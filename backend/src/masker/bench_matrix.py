"""К4 — матричный бенчмарк: слои детекции × провайдеры LLM (`make bench-matrix`).

Отвечает числами на два вопроса, которые сегодня закрыты мнениями, а не
цифрами: **нужен ли GLiNER** и **что реально даёт LLM**. Не входит в
``make gate`` и не запускается по умолчанию — живые провайдеры (GigaChat,
OpenRouter) стоят денег и требуют сети (AGENTS.md, «Дешёвая проверка во
время работы»).

Две независимые оси, не полное декартово произведение (см. докстринг
``run`` — там объяснено, какие сочетания пропущены и почему):

- **Ось 1 — слой детекции** (``rules`` / ``ner`` / ``gliner``): P/R/F1 по
  основному корпусу ``fixtures/labeled`` через ``masker.eval._mask_corpus``
  (тот же граф, что и ``make eval``, только с ``rules_only`` из
  ``RunOptions``). Слой ``gliner`` меряется на отдельном корпусе
  (``fixtures/gliner/contract_10_roles_dates.*``, класс D из
  ``tests/masker/detect/test_gliner_corpus.py``) — в ``fixtures/labeled``
  нет ни одного документа с ``gliner_*`` пользовательским типом, поэтому на
  основном корпусе слой ``gliner`` буквально не отличим от ``ner``.
- **Ось 2 — провайдер LLM** (``none`` / ``cassette`` / ``gigachat`` /
  ``openrouter``): ``role_accuracy``/``cluster_purity`` через
  ``masker.eval._profile_judge_metrics`` — тот же прямой вызов
  ``ProfileAgent``/``JudgeAgent``, что и в ``make eval``, только провайдер
  собирается из именованного профиля ``llm.profiles`` в ``masker.yaml``
  (заказ №6 — провайдер только через ``LLMProvider`` из ``masker.llm``).

Ресурсы (вызовы/токены/стоимость) берутся из ``masker.telemetry`` —
``MeteringProvider`` оборачивает провайдер тем же способом, что и граф в
проде, поэтому числа сопоставимы с ``runtime-metrics.json`` боевого прогона.

Недетерминированность живых моделей (требование задания №4): числа в
строках ``gigachat``/``openrouter`` — **один прогон**, не среднее. Повторный
запуск с той же кассетой/тем же fake — детерминирован, повторный запуск с
живой моделью может дать другое число того же порядка.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import logging
import os
import pathlib
import sys
import time
import warnings
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from typing import Any

import masker.eval as eval_module
from masker.config import project_section
from masker.detect.address import AddressDetector
from masker.detect.agent import DetectAgent
from masker.detect.base import EntityDetector
from masker.detect.contract_params import (
    ContractAmountDetector,
    DeliveryPeriodDetector,
    PaymentTermsDetector,
)
from masker.detect.dates import DateDetector
from masker.detect.rules import RuleDetector
from masker.llm import LLMConfig, LLMError, get_provider
from masker.llm.config import llm_config_from_mapping
from masker.telemetry import LLMPricing, MeteringProvider, report_telemetry

#: Профиль ``llm.profiles`` (``masker.yaml``) для каждой оси 2. ``none`` —
#: детерминированная заглушка (без сети), остальные три — живые/записанные
#: провайдеры, объявленные в масштабах проекта, а не своим параллельным
#: механизмом конфигурации.
_LLM_PROFILE_BY_AXIS: dict[str, str] = {
    "none": "fake",
    "cassette": "cassette",
    "gigachat": "gigachat-max",
    "openrouter": "openrouter-deepseek-flash",
    # Ось-потолок. Нужна не для продакшена, а чтобы отличить «задача уже
    # решена эвристикой» от «эта конкретная модель слаба»: если сильная
    # модель даёт ту же точность ролей, что и эвристика, LLM в этой задаче
    # не поможет никакая, и дальше её тюнить бессмысленно.
    "ceiling": "openrouter-deepseek-pro",
}
LLM_AXES: tuple[str, ...] = ("none", "cassette", "gigachat", "openrouter", "ceiling")
DETECTION_LAYERS: tuple[str, ...] = ("rules", "ner", "gliner")

GLINER_FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "gliner"
GLINER_DOC = GLINER_FIXTURES / "contract_10_roles_dates.docx"
GLINER_LABELS = GLINER_FIXTURES / "contract_10_roles_dates.labels.json"
#: Порог из T1.13.1 (шаг 17, `test_gliner_corpus.py`) — сюда не переносится
#: как ворота (`make gate` этот модуль не гоняет), только как ориентир в
#: печати, чтобы число было с чем сравнить, а не голым.
GLINER_ACCEPTANCE_F1 = 0.9


def gliner_available() -> bool:
    """Установлен ли пакет ``gliner2`` в текущем окружении."""
    return importlib.util.find_spec("gliner2") is not None


def llm_axis_config(axis: str) -> LLMConfig:
    """Собрать ``LLMConfig`` выбранного профиля ``masker.yaml`` для оси 2."""
    profile = _LLM_PROFILE_BY_AXIS[axis]
    settings = {**project_section("llm"), "profile": profile}
    return llm_config_from_mapping(settings)


def llm_axis_skip_reason(axis: str) -> str | None:
    """Почему ось 2 недоступна offline — ``None``, если можно вызывать.

    ``none`` и ``cassette`` работают без сети всегда. ``gigachat`` и
    ``openrouter`` пропускаются, только если в окружении нет нужного ключа —
    задание №2: без ключей эти конфигурации не падают, а помечаются
    пропущенными с причиной.
    """
    if axis in ("none", "cassette"):
        return None
    try:
        config = llm_axis_config(axis)
    except ValueError as error:
        # Профиль в masker.yaml собрался в невалидную конфигурацию (например,
        # задан только один из двух тарифов) — данные конфигурации, а не
        # сеть/ключ, но по требованию №3 ячейка обязана честно объяснить
        # причину, а не уронить весь прогон матрицы.
        return f"конфигурация профиля llm.profiles повреждена: {error}"
    if not os.environ.get(config.api_key_env, "").strip():
        return (
            f"нет переменной окружения {config.api_key_env} — живой провайдер "
            f"{axis!r} недоступен без сети/ключа"
        )
    return None


def _rules_only_detectors() -> list[EntityDetector]:
    """Тот же набор детекторов, что ``detect_node`` строит при ``rules_only=True``.

    Намеренный дубль ветки ``if rules_only`` в ``masker/graph/nodes.py``
    (``make_detect_node``): нужен здесь, чтобы посчитать ``role_accuracy`` под
    слоем ``rules`` напрямую через ``DetectAgent``, не поднимая граф целиком
    (в отличие от ``_mask_corpus``, которому граф уже доступен через
    ``RunOptions.rules_only``, добавленный этой задачей в ``mask_and_validate``).
    Расхождение с ``graph/nodes.py`` обязано провалить
    ``test_rules_only_detectors_match_detect_node``
    (``tests/masker/test_bench_matrix.py``), а не остаться незамеченным тут.
    Без пользовательских типов — как и в оригинале, когда ``specs`` пусты.
    """
    return [
        RuleDetector(),
        AddressDetector(),
        DateDetector(),
        ContractAmountDetector(),
        DeliveryPeriodDetector(),
        PaymentTermsDetector(),
    ]


@dataclass(frozen=True, slots=True)
class CellResult:
    """Итог одной ячейки матрицы: либо метрики, либо честная причина пропуска."""

    name: str
    status: str  # "ok" | "skipped" | "failed"
    reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Ось 1 — слои детекции.
# ---------------------------------------------------------------------------


def detection_layer_cell(
    layer: str, corpus: list[tuple[pathlib.Path, dict[str, Any]]], registry: Any
) -> CellResult:
    """P/R/F1, критичный recall и leaked_total одного слоя детекции на основном корпусе.

    ``layer='gliner'`` здесь не вызывается: на ``fixtures/labeled`` нет ни
    одного ``gliner_*`` типа, слой не отличим от ``ner`` (см. докстринг
    модуля) — он меряется отдельно, на своём корпусе, ``gliner_layer_cell``.
    """
    if layer not in ("rules", "ner"):
        raise ValueError(f"detection_layer_cell не умеет layer={layer!r}, только rules/ner")
    t0 = time.perf_counter()
    metrics = eval_module._mask_corpus(corpus, rules_only=(layer == "rules"))
    elapsed = time.perf_counter() - t0
    critical, other = eval_module._aggregate(metrics.by_type, registry)
    critical_recall = (
        critical["tp"] / (critical["tp"] + critical["fn"])
        if critical["tp"] + critical["fn"]
        else 1.0
    )
    overall_tp = critical["tp"] + other["tp"]
    overall_fp = critical["fp"] + other["fp"]
    overall_fn = critical["fn"] + other["fn"]
    overall_precision = overall_tp / (overall_tp + overall_fp) if overall_tp + overall_fp else 1.0
    overall_recall = overall_tp / (overall_tp + overall_fn) if overall_tp + overall_fn else 1.0
    custom_types = {
        type_id: eval_module.score(sets["expected"], sets["found"])
        for type_id, sets in metrics.by_type.items()
        if type_id in ("product_code", "shipment_date")
    }
    return CellResult(
        name=layer,
        status="ok",
        metrics={
            "precision": overall_precision,
            "recall": overall_recall,
            "critical_recall": critical_recall,
            "critical_tp": critical["tp"],
            "critical_fn": critical["fn"],
            "leaked_total": metrics.leaked_total,
            "render_failures": len(metrics.render_failures),
            "custom_types": custom_types,
        },
        elapsed_seconds=elapsed,
    )


def _gliner_span_key(entity_type: str, order: int, start: int, end: int) -> tuple[str, ...]:
    """Ключ вхождения как строки — контракт ``eval.score`` (``set[tuple[str, ...]]``),
    позиции переведены в строку только ради типа: сравнение остаётся точным."""
    return (entity_type, str(order), str(start), str(end))


def _gliner_expected_spans(document: Any, class_d: list[dict[str, str]]) -> set[tuple[str, ...]]:
    """Позиция роли `signing_date`/`shipment_date` внутри абзаца класса D.

    Копия ``_expected_spans`` из ``tests/masker/detect/test_gliner_corpus.py``
    (докстринг там же объясняет порядок дат в абзаце) — тестовый модуль не
    экспортирует эту функцию как часть публичного API `masker`, поэтому
    дубль сознательный и мелкий (≈10 строк), а не расхождение в логике.
    """
    by_text = {segment.text: segment.order for segment in document.segments}
    expected: set[tuple[str, ...]] = set()
    for pair in class_d:
        text = pair["text"]
        date = pair["date"]
        order = by_text.get(text)
        if order is None:
            raise ValueError(f"абзац класса D не найден среди сегментов документа: {text!r}")
        signing_start = text.index(date)
        signing_end = signing_start + len(date)
        shipment_start = text.index(date, signing_end)
        shipment_end = shipment_start + len(date)
        expected.add(_gliner_span_key("signing_date", order, signing_start, signing_end))
        expected.add(_gliner_span_key("shipment_date", order, shipment_start, shipment_end))
    return expected


def gliner_layer_cell() -> CellResult:
    """F1 по ``shipment_date``/``signing_date`` на классе D (T1.13.1, шаг 17).

    Отдельный, маленький корпус (``fixtures/gliner``, один документ) — числа
    здесь **не сопоставимы** по масштабу с P/R/F1 основного корпуса
    (13+ документов): это единственное независимое измерение того, работает
    ли GLiNER-слой вообще, а не сравнение с той же выборкой.
    """
    if not gliner_available():
        return CellResult(
            name="gliner",
            status="skipped",
            reason=(
                "пакет gliner2 не установлен — `uv sync --extra gliner`; "
                "GLiNER не входит ни в Docker-образ, ни в бинарник (см. задание)"
            ),
        )
    if not GLINER_DOC.exists() or not GLINER_LABELS.exists():
        return CellResult(
            name="gliner",
            status="skipped",
            reason=f"нет корпуса {GLINER_DOC} — GLiNER-фикстуры не развёрнуты",
        )

    from masker.detect import default_detectors
    from masker.entity_types import EntityTypeRegistry
    from masker.ingest.docx_ingest import ingest_docx
    from masker.typeconfig import load_type_config

    payload = json.loads(GLINER_LABELS.read_text(encoding="utf-8"))
    document = ingest_docx(GLINER_DOC)
    specs = load_type_config({"version": 1, "types": payload["custom_types"]})
    registry = EntityTypeRegistry.builtin().extend(item.spec for item in specs)
    agent = DetectAgent(default_detectors(specs), registry)

    t0 = time.perf_counter()
    try:
        entities = agent.detect(document).entities
    except (ValueError, ImportError, FileNotFoundError) as error:
        return CellResult(
            name="gliner",
            status="failed",
            reason=f"GLiNER не смог отработать: {error}",
            elapsed_seconds=time.perf_counter() - t0,
        )
    elapsed = time.perf_counter() - t0

    found = {
        _gliner_span_key(entity.type, entity.segment_order, entity.start, entity.end)
        for entity in entities
        if entity.type in {"shipment_date", "signing_date"}
    }
    expected = _gliner_expected_spans(document, payload["class_d"])
    by_type = {}
    for type_id in ("shipment_date", "signing_date"):
        exp = {item for item in expected if item[0] == type_id}
        got = {item for item in found if item[0] == type_id}
        by_type[type_id] = eval_module.score(exp, got)
    return CellResult(
        name="gliner", status="ok", metrics={"by_type": by_type}, elapsed_seconds=elapsed
    )


# ---------------------------------------------------------------------------
# Ось 2 — провайдеры LLM (профиль/судья).
# ---------------------------------------------------------------------------


def llm_axis_cell(
    axis: str,
    corpus: list[tuple[pathlib.Path, dict[str, Any]]],
    *,
    detect_agent_factory: Any = None,
    layer_label: str = "ner",
) -> CellResult:
    """``role_accuracy``/``cluster_purity`` и ресурсы одной оси 2.

    ``layer_label`` — только для имени строки в выводе: слой детекции здесь
    задаётся через ``detect_agent_factory`` (по умолчанию — тот же голый
    ``DetectAgent()``, что и в ``make eval``, т.е. слой ``ner``).
    """
    name = f"{layer_label}+{axis}"
    reason = llm_axis_skip_reason(axis)
    if reason is not None:
        return CellResult(name=name, status="skipped", reason=reason)

    config = llm_axis_config(axis)
    try:
        base_provider = get_provider(config)
    except LLMError as error:
        return CellResult(name=name, status="failed", reason=f"провайдер не собрался: {error}")

    pricing: LLMPricing | None = config.pricing
    metering = MeteringProvider(base_provider, pricing)
    t0 = time.perf_counter()
    try:
        with metering.for_stage("bench_matrix_profile"):
            profile_metrics = eval_module._profile_judge_metrics(
                corpus,
                provider=metering,
                detect_agent_factory=detect_agent_factory,
            )
    except LLMError as error:
        return CellResult(
            name=name,
            status="failed",
            reason=str(error),
            elapsed_seconds=time.perf_counter() - t0,
        )
    except Exception as error:
        # Смысл матрицы в том, чтобы посчитать ВСЕ клетки за один прогон.
        # Любая неожиданность в одной из них — чужой контракт, сеть, кривой
        # ответ — не имеет права уносить остальные: живые прогоны стоят
        # денег и времени, а половина таблицы бесполезна. Ошибка не
        # проглатывается: она попадает в отчёт строкой с типом исключения.
        # Замерено 10.09.2026: сырая httpx.ConnectError из GigaChat унесла
        # весь прогон вместе с не начатыми клетками openrouter и ceiling.
        return CellResult(
            name=name,
            status="failed",
            reason=f"{type(error).__name__}: {error}",
            elapsed_seconds=time.perf_counter() - t0,
        )
    elapsed = time.perf_counter() - t0

    _total_calls, records = metering.delta_since(0)
    telemetry_payload: dict[str, Any] = {"llm": {"calls": records}}
    if pricing is not None:
        telemetry_payload["pricing"] = pricing.as_dict()
    usage = report_telemetry(telemetry_payload, runtime_available=False)["llm"]

    metrics: dict[str, Any] = dict(profile_metrics)
    metrics["llm_usage"] = usage
    return CellResult(name=name, status="ok", metrics=metrics, elapsed_seconds=elapsed)


# ---------------------------------------------------------------------------
# Печать.
# ---------------------------------------------------------------------------


@contextmanager
def _quiet_library_noise() -> Iterator[None]:
    """Временно убрать предупреждения известных библиотек, не скрывая наши.

    Фильтры ограничены модулями зависимостей. В частности, предупреждение
    ``masker.typeconfig`` о критичном ``product_code`` остаётся видимым:
    это не шум, а сообщение о принятом пользователем риске.
    """
    logger_levels: list[tuple[logging.Logger, int]] = []
    with warnings.catch_warnings():
        for module in ("pymorphy2", "torch", "gliner2"):
            warnings.filterwarnings("ignore", module=rf"^{module}(?:\.|$)")
            logger = logging.getLogger(module)
            logger_levels.append((logger, logger.level))
            logger.setLevel(logging.ERROR)
        try:
            yield
        finally:
            for logger, level in logger_levels:
                logger.setLevel(level)


def _print_column_guide() -> None:
    print("СТОЛБЦЫ:")
    print("  P — точность: какая доля найденного действительно размечена как сущность.")
    print("  R — полнота: какая доля размеченных сущностей найдена.")
    print("  critR — полнота только по критичным типам; должна быть 1.000, иначе возможна утечка.")
    print("  leaked — сколько исходных значений осталось в итоговых артефактах; должно быть 0.")
    print("  role_acc — точность назначения роли стороны там, где эталонную роль можно проверить.")
    print("  purity — доля профилей, не смешавших сущности разных сторон.")
    print("  calls/prompt/compl — вызовы LLM и возвращённые ею входные/выходные токены.")
    print("  сек — фактическое время клетки; это ориентир, не метрика качества.")


def _print_plan(layers: tuple[str, ...], axes: tuple[str, ...]) -> None:
    cells: list[str] = []
    cells.extend(f"слой {layer}" for layer in layers if layer in ("rules", "ner", "gliner"))
    cells.extend(f"ner+{axis}" for axis in axes)
    if "rules" in layers:
        cells.append("rules+none")

    print("=" * 88)
    print("МАТРИЧНЫЙ БЕНЧМАРК: слои детекции × провайдеры LLM")
    print(f"ПЛАН: {len(cells)} клеток: {', '.join(cells)}.")
    print("Ориентиры прошлого прогона: rules ≈40 с, ner ≈50 с, gliner ≈6 с;")
    print("каждая живая LLM-клетка — от 5 до 350 с. Самыми долгими обычно бывают живые модели.")
    if any(axis in {"gigachat", "openrouter", "ceiling"} for axis in axes):
        print(
            "ВНИМАНИЕ: живые модели требуют сети и тратят деньги; "
            "их результат — один прогон, не среднее."
        )
    else:
        print("Живые модели не выбраны: этот запуск не ходит в сеть и не тратит деньги на LLM.")
    print(
        "Строки печатаются сразу по готовности; отсутствие новой строки означает, "
        "что считается названная клетка."
    )
    print("=" * 88)
    _print_column_guide()


def _print_cell_start(description: str) -> None:
    print(f"\nсчитаю {description}…", flush=True)


def _print_detection_header() -> None:
    print("ОСЬ 1 — СЛОЙ ДЕТЕКЦИИ (fixtures/labeled, весь корпус)")
    print(f"{'слой':<10}{'P':>7}{'R':>7}{'critR':>7}{'leaked':>8}{'сек':>8}  статус/причина")


def _print_detection_result(cell: CellResult) -> None:
    if cell.status != "ok":
        print(
            f"готово: {cell.name:<10}{'—':>7}{'—':>7}{'—':>7}{'—':>8}{'—':>8}  "
            f"{cell.status}: {cell.reason}",
            flush=True,
        )
        return
    m = cell.metrics
    print(
        f"готово: {cell.name:<10}{m['precision']:>7.3f}{m['recall']:>7.3f}"
        f"{m['critical_recall']:>7.3f}{m['leaked_total']:>8}{cell.elapsed_seconds:>8.2f}  ok",
        flush=True,
    )
    for type_id, score in m["custom_types"].items():
        print(
            f"    пользовательский тип {type_id:<16}"
            f"P={score['precision']:.3f} R={score['recall']:.3f} "
            f"(измерено на contract_09_custom.docx — один документ, не корпус)",
            flush=True,
        )


def _print_gliner_row(cell: CellResult) -> None:
    if cell.status != "ok":
        print(f"готово: {cell.status}: {cell.reason}", flush=True)
        return
    print(
        f"{'тип':<15}{'P':>7}{'R':>7}{'F1':>7}{'FN':>5}{'FP':>5}  "
        f"(порог приёмки F1>={GLINER_ACCEPTANCE_F1})"
    )
    for type_id, m in cell.metrics["by_type"].items():
        flag = "OK" if m["f1"] >= GLINER_ACCEPTANCE_F1 else "НИЖЕ ПОРОГА"
        print(
            f"{type_id:<15}{m['precision']:>7.3f}{m['recall']:>7.3f}{m['f1']:>7.3f}"
            f"{m['fn']:>5}{m['fp']:>5}  {flag}",
            flush=True,
        )
    print(f"готово: время{cell.elapsed_seconds:>10.2f} с (N=1, один документ)", flush=True)


def _print_llm_header() -> None:
    print("\nОСЬ 2 — ПРОВАЙДЕР LLM (роли/профиль/судья, слой детекции — ner, если не указано иное)")
    print(
        f"{'конфигурация':<16}{'role_acc':>9}{'purity':>8}{'calls':>7}"
        f"{'prompt':>8}{'compl':>7}{'сек':>8}  статус/сообщение"
    )


def _print_llm_result(cell: CellResult) -> None:
    if cell.status != "ok":
        print(
            f"готово: {cell.name:<16}{'—':>9}{'—':>8}{'—':>7}{'—':>8}{'—':>7}{'—':>8}  "
            f"{cell.status}: {cell.reason}",
            flush=True,
        )
        return
    m = cell.metrics
    usage = m["llm_usage"]
    print(
        f"готово: {cell.name:<16}{m['role_accuracy']:>9.3f}{m['cluster_purity']:>8.3f}"
        f"{usage['calls']:>7}{usage['prompt_tokens']:>8}{usage['completion_tokens']:>7}"
        f"{cell.elapsed_seconds:>8.2f}  {usage['message']}",
        flush=True,
    )
    if cell.name.split("+", 1)[1] in ("gigachat", "openrouter", "ceiling"):
        print("    НЕДЕТЕРМИНИРОВАНО: один прогон живой модели, не среднее.", flush=True)


# ---------------------------------------------------------------------------
# run()/main()
# ---------------------------------------------------------------------------


def _print_human_summary(
    detection_cells: list[CellResult], gliner_cell: CellResult | None, llm_cells: list[CellResult]
) -> None:
    """Напечатать осторожный вывод поверх чисел, не делая из одного замера рейтинг."""
    print("\nВЫВОД:")
    print("  Измерены две независимые вещи: поиск сущностей по корпусу и роли/профили у LLM.")
    print(
        "  Они не складываются в один рейтинг: хорошая роль не доказывает отсутствие утечек, "
        "а высокий R не доказывает качество ролей."
    )

    successful_detection = [cell for cell in detection_cells if cell.status == "ok"]
    leaked = sum(int(cell.metrics["leaked_total"]) for cell in successful_detection)
    if successful_detection:
        if leaked:
            print(
                f"  В измеренных слоях осталось утечек: {leaked}; "
                "результат нельзя считать безопасным."
            )
        else:
            print(
                "  В измеренных слоях leaked=0: на этом корпусе валидатор "
                "не нашёл остаточных исходных значений."
            )
    if gliner_cell is not None:
        if gliner_cell.status == "ok":
            print(
                "  GLiNER измерен отдельно на одном документе с датами; "
                "это проверка слоя, а не сравнение с основным корпусом."
            )
        else:
            print(f"  GLiNER не измерен: {gliner_cell.reason}")

    ner_cells = [cell for cell in llm_cells if cell.status == "ok" and cell.name.startswith("ner+")]
    live_axes = {"gigachat", "openrouter", "ceiling"}
    live_cells = [cell for cell in ner_cells if cell.name.split("+", 1)[1] in live_axes]
    if len(ner_cells) >= 2:
        scores = [float(cell.metrics["role_accuracy"]) for cell in ner_cells]
        spread = max(scores) - min(scores)
        print(
            f"  Разброс role_acc между доступными конфигурациями: {spread:.3f} "
            f"({spread * 100:.1f} процентного пункта)."
        )
        if spread < 0.01:
            print("  Это меньше одного процентного пункта и укладывается в шум одного прогона.")
        if live_cells:
            print(
                "  На 110 профилях живую конфигурацию с большим role_acc нельзя называть "
                "победителем: это один прогон, не среднее и не тест значимости."
            )
        else:
            print("  Живые модели не запускались: эти строки не говорят о том, какая из них лучше.")
    elif ner_cells:
        print(
            "  Для сравнения role_acc нужна минимум ещё одна доступная конфигурация; "
            "одна строка ничего не доказывает."
        )
    print(
        "  Бенчмарк не показывает устойчивость живой модели между запусками "
        "и не заменяет приёмочные ворота."
    )


def run(
    *, layers: tuple[str, ...] = DETECTION_LAYERS, axes: tuple[str, ...] = LLM_AXES
) -> dict[str, Any]:
    """Собрать и напечатать всю матрицу. Возвращает данные для ``--json``."""
    _print_plan(layers, axes)
    with _quiet_library_noise():
        corpus = [
            (path, labels)
            for path, labels in eval_module.load_corpus()
            if not path.stem.startswith("scan_synth_")
        ]
        registry = eval_module.corpus_registry(corpus)

        detection_cells: list[CellResult] = []
        if any(layer in ("rules", "ner") for layer in layers):
            _print_detection_header()
        for layer in layers:
            if layer not in ("rules", "ner"):
                continue
            _print_cell_start(f"слой детекции {layer}")
            cell = detection_layer_cell(layer, corpus, registry)
            detection_cells.append(cell)
            _print_detection_result(cell)

        gliner_cell: CellResult | None = None
        if "gliner" in layers:
            print("\nОСЬ 1 — СЛОЙ gliner (свой корпус: fixtures/gliner, класс D)")
            _print_cell_start("слой детекции gliner")
            # GLiNER2 пишет баннер конфигурации прямо в stdout при загрузке
            # весов, минуя warnings и logging. Это не сообщение masker и не
            # результат клетки, поэтому не даём ему разорвать таблицу.
            with redirect_stdout(io.StringIO()):
                gliner_cell = gliner_layer_cell()
            _print_gliner_row(gliner_cell)

        llm_cells: list[CellResult] = []
        if axes or "rules" in layers:
            _print_llm_header()
        for axis in axes:
            _print_cell_start(f"профиль/судья ner+{axis}")
            cell = llm_axis_cell(axis, corpus)
            llm_cells.append(cell)
            _print_llm_result(cell)
        if "rules" in layers:
            # Бесплатная (offline, `none`) точка на пересечении осей: показывает,
            # насколько профиль/судья деградируют, когда детекция — только
            # правила. Остальные сочетания rules×{cassette,gigachat,openrouter}
            # и gliner×любая LLM-ось пропущены сознательно (см. run.__doc__).
            _print_cell_start("профиль/судья rules+none")
            cell = llm_axis_cell(
                "none",
                corpus,
                detect_agent_factory=lambda: DetectAgent(_rules_only_detectors()),
                layer_label="rules",
            )
            llm_cells.append(cell)
            _print_llm_result(cell)

    print("\nПРОПУЩЕННЫЕ СОЧЕТАНИЯ ОСЕЙ (не измерены намеренно, не по ошибке):")
    print(
        "  rules × {cassette,gigachat,openrouter}: профиль/судья не зависят от слоя детекции\n"
        "    в коде графа (ProfileAgent/JudgeAgent видят найденные сущности, а не то, каким\n"
        "    детектором они найдены) — интересна только точка rules×none (посчитана выше),\n"
        "    остальные три повторяли бы ту же LLM-ось ещё раз на урезанном входе, вопрос\n"
        "    «что даёт LLM» она не проясняет, а сетевые вызовы стоят денег."
    )
    print(
        "  gliner × {cassette,gigachat,openrouter}: у fixtures/gliner нет ролей/сторон\n"
        "    (разметка class_d — только пары дат), role_accuracy/cluster_purity там не считаются\n"
        "    ни при каком провайдере — это не ограничение бенчмарка, а факт разметки корпуса."
    )
    print(
        "  gliner на fixtures/labeled: ни один документ основного корпуса не использует\n"
        "    gliner_* пользовательский тип, поэтому слой gliner там буквально совпадает с ner —\n"
        "    отдельная строка добавила бы дублирующее число, а не новую информацию."
    )

    _print_human_summary(detection_cells, gliner_cell, llm_cells)

    return {
        "detection": {cell.name: _cell_to_dict(cell) for cell in detection_cells},
        "gliner": _cell_to_dict(gliner_cell) if gliner_cell is not None else None,
        "llm": {cell.name: _cell_to_dict(cell) for cell in llm_cells},
    }


def _cell_to_dict(cell: CellResult) -> dict[str, Any]:
    return {
        "status": cell.status,
        "reason": cell.reason,
        "metrics": cell.metrics,
        "elapsed_seconds": cell.elapsed_seconds,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="masker.bench_matrix",
        description=(
            "К4 — матричный бенчмарк слоёв детекции и провайдеров LLM. "
            "ТРАТИТ ДЕНЬГИ И ХОДИТ В СЕТЬ, если заданы GIGACHAT_CREDENTIALS/"
            "OPENROUTER_API_KEY — без них живые клетки пропускаются. "
            "Не входит в `make gate` и не запускается по умолчанию."
        ),
    )
    parser.add_argument(
        "--json", type=pathlib.Path, default=None, help="куда записать сырые метрики матрицы (JSON)"
    )
    parser.add_argument(
        "--layers",
        default=",".join(DETECTION_LAYERS),
        help=f"слои детекции через запятую ({','.join(DETECTION_LAYERS)})",
    )
    parser.add_argument(
        "--llm-axes",
        default=",".join(LLM_AXES),
        help=f"провайдеры LLM через запятую ({','.join(LLM_AXES)})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    layers = tuple(item.strip() for item in args.layers.split(",") if item.strip())
    axes = tuple(item.strip() for item in args.llm_axes.split(",") if item.strip())
    result = run(layers=layers, axes=axes)
    if args.json is not None:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON записан: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
