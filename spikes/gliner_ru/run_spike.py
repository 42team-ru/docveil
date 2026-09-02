"""Главный runner спайка GLiNER2 на русском.

Гоняет 3 модели × 3-4 стратегии × 3 порога на фикстуре из
spike_labels.json, считает per-type P/R/F1 (exact и overlap>=50%) и
пишет markdown-таблицу в results/{timestamp}.md.

Запуск:

    uv run --with gliner --with gliner2 --with 'torch>=2.0' \
        --with python-docx \
        --index https://download.pytorch.org/whl/cpu \
        python spikes/gliner_ru/run_spike.py
"""

from __future__ import annotations

import datetime as dt
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from fixture_loader import load_phrases

# --- модели и стратегии ---------------------------------------------------

MODELS = [
    ("M1", "urchade/gliner_multi-v2.1", "gliner"),
    ("M2", "fastino/gliner2.5-multi-v1", "gliner2"),
    ("M3", "nvidia/gliner-PII", "gliner"),
    ("M4", "fastino/gliner2-privacy-filter-PII-multi", "gliner2"),
]

TYPES = [
    # Класс C — то, ради чего изначально брали GLiNER
    "job_title",
    "department",
    "product_name",
    "certification_number",
    # Класс D — семантическая роль поверх формата
    "shipment_date",
    "signing_date",
    # Natasha territory — проверяем, не бьёт ли GLiNER2 Natasha на её же поле
    "person",
    "org_name",
    "location",
]

# --- стратегии подачи лейблов ---------------------------------------------

S1_EN_LABELS = list(TYPES)

S2_RU_LABELS = [
    "должность",
    "отдел",
    "наименование товара",
    "номер лицензии",
    "дата отгрузки",
    "дата подписания",
    "фамилия имя отчество",
    "название организации",
    "город",
]

# Обратный маппинг S2 -> canonical (по индексу — порядок сохраняется)
S2_TO_CANONICAL = dict(zip(S2_RU_LABELS, TYPES, strict=True))

# S3: лейбл + краткое описание — подаётся как dict {label_ru: description}
S3_LABEL_DESCRIPTIONS = {
    "должность": "должность или профессия человека в компании, например директор, главный инженер, заместитель по производству",
    "отдел": "структурное подразделение организации, например отдел закупок, служба безопасности, финансовое управление",
    "наименование товара": "название конкретного товара, продукта или изделия, например Резистор МЛТ-0,25 или программное обеспечение",
    "номер лицензии": "номер лицензии, сертификата соответствия или свидетельства СРО",
    "дата отгрузки": "дата фактической отгрузки товара со склада, в формате dd.mm.yyyy",
    "дата подписания": "дата подписания или заключения договора между сторонами, в формате dd.mm.yyyy",
    "фамилия имя отчество": "имя человека, полное или инициалы: фамилия имя отчество",
    "название организации": "название юридического лица: ООО, АО, ИП, полная или сокращённая форма",
    "город": "название города или населённого пункта",
}
S3_TO_CANONICAL = dict(zip(S3_LABEL_DESCRIPTIONS.keys(), TYPES, strict=True))

THRESHOLDS = [0.3, 0.5, 0.7]


# --- метрики --------------------------------------------------------------


def iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    if inter == 0:
        return 0.0
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union


def evaluate(
    gt_by_phrase: list[list[dict[str, Any]]],
    pred_by_phrase: list[list[dict[str, Any]]],
) -> dict[str, dict[str, dict[str, float]]]:
    """
    Возвращает: {mode: {type: {p, r, f1, tp, fp, fn}}}, где mode in {'exact','overlap'}.
    """
    result: dict[str, dict[str, dict[str, float]]] = {}
    for mode in ("exact", "overlap"):
        tp: dict[str, int] = defaultdict(int)
        fp: dict[str, int] = defaultdict(int)
        fn: dict[str, int] = defaultdict(int)
        for gts, preds in zip(gt_by_phrase, pred_by_phrase, strict=True):
            matched_gt: set[int] = set()
            for pred in preds:
                pt = pred["type"]
                pa = (pred["start"], pred["end"])
                found = None
                for gi, gt in enumerate(gts):
                    if gi in matched_gt or gt["type"] != pt:
                        continue
                    ga = (gt["start"], gt["end"])
                    if mode == "exact" and pa == ga:
                        found = gi
                        break
                    if mode == "overlap" and iou(pa, ga) >= 0.5:
                        found = gi
                        break
                if found is not None:
                    matched_gt.add(found)
                    tp[pt] += 1
                else:
                    fp[pt] += 1
            for gi, gt in enumerate(gts):
                if gi not in matched_gt:
                    fn[gt["type"]] += 1
        per_type: dict[str, dict[str, float]] = {}
        for t in TYPES:
            p = tp[t] / (tp[t] + fp[t]) if (tp[t] + fp[t]) else 0.0
            r = tp[t] / (tp[t] + fn[t]) if (tp[t] + fn[t]) else 0.0
            f1 = 2 * p * r / (p + r) if (p + r) else 0.0
            per_type[t] = {
                "p": round(p, 3),
                "r": round(r, 3),
                "f1": round(f1, 3),
                "tp": tp[t],
                "fp": fp[t],
                "fn": fn[t],
            }
        result[mode] = per_type
    return result


# --- обёртки моделей ------------------------------------------------------


def load_gliner_v1(model_id: str):
    from gliner import GLiNER

    return GLiNER.from_pretrained(model_id)


def load_gliner_v2(model_id: str):
    # Пробуем возможные точки входа. GLiNER2 может экспортировать разные API.
    try:
        from gliner2 import GLiNER2  # type: ignore

        return ("GLiNER2", GLiNER2.from_pretrained(model_id))
    except Exception as e1:
        try:
            from gliner2 import AutoExtractor  # type: ignore

            return ("AutoExtractor", AutoExtractor.from_pretrained(model_id))
        except Exception as e2:
            try:
                # Fallback: gliner API совместимость
                from gliner import GLiNER

                return ("GLiNER-compat", GLiNER.from_pretrained(model_id))
            except Exception as e3:
                raise RuntimeError(
                    f"Не удалось загрузить {model_id} ни через GLiNER2, ни AutoExtractor, ни GLiNER-compat: "
                    f"{e1!r} / {e2!r} / {e3!r}"
                ) from e3


def predict_v1(
    model, text: str, labels: list[str] | dict[str, str], threshold: float
) -> list[dict[str, Any]]:
    # GLiNER v1 не принимает dict — если пришёл dict (S3), берём ключи как labels.
    if isinstance(labels, dict):
        labels = list(labels.keys())
    ents = model.predict_entities(text, labels, threshold=threshold)
    return [
        {"type": e["label"], "start": e["start"], "end": e["end"], "text": e["text"]} for e in ents
    ]


def predict_v2_flat(
    model_bundle, text: str, labels: list[str] | dict[str, str], threshold: float
) -> list[dict[str, Any]]:
    kind, model = model_bundle
    # Пробуем extract_entities, потом predict_entities.
    for method_name in ("extract_entities", "predict_entities"):
        method = getattr(model, method_name, None)
        if method is None:
            continue
        try:
            if isinstance(labels, dict):
                # Некоторые версии принимают dict; иначе передаём keys.
                try:
                    ents = method(text, labels, threshold=threshold)
                except (TypeError, ValueError):
                    ents = method(text, list(labels.keys()), threshold=threshold)
            else:
                ents = method(text, labels, threshold=threshold)
            # GLiNER2 отдаёт {'entities': {label: [text, ...]}} без оффсетов
            if isinstance(ents, dict) and "entities" in ents and isinstance(ents["entities"], dict):
                return _spans_from_label_texts(ents["entities"], text)
            return _normalize_ents(ents)
        except Exception:
            continue
    raise RuntimeError(f"Модель {kind} не поддерживает ни extract_entities, ни predict_entities")


def _spans_from_label_texts(
    label_to_texts: dict[str, list[str]], text: str
) -> list[dict[str, Any]]:
    """GLiNER2 возвращает только текст спанов. Ищем позиции через find().

    Если один и тот же текст встречается N раз в спанах модели — берём N первых
    вхождений подряд из text.
    """
    out: list[dict[str, Any]] = []
    for label, texts in label_to_texts.items():
        if not isinstance(texts, list):
            continue
        # Считаем, сколько раз модель предсказала каждый текст
        from collections import Counter

        counts = Counter(texts)
        for span_text, count in counts.items():
            if not span_text:
                continue
            search_from = 0
            for _ in range(count):
                idx = text.find(span_text, search_from)
                if idx < 0:
                    break
                out.append(
                    {"type": label, "start": idx, "end": idx + len(span_text), "text": span_text}
                )
                search_from = idx + len(span_text)
    return out


def _normalize_ents(ents: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not ents:
        return out
    for e in ents:
        # Разные модели могут возвращать разные поля
        if isinstance(e, dict):
            typ = e.get("label") or e.get("type") or e.get("entity") or e.get("class")
            start = e.get("start")
            end = e.get("end")
            txt = e.get("text") or e.get("span")
            if typ is None or start is None or end is None:
                continue
            out.append({"type": typ, "start": start, "end": end, "text": txt or ""})
        else:
            # Возможно, tuple/dataclass — пропускаем
            continue
    return out


def try_predict_structure(model_bundle, text: str, threshold: float) -> list[dict[str, Any]] | None:
    """Пробуем hierarchical structure API GLiNER2 для класса D.

    Возвращаем список нормализованных спанов (type=shipment_date|signing_date)
    или None, если API недоступно.
    """
    kind, model = model_bundle
    create_schema = getattr(model, "create_schema", None)
    if create_schema is None:
        return None
    try:
        schema = (
            create_schema()
            .structure("shipment")
            .field("date", dtype="str", description="дата отгрузки товара со склада")
            .field("quantity", dtype="str", description="количество отгруженного товара")
            .structure("signing")
            .field(
                "date", dtype="str", description="дата подписания или заключения договора сторонами"
            )
        )
    except Exception:
        return None
    for method_name in ("extract", "predict", "run"):
        method = getattr(model, method_name, None)
        if method is None:
            continue
        try:
            try:
                result = method(text, schema, threshold=threshold)
            except TypeError:
                result = method(text, schema)
            return _extract_structure_spans(result, text)
        except Exception:
            continue
    return None


def _extract_structure_spans(result: Any, text: str) -> list[dict[str, Any]]:
    """Пытаемся достать shipment.date / signing.date из результата structure API.

    Формат вывода в разных версиях разный — пробуем несколько вариантов.
    """
    out: list[dict[str, Any]] = []

    def try_add(struct_name: str, field_name: str, value: Any) -> None:
        if not value:
            return
        # value может быть str, dict {value/text/start/end}, list
        if isinstance(value, str):
            idx = text.find(value)
            if idx >= 0:
                out.append(
                    {
                        "type": _canonical_for_structure(struct_name, field_name),
                        "start": idx,
                        "end": idx + len(value),
                        "text": value,
                    }
                )
            return
        if isinstance(value, dict):
            span_text = value.get("value") or value.get("text")
            start = value.get("start")
            end = value.get("end")
            if start is not None and end is not None and span_text:
                out.append(
                    {
                        "type": _canonical_for_structure(struct_name, field_name),
                        "start": start,
                        "end": end,
                        "text": span_text,
                    }
                )
            elif span_text:
                idx = text.find(span_text)
                if idx >= 0:
                    out.append(
                        {
                            "type": _canonical_for_structure(struct_name, field_name),
                            "start": idx,
                            "end": idx + len(span_text),
                            "text": span_text,
                        }
                    )
            return
        if isinstance(value, list):
            for v in value:
                try_add(struct_name, field_name, v)

    if isinstance(result, dict):
        # Плоское извлечение
        for struct_name in ("shipment", "signing"):
            struct = result.get(struct_name) or result.get("structures", {}).get(struct_name)
            if isinstance(struct, dict):
                for field_name, val in struct.items():
                    try_add(struct_name, field_name, val)
            elif isinstance(struct, list):
                for item in struct:
                    if isinstance(item, dict):
                        for field_name, val in item.items():
                            try_add(struct_name, field_name, val)
    return out


def _canonical_for_structure(struct_name: str, field_name: str) -> str:
    if struct_name == "shipment" and field_name == "date":
        return "shipment_date"
    if struct_name == "signing" and field_name == "date":
        return "signing_date"
    return f"{struct_name}_{field_name}"


# --- прогон ---------------------------------------------------------------


def run_all(phrases: list[dict[str, Any]]) -> dict[str, Any]:
    gt_by_phrase = [p["spans"] for p in phrases]
    texts = [p["text"] for p in phrases]

    runs: list[dict[str, Any]] = []
    load_times: dict[str, float] = {}
    inference_times: dict[str, float] = {}
    load_errors: dict[str, str] = {}

    for model_id, hf_name, kind in MODELS:
        print(f"\n=== Загружаю {model_id} = {hf_name} ({kind}) ===", flush=True)
        t0 = time.perf_counter()
        try:
            if kind == "gliner":
                model_bundle = ("GLiNER", load_gliner_v1(hf_name))
                predictor = predict_v1
            else:
                model_bundle = load_gliner_v2(hf_name)
                predictor = predict_v2_flat
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"  ОШИБКА загрузки: {err}", flush=True)
            load_errors[model_id] = err
            traceback.print_exc()
            continue
        load_times[model_id] = time.perf_counter() - t0
        print(f"  загружено за {load_times[model_id]:.2f}s", flush=True)

        strategies: list[tuple[str, str, Any]] = [
            ("S1", "EN labels", S1_EN_LABELS),
            ("S2", "RU labels", S2_RU_LABELS),
            ("S3", "RU labels + descriptions", S3_LABEL_DESCRIPTIONS),
        ]

        inf_samples: list[float] = []
        for strat_id, strat_name, labels in strategies:
            # Маппинг обратно к каноническому типу
            if strat_id == "S1":
                to_canonical = {t: t for t in TYPES}
            elif strat_id == "S2":
                to_canonical = S2_TO_CANONICAL
            else:
                to_canonical = S3_TO_CANONICAL

            for th in THRESHOLDS:
                preds_by_phrase: list[list[dict[str, Any]]] = []
                t_inf_start = time.perf_counter()
                errors_here = 0
                for text in texts:
                    try:
                        if kind == "gliner":
                            ents = predictor(model_bundle[1], text, labels, th)
                        else:
                            ents = predictor(model_bundle, text, labels, th)
                    except Exception as e:
                        errors_here += 1
                        ents = []
                        if errors_here == 1:
                            print(
                                f"    inference error {strat_id}@{th}: {type(e).__name__}: {e}",
                                flush=True,
                            )
                    # Приводим типы к каноническим
                    canonical_ents = []
                    for e in ents:
                        raw_t = e["type"]
                        c_t = to_canonical.get(raw_t, raw_t)
                        if c_t in TYPES:
                            canonical_ents.append({**e, "type": c_t})
                    preds_by_phrase.append(canonical_ents)
                t_inf = (time.perf_counter() - t_inf_start) / max(1, len(texts)) * 1000
                inf_samples.append(t_inf)
                metrics = evaluate(gt_by_phrase, preds_by_phrase)
                runs.append(
                    {
                        "model": model_id,
                        "hf": hf_name,
                        "strategy": strat_id,
                        "strategy_name": strat_name,
                        "threshold": th,
                        "metrics": metrics,
                        "inference_ms": round(t_inf, 1),
                        "errors": errors_here,
                    }
                )
                avg_f1_overlap = sum(metrics["overlap"][t]["f1"] for t in TYPES) / len(TYPES)
                print(
                    f"  {strat_id}@{th}: avg_f1_overlap={avg_f1_overlap:.3f} "
                    f"({t_inf:.0f}ms/фраза, errors={errors_here})",
                    flush=True,
                )

        # S4 — structure API только для GLiNER2 моделей
        if kind == "gliner2":
            structure_available = False
            for th in THRESHOLDS:
                preds_by_phrase = []
                t_inf_start = time.perf_counter()
                errors_here = 0
                any_api_ok = False
                for text in texts:
                    res = try_predict_structure(model_bundle, text, th)
                    if res is None:
                        preds_by_phrase.append([])
                        continue
                    any_api_ok = True
                    preds_by_phrase.append([e for e in res if e["type"] in TYPES])
                if not any_api_ok:
                    print(f"  S4@{th}: structure API недоступно на этой модели", flush=True)
                    runs.append(
                        {
                            "model": model_id,
                            "hf": hf_name,
                            "strategy": "S4",
                            "strategy_name": "hierarchical structure",
                            "threshold": th,
                            "metrics": None,
                            "inference_ms": None,
                            "errors": len(texts),
                            "note": "structure API недоступно",
                        }
                    )
                    continue
                structure_available = True
                t_inf = (time.perf_counter() - t_inf_start) / max(1, len(texts)) * 1000
                metrics = evaluate(gt_by_phrase, preds_by_phrase)
                d_f1 = (
                    metrics["overlap"]["shipment_date"]["f1"]
                    + metrics["overlap"]["signing_date"]["f1"]
                ) / 2
                print(
                    f"  S4@{th}: avg_f1_D={d_f1:.3f} ({t_inf:.0f}ms/фраза)",
                    flush=True,
                )
                runs.append(
                    {
                        "model": model_id,
                        "hf": hf_name,
                        "strategy": "S4",
                        "strategy_name": "hierarchical structure",
                        "threshold": th,
                        "metrics": metrics,
                        "inference_ms": round(t_inf, 1),
                        "errors": errors_here,
                    }
                )
            if not structure_available:
                pass  # уже записали ноты

        inference_times[model_id] = sum(inf_samples) / max(1, len(inf_samples))

    return {
        "runs": runs,
        "load_times": load_times,
        "inference_times": inference_times,
        "load_errors": load_errors,
    }


# --- отчёт ----------------------------------------------------------------


def write_report(
    phrases: list[dict[str, Any]],
    results: dict[str, Any],
    out_path: Path,
) -> None:
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    total_spans = sum(len(p["spans"]) for p in phrases)

    lines: list[str] = []
    lines.append(f"# Spike: GLiNER2 на русском — результаты {now}\n")
    lines.append("## Обзор\n")
    lines.append(f"- всего фраз: {len(phrases)}, всего спанов: {total_spans}")
    lines.append(f"- моделей заявлено: {len(MODELS)}, загружено: {len(results['load_times'])}")
    lines.append(
        "- стратегий: S1 EN labels, S2 RU labels, S3 RU+descriptions, S4 structure (только GLiNER2)"
    )
    lines.append(f"- пороги: {THRESHOLDS}")
    try:
        import platform

        import torch  # noqa: F401

        lines.append(f"- CPU: {platform.processor() or platform.machine()}, torch threads: 4")
    except Exception:
        lines.append("- torch: не импортирован в отчёт")
    lines.append("")

    if results["load_errors"]:
        lines.append("## Ошибки загрузки\n")
        for m, e in results["load_errors"].items():
            lines.append(f"- **{m}**: {e}")
        lines.append("")

    def fmt_val(v: float) -> str:
        return f"{v:.3f}" if isinstance(v, (int, float)) else "—"

    # Основная таблица F1 (overlap, threshold=0.5)
    lines.append("## F1 по типам (overlap ≥ 50%, порог 0.5)\n")
    header = "| Model | Strategy | " + " | ".join(TYPES) + " | AVG |"
    sep = "|" + "|".join(["---"] * (len(TYPES) + 3)) + "|"
    lines.append(header)
    lines.append(sep)
    for run in results["runs"]:
        if run["threshold"] != 0.5 or run["metrics"] is None:
            continue
        f1s = [run["metrics"]["overlap"][t]["f1"] for t in TYPES]
        avg = sum(f1s) / len(f1s)
        row = f"| {run['model']} | {run['strategy']} {run['strategy_name']} | "
        row += " | ".join(fmt_val(x) for x in f1s)
        row += f" | {avg:.3f} |"
        lines.append(row)
    lines.append("")

    # Precision / Recall — та же ось
    lines.append("## Precision / Recall (overlap, порог 0.5)\n")
    lines.append("| Model | Strategy | Type | P | R | F1 | TP | FP | FN |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for run in results["runs"]:
        if run["threshold"] != 0.5 or run["metrics"] is None:
            continue
        for t in TYPES:
            m = run["metrics"]["overlap"][t]
            lines.append(
                f"| {run['model']} | {run['strategy']} | {t} | "
                f"{m['p']:.3f} | {m['r']:.3f} | {m['f1']:.3f} | "
                f"{m['tp']} | {m['fp']} | {m['fn']} |"
            )
    lines.append("")

    # Exact match отдельная таблица
    lines.append("## F1 exact match (порог 0.5)\n")
    lines.append(header)
    lines.append(sep)
    for run in results["runs"]:
        if run["threshold"] != 0.5 or run["metrics"] is None:
            continue
        f1s = [run["metrics"]["exact"][t]["f1"] for t in TYPES]
        avg = sum(f1s) / len(f1s)
        row = f"| {run['model']} | {run['strategy']} {run['strategy_name']} | "
        row += " | ".join(fmt_val(x) for x in f1s)
        row += f" | {avg:.3f} |"
        lines.append(row)
    lines.append("")

    # Влияние порога — сокращённо: overlap AVG F1 по каждому порогу
    lines.append("## Влияние порога (AVG F1 overlap по всем типам)\n")
    lines.append("| Model | Strategy | th=0.3 | th=0.5 | th=0.7 |")
    lines.append("|---|---|---|---|---|")
    grouped: dict[tuple[str, str], dict[float, float]] = defaultdict(dict)
    for run in results["runs"]:
        if run["metrics"] is None:
            continue
        f1s = [run["metrics"]["overlap"][t]["f1"] for t in TYPES]
        grouped[(run["model"], run["strategy"])][run["threshold"]] = sum(f1s) / len(f1s)
    for (m, s), th_map in grouped.items():
        row = f"| {m} | {s} | "
        row += " | ".join(f"{th_map.get(th, 0):.3f}" if th in th_map else "—" for th in THRESHOLDS)
        row += " |"
        lines.append(row)
    lines.append("")

    # Класс D: structure API
    lines.append("## Класс D: hierarchical structure API (S4)\n")
    s4_runs = [r for r in results["runs"] if r["strategy"] == "S4"]
    if not s4_runs:
        lines.append("Не запускалось (нет GLiNER2 моделей).\n")
    else:
        lines.append("| Model | th | shipment_date P/R/F1 | signing_date P/R/F1 | note |")
        lines.append("|---|---|---|---|---|")
        for r in s4_runs:
            note = r.get("note", "")
            if r["metrics"] is None:
                lines.append(f"| {r['model']} | {r['threshold']} | — | — | {note} |")
                continue
            ms = r["metrics"]["overlap"]["shipment_date"]
            sg = r["metrics"]["overlap"]["signing_date"]
            lines.append(
                f"| {r['model']} | {r['threshold']} | "
                f"{ms['p']:.2f}/{ms['r']:.2f}/{ms['f1']:.2f} | "
                f"{sg['p']:.2f}/{sg['r']:.2f}/{sg['f1']:.2f} | {note} |"
            )
    lines.append("")

    # Загрузка + инференс
    lines.append("## Загрузка и инференс\n")
    lines.append("| Model | Load (s) | Inference avg (ms/paragraph) |")
    lines.append("|---|---|---|")
    for m, _hf, _k in MODELS:
        load = results["load_times"].get(m)
        inf = results["inference_times"].get(m)
        lines.append(f"| {m} | {f'{load:.2f}' if load else '—'} | {f'{inf:.1f}' if inf else '—'} |")
    lines.append("")

    # Наблюдения (полу-авто по цифрам)
    best_by_type: dict[str, tuple[str, str, float, float]] = {}
    for run in results["runs"]:
        if run["metrics"] is None:
            continue
        for t in TYPES:
            f1 = run["metrics"]["overlap"][t]["f1"]
            cur = best_by_type.get(t)
            if cur is None or f1 > cur[2]:
                best_by_type[t] = (run["model"], run["strategy"], f1, run["threshold"])
    lines.append("## Лучшая F1 по типам (overlap, любой конфиг)\n")
    lines.append("| Type | Model | Strategy | th | F1 |")
    lines.append("|---|---|---|---|---|")
    for t in TYPES:
        cur = best_by_type.get(t)
        if cur is None:
            lines.append(f"| {t} | — | — | — | — |")
        else:
            lines.append(f"| {t} | {cur[0]} | {cur[1]} | {cur[3]} | {cur[2]:.3f} |")
    lines.append("")

    # Вердикт: критерии из плана
    best_class_c_f1 = 0.0
    for t in ("job_title", "department", "product_name", "certification_number"):
        cur = best_by_type.get(t)
        if cur:
            best_class_c_f1 = max(best_class_c_f1, cur[2])
    lines.append("## Вердикт\n")
    if best_class_c_f1 >= 0.7:
        verdict = "GREEN: одна из моделей даёт F1 >= 0.7 хотя бы по одному классу C"
    elif best_class_c_f1 >= 0.4:
        verdict = "YELLOW: F1 в диапазоне 0.4-0.7 — обсудить fine-tuning или human-preview"
    else:
        verdict = "RED: F1 < 0.4 на всех моделях — GLiNER не тащим, оставляем regex+LLM"
    lines.append(f"- **{verdict}**")
    lines.append(f"- лучший F1 по классу C: **{best_class_c_f1:.3f}**")
    d_best = 0.0
    for t in ("shipment_date", "signing_date"):
        cur = best_by_type.get(t)
        if cur:
            d_best = max(d_best, cur[2])
    lines.append(f"- лучший F1 по классу D (shipment/signing_date): **{d_best:.3f}**")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nОтчёт: {out_path}", flush=True)


def main() -> int:
    try:
        import torch

        torch.set_num_threads(4)
    except ImportError:
        print("WARN: torch не найден в этом интерпретаторе — модели не загрузятся", flush=True)

    phrases = load_phrases()
    total_spans = sum(len(p["spans"]) for p in phrases)
    print(f"Фикстура: {len(phrases)} фраз, {total_spans} спанов", flush=True)

    results = run_all(phrases)

    results_dir = Path(__file__).with_name("results")
    results_dir.mkdir(exist_ok=True)
    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H%M%SZ")
    out_path = results_dir / f"{ts}.md"
    write_report(phrases, results, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
