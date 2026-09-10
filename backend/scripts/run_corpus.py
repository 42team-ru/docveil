"""Прогон корпуса в одной конфигурации: метрики + замаскированные файлы для глаз.

Зачем отдельно от `bench_matrix`. Тот отвечает на вопрос «какая конфигурация
лучше по числам», и артефакты выбрасывает. Здесь задача другая: получить
**и** числа, **и** сами файлы, чтобы человек открыл документ и посмотрел,
что именно замазано. Ни одна метрика не заменяет взгляда на страницу: она
не покажет, что маркер съехал, что подсветка накрыла чужое слово или что
замазан весь абзац вместо одного слова.

Каждый прогон складывается в свой каталог с меткой конфигурации и временем,
поэтому прогоны можно сравнивать между собой, а не переписывать числа из
терминала.

    # базовый прогон, без модели
    python scripts/run_corpus.py fixtures/real/open-contracts

    # только правила, без Natasha
    python scripts/run_corpus.py fixtures/real/open-contracts --layer rules

    # с GLiNER на пользовательских типах
    python scripts/run_corpus.py fixtures/real/open-contracts --layer gliner

    # с живой моделью (нужен ключ в окружении)
    python scripts/run_corpus.py fixtures/real/open-contracts --llm gigachat-max

Сравнить два прогона:

    python scripts/compare_runs.py out/runs/ner-none-* out/runs/gliner-none-*
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time
import warnings
from typing import Any

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_OUT = ROOT / "out" / "runs"


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _labels_for(document: pathlib.Path) -> list[dict[str, Any]]:
    """Разметка рядом с документом, если она есть.

    Ищутся оба написания: `файл.pdf.labels.json` и `файл.labels.json` —
    в корпусах проекта встречаются оба, и требовать одно значило бы молча
    не найти половину эталона.
    """
    for candidate in (
        document.with_name(document.name + ".labels.json"),
        document.with_suffix(".labels.json"),
    ):
        if candidate.is_file():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            return payload.get("entities", [])
    return []


def _custom_types_for(document: pathlib.Path) -> list[dict[str, Any]]:
    for candidate in (
        document.with_name(document.name + ".labels.json"),
        document.with_suffix(".labels.json"),
    ):
        if candidate.is_file():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            return payload.get("custom_types", [])
    return []


def run_corpus(
    corpus: pathlib.Path,
    *,
    layer: str,
    llm_profile: str,
    out_root: pathlib.Path,
    keep_artifacts: bool,
) -> dict[str, Any]:
    """Прогнать все документы каталога и сложить результат в новый каталог."""
    from masker.model import CRITICAL_TYPES, EntityType
    from masker.pipeline import mask_and_validate

    provider = None
    if llm_profile != "none":
        from masker.config import project_section
        from masker.llm import get_provider
        from masker.llm.config import llm_config_from_mapping

        settings = {**project_section("llm"), "profile": llm_profile}
        provider = get_provider(llm_config_from_mapping(settings))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / f"{layer}-{llm_profile}-{stamp}"
    (out_dir / "documents").mkdir(parents=True, exist_ok=True)

    documents = sorted(
        p
        for p in corpus.iterdir()
        if p.suffix.casefold() in {".pdf", ".docx", ".xlsx"} and not p.name.startswith(".")
    )
    critical = {c.value for c in CRITICAL_TYPES}
    per_document: list[dict[str, Any]] = []
    started_all = time.perf_counter()

    print(f"конфигурация: слой {layer}, модель {llm_profile}")
    print(f"документов:   {len(documents)}")
    print(f"результат:    {out_dir}\n")

    for index, document in enumerate(documents, 1):
        print(f"  [{index}/{len(documents)}] {document.name} … ", end="", flush=True)
        gold = _labels_for(document)
        started = time.perf_counter()
        record: dict[str, Any] = {"document": document.name, "gold_entities": len(gold)}
        try:
            with mask_and_validate(
                document,
                types=list(EntityType),
                custom_types=_custom_types_for(document),
                rules_only=(layer == "rules"),
                llm=provider,
            ) as result:
                elapsed = time.perf_counter() - started
                found = {
                    (r.entity.type, _collapse(r.entity.text)) for r in result.plan.replacements
                }
                expected = {(g["type"], _collapse(g["text"])) for g in gold}
                hit = expected & found
                crit_expected = {k for k in expected if k[0] in critical}
                crit_hit = {k for k in hit if k[0] in critical}
                leaked = list(result.validation.leaked)
                record |= {
                    "found": len(found),
                    "matched_gold": len(hit),
                    "recall": len(hit) / len(expected) if expected else None,
                    "critical_expected": len(crit_expected),
                    "critical_found": len(crit_hit),
                    "critical_recall": (
                        len(crit_hit) / len(crit_expected) if crit_expected else None
                    ),
                    "leaked": len(leaked),
                    "leaked_detail": [
                        {
                            "type": item.entity_type,
                            "value": item.value,
                            "artifact": item.artifact,
                            "part": item.part,
                        }
                        for item in leaked[:10]
                    ],
                    "missed": sorted(f"{t}: {v}" for t, v in (expected - found))[:40],
                    "seconds": round(elapsed, 2),
                    "status": "ok",
                }
                if keep_artifacts:
                    target = out_dir / "documents" / document.stem
                    target.mkdir(parents=True, exist_ok=True)
                    # `MaskResult.artifacts` — кортеж путей (`pipeline.py:101`),
                    # а не словарей: каталог живёт только внутри `with`, поэтому
                    # копировать надо здесь, а не после выхода из блока.
                    for artifact in result.artifacts:
                        source = pathlib.Path(artifact)
                        if source.is_file():
                            shutil.copy2(source, target / source.name)
                mark = "утечек " + str(len(leaked)) if leaked else "чисто"
                print(f"{len(found):4} замен, {mark}, {elapsed:.1f} с")
        except Exception as error:
            record |= {"status": "failed", "error": f"{type(error).__name__}: {error}"}
            print(f"ОШИБКА {type(error).__name__}: {error}")
        per_document.append(record)

    ok = [r for r in per_document if r.get("status") == "ok"]
    graded = [r for r in ok if r.get("recall") is not None]
    crit_graded = [r for r in ok if r.get("critical_recall") is not None]
    summary = {
        "configuration": {"layer": layer, "llm_profile": llm_profile},
        "corpus": str(corpus),
        "finished_at": stamp,
        "documents": len(documents),
        "succeeded": len(ok),
        "failed": len(documents) - len(ok),
        "leaked_total": sum(r.get("leaked", 0) for r in ok),
        "recall": (
            sum(r["matched_gold"] for r in graded) / sum(r["gold_entities"] for r in graded)
            if graded and sum(r["gold_entities"] for r in graded)
            else None
        ),
        "critical_recall": (
            sum(r["critical_found"] for r in crit_graded)
            / sum(r["critical_expected"] for r in crit_graded)
            if crit_graded and sum(r["critical_expected"] for r in crit_graded)
            else None
        ),
        "seconds": round(time.perf_counter() - started_all, 1),
        "per_document": per_document,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\n{'=' * 60}")
    print(f"документов обработано: {summary['succeeded']} из {summary['documents']}")
    if summary["critical_recall"] is not None:
        print(f"recall критичных типов: {summary['critical_recall']:.3f}")
    if summary["recall"] is not None:
        print(f"recall общий:           {summary['recall']:.3f}")
    leaked_total = summary["leaked_total"]
    print(f"утечек:                 {leaked_total}" + ("  ← РАЗБИРАТЬ" if leaked_total else ""))
    print(f"время:                  {summary['seconds']} с")
    print(f"\nчисла:          {out_dir / 'summary.json'}")
    if keep_artifacts:
        print(f"файлы глазами:  {out_dir / 'documents'}")
        print("\nПосмотрите masked_black.* и masked_highlight.* — метрика не показывает,")
        print("что маркер съехал или что замазан лишний кусок текста.")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=pathlib.Path, help="каталог с документами")
    parser.add_argument(
        "--layer",
        default="ner",
        choices=("rules", "ner", "gliner"),
        help="слой детекции: rules — только регулярки, ner — плюс Natasha (по умолчанию), "
        "gliner — плюс GLiNER на пользовательских типах",
    )
    parser.add_argument(
        "--llm",
        default="none",
        dest="llm_profile",
        help="профиль модели из llm.profiles в masker.yaml (по умолчанию none — без модели)",
    )
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT, help="куда складывать")
    parser.add_argument(
        "--no-artifacts",
        action="store_true",
        help="не копировать замаскированные файлы (быстрее, но смотреть будет нечего)",
    )
    args = parser.parse_args(argv)

    if not args.corpus.is_dir():
        print(f"нет каталога {args.corpus}", file=sys.stderr)
        return 2
    summary = run_corpus(
        args.corpus,
        layer=args.layer,
        llm_profile=args.llm_profile,
        out_root=args.out,
        keep_artifacts=not args.no_artifacts,
    )
    # Ненулевой код только на сбоях прогона: утечки печатаются, но решение
    # по ним принимает человек, а не скрипт.
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
