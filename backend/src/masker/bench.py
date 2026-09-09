"""К3 — замеры практического эффекта (`make bench`).

Печатает таблицу с явной границей между ЗАМЕРЕННЫМ и ПРОГНОЗНЫМ
(критерий финала «Практический эффект», `docs/SCORING.md`, §2):

- **ЗАМЕРЕНО** — числа, полученные прогоном графового конвейера на
  `fixtures/labeled`/`fixtures/holdout`: время по стадиям графа, recall по
  критичным типам, ``leaked_total``, время и пиковая память на документах
  разного размера, число страниц PDF против числа заполненных полей
  карточки договора.
- **ПРОГНОЗ** — экономия часов при потоке N договоров в месяц, считается
  явно из замеренного среднего времени обработки и внешней (не нашей)
  оценки времени ручной вычитки. Без внешней оценки прогноз не строится —
  подставлять правдоподобное число запрещено (AGENTS.md).

Время по своей природе шумит, поэтому каждая величина — медиана из N
прогонов, N печатается рядом. Никакого ``random`` без сида нигде не
используется — единственный источник вариативности здесь легитимен
(реальное время выполнения), а не генерация данных.

Пиковая память измеряется в отдельном подпроцессе на каждый прогон
(``resource.getrusage(RUSAGE_SELF).ru_maxrss``, КиБ на Linux): значение
внутри одного процесса — это максимум с начала процесса, а не дельта
одного прогона, поэтому переиспользовать текущий процесс для нескольких
документов подряд нельзя — большой документ исказил бы память следующих.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from masker.entity_types import EntityTypeRegistry
from masker.eval import FIXTURES, FIXTURES_HOLDOUT, corpus_registry, load_corpus, score
from masker.graph.build import compile_graph
from masker.graph.nodes import RunDeps
from masker.graph.serde import plan_from_dict
from masker.graph.state import State
from masker.run import RunOptions, RunOutcome, report_of, start_run, thread_id_for

#: Маркер строки в stdout дочернего процесса — отделяет результат замера от
#: возможного постороннего вывода библиотек (предупреждения и т.п.).
_CHILD_RESULT_PREFIX = "BENCH_RESULT "

#: Документ для разбивки по стадиям графа — из основного корпуса, не самый
#: маленький (в нём часть стадий работает по пустому множеству кандидатов)
#: и не 46-страничный PDF (там шум запуска Natasha/pymupdf тонет в секундах
#: реальной обработки, разбивка по стадиям становится нечитаемой).
STAGE_DOC = FIXTURES / "contract_01.docx"
STAGE_REPEATS = 5


#: Документы разного размера для времени/памяти. DOCX не хранит «число
#: страниц» без рендера в PDF — размер задаём через то, что действительно
#: можно посчитать не выдумывая: абзацы и строки таблиц для DOCX, страницы
#: для PDF. Все четыре уже входят в `fixtures/labeled` — они же используются
#: и для recall/leaked_total, повторный прогон не нужен.
@dataclass(frozen=True, slots=True)
class SizeDoc:
    label: str
    path: Path
    repeats: int


SIZE_DOCS: tuple[SizeDoc, ...] = (
    SizeDoc("DOCX маленький (2 абзаца + 5 строк таблицы)", FIXTURES / "contract_05_tables.docx", 3),
    SizeDoc("DOCX средний (17 абзацев + 3 строки таблицы)", FIXTURES / "contract_01.docx", 3),
    SizeDoc("PDF маленький (1 стр.)", FIXTURES / "contract_pdf_01.pdf", 3),
    # 46 страниц — единственный такой документ в корпусе; полный прогон
    # занимает десятки секунд, повторять трижды ради медианы непропорционально
    # дорого. Один замер, помечен как N=1 без усреднения — не выдумываем
    # медиану там, где её не считали.
    SizeDoc("PDF крупный (46 стр.)", FIXTURES / "contract_pdf_02_school.pdf", 1),
)

#: PDF из корпуса — единственные документы, где «число страниц» измерено
#: инструментом (`pymupdf`), а не оценено на глаз. DOCX сюда не попадает.
CARD_DOCS: tuple[Path, ...] = (
    FIXTURES / "contract_pdf_01.pdf",
    FIXTURES / "contract_pdf_02_school.pdf",
)

#: Форматы, которые граф умеет прогонять целиком (`extract_node`, CLI —
#: `masker.cli._SUPPORTED_SUFFIXES`). XLSX добавлен 09.09.2026: проводка
#: через граф сделана вместе с М7, и оговорка «не входит: подключение xlsx
#: к воротам» из того коммита больше не действует. Документы формата, который
#: граф не умеет, не выдумываем гонять — честно исключаем и печатаем, что и
#: почему пропущено.
_GRAPH_SUPPORTED_SUFFIXES = frozenset({".docx", ".pdf", ".xlsx"})

#: Скан-документы OCR-корпуса (`scan_synth_*`) в замер не входят: у них нет
#: текстового слоя, и без OCR-провайдера граф честно не находит в них ничего.
#: `masker.eval.run` исключает их из основного корпуса по той же причине —
#: числа bench и ворот обязаны считаться по одному и тому же множеству
#: документов, иначе одно из них выглядит провалом на ровном месте (замерено
#: 09.09.2026: bench давал recall 0.854 при 1.000 в воротах, вся разница —
#: шесть критичных сущностей одного скана). Качество OCR меряется отдельно,
#: своей метрикой `scan_critical_recall`.
_SCAN_PREFIX = "scan_synth_"


def _filter_graph_supported(
    corpus: list[tuple[Path, dict[str, Any]]],
) -> tuple[list[tuple[Path, dict[str, Any]]], list[Path]]:
    def _runnable(path: Path) -> bool:
        return path.suffix.casefold() in _GRAPH_SUPPORTED_SUFFIXES and not path.stem.startswith(
            _SCAN_PREFIX
        )

    supported = [item for item in corpus if _runnable(item[0])]
    skipped = [path for path, _labels in corpus if not _runnable(path)]
    return supported, skipped


def _collapse(text: str) -> str:
    """Схлопнуть пробелы для сравнения — та же нормализация, что в eval.py."""
    return " ".join(text.split())


def _full_options(*, custom_types: tuple[dict[str, Any], ...] = ()) -> RunOptions:
    """Опции прогона «как в проде»: оба редактирующих рендера, без паузы на
    человеке — bench меряет автоматическую обработку, а не диалог."""
    return RunOptions(
        interactive=False,
        preview=False,
        styles=("marker", "blackbox"),
        custom_types=custom_types,
    )


def _state_for(path: str | Path, options: RunOptions, thread_id: str) -> State:
    """Начальное состояние графа — то же построение, что и `run._initial_state`
    (без обработки заранее известных ответов: bench всегда неинтерактивен)."""
    state: State = {
        "path": str(path),
        "options": {
            **options.canonical(),
            "thread_id": thread_id,
            "interactive": options.interactive,
            "styles": list(options.styles),
            "preview": options.preview,
        },
    }
    return state


def run_once(
    path: str | Path, *, custom_types: tuple[dict[str, Any], ...] = ()
) -> tuple[float, RunOutcome]:
    """Один полный прогон графа (extract → report). Возвращает время в
    секундах вокруг вызова конвейера (без учёта импорта модулей) и исход."""
    options = _full_options(custom_types=custom_types)
    with tempfile.TemporaryDirectory(prefix="masker-bench-") as scratch:
        deps = RunDeps(artifact_dir=Path(scratch))
        t0 = time.perf_counter()
        outcome = start_run(path, options, checkpointer_factory=lambda: InMemorySaver(), deps=deps)
        elapsed = time.perf_counter() - t0
    if outcome.status != "done":
        # interactive=False обязан пропустить паузу (см. needs_human) — если
        # это не так, это дефект графа, а не документа, и должен быть виден.
        raise RuntimeError(
            f"неинтерактивный прогон {path} неожиданно приостановился "
            f"(thread_id={outcome.thread_id!r})"
        )
    return elapsed, outcome


def stage_timings(path: str | Path, repeats: int) -> dict[str, list[float]]:
    """Время каждой стадии графа по нескольким прогонам одного документа.

    Использует `graph.stream(..., stream_mode="updates")`: LangGraph отдаёт
    состояние сразу после выполнения каждого узла, поэтому разница между
    двумя последовательными yield — честное время именно этого узла, без
    необходимости трогать сами узлы графа (`graph/nodes.py` не меняется).
    """
    per_stage: dict[str, list[float]] = defaultdict(list)
    options = _full_options()
    for _ in range(repeats):
        with tempfile.TemporaryDirectory(prefix="masker-bench-") as scratch:
            deps = RunDeps(artifact_dir=Path(scratch))
            graph = compile_graph(deps, InMemorySaver())
            tid = thread_id_for(path, options)
            config: RunnableConfig = {"configurable": {"thread_id": tid}}
            state = _state_for(path, options, tid)
            t_prev = time.perf_counter()
            for update in graph.stream(state, config, stream_mode="updates"):
                now = time.perf_counter()
                for node_name in update:
                    per_stage[node_name].append(now - t_prev)
                t_prev = now
    return dict(per_stage)


@dataclass
class CorpusMetrics:
    """Recall по критичным типам и `leaked_total` по одному корпусу."""

    critical_expected: set[tuple[str, ...]] = field(default_factory=set)
    critical_found: set[tuple[str, ...]] = field(default_factory=set)
    leaked_total: int = 0
    docs: int = 0
    elapsed_by_doc: dict[str, float] = field(default_factory=dict)


def measure_corpus(
    corpus: list[tuple[Path, dict[str, Any]]], registry: EntityTypeRegistry
) -> CorpusMetrics:
    """Прогнать каждый документ корпуса через граф и собрать критичный
    recall и `leaked_total` — то же определение, что и в `make eval`
    (`masker.eval._mask_corpus`), но здесь считается независимо от него,
    напрямую через граф, чтобы получить и честное время прогона заодно."""
    metrics = CorpusMetrics()
    for path, labels in corpus:
        for item in labels["entities"]:
            if not registry.is_critical(item["type"]):
                continue
            metrics.critical_expected.add((path.name, item["type"], _collapse(item["text"])))

        custom_types = tuple(labels.get("custom_types", []))
        elapsed, outcome = run_once(path, custom_types=custom_types)
        metrics.elapsed_by_doc[path.name] = elapsed

        plan = plan_from_dict(outcome.state.get("plan", {}))
        for repl in plan.replacements:
            if not registry.is_critical(repl.entity.type):
                continue
            metrics.critical_found.add((path.name, repl.entity.type, _collapse(repl.entity.text)))

        report = report_of(outcome)
        metrics.leaked_total += len(report.get("leaked", []))
        metrics.docs += 1
    return metrics


def _count_summary_fields(summary: dict[str, Any]) -> int:
    """Сколько листовых значений реально заполнено в карточке договора.

    Скалярные поля считаются, если непустые; списки (``federal_law``,
    ``delivery_periods``) — по числу элементов, каждый элемент — отдельный
    факт, который не нужно искать по документу вручную. ``generated_at`` и
    ``llm_calls`` — служебные поля отчёта, не часть карточки для человека.
    """
    count = 0
    for party_key in ("customer", "supplier"):
        party = summary.get(party_key) or {}
        for field_name in ("name", "role_title", "inn", "ogrn"):
            if party.get(field_name):
                count += 1
    for field_name in ("contract_amount", "payment_terms", "contract_number"):
        if summary.get(field_name):
            count += 1
    for field_name in ("federal_law", "delivery_periods"):
        count += len(summary.get(field_name) or [])
    return count


def card_metrics(path: Path) -> tuple[int, int]:
    """(число страниц PDF, число заполненных полей карточки договора)."""
    # PyMuPDF не поставляет стабы (см. [[tool.mypy.overrides]] для ingest/render) —
    # тот же артефакт библиотеки, здесь достаточно точечного игнора одной строки.
    pages = pymupdf.open(str(path)).page_count  # type: ignore[no-untyped-call]
    _elapsed, outcome = run_once(path)
    summary = dict(outcome.state.get("contract_summary", {}))
    return pages, _count_summary_fields(summary)


# ---------------------------------------------------------------------------
# Время + пиковая память в отдельном подпроцессе (см. докстринг модуля).
# ---------------------------------------------------------------------------


def _run_child_measure(path: Path) -> None:
    """Тело дочернего процесса: один прогон, печать времени и пиковой RSS."""
    import resource

    elapsed, outcome = run_once(path)
    assert outcome.status == "done"
    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    payload = {"seconds": elapsed, "peak_rss_kb": peak_kb}
    print(_CHILD_RESULT_PREFIX + json.dumps(payload))


def _measure_once_subprocess(path: Path) -> dict[str, float]:
    """Замерить время и пиковую RSS одного прогона в свежем интерпретаторе."""
    result = subprocess.run(
        [sys.executable, "-m", "masker.bench", "--child-measure", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith(_CHILD_RESULT_PREFIX):
            return dict(json.loads(line[len(_CHILD_RESULT_PREFIX) :]))
    raise RuntimeError(
        f"дочерний процесс замера {path} не вернул результат; stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )


@dataclass(frozen=True, slots=True)
class SizeMeasurement:
    label: str
    path: Path
    repeats: int
    seconds: list[float]
    peak_rss_kb: list[float]

    @property
    def seconds_median(self) -> float:
        return statistics.median(self.seconds)

    @property
    def peak_rss_mb_median(self) -> float:
        return statistics.median(self.peak_rss_kb) / 1024


def measure_size_docs(docs: Sequence[SizeDoc] = SIZE_DOCS) -> list[SizeMeasurement]:
    results: list[SizeMeasurement] = []
    for doc in docs:
        seconds: list[float] = []
        peak_rss: list[float] = []
        for _ in range(doc.repeats):
            payload = _measure_once_subprocess(doc.path)
            seconds.append(float(payload["seconds"]))
            peak_rss.append(float(payload["peak_rss_kb"]))
        results.append(SizeMeasurement(doc.label, doc.path, doc.repeats, seconds, peak_rss))
    return results


# ---------------------------------------------------------------------------
# Прогноз (явно отделён от замеров) — экономия часов при потоке N договоров.
# ---------------------------------------------------------------------------


def forecast_hours_saved(
    *, contracts_per_month: int, automated_seconds: float, manual_minutes: float | None
) -> float | None:
    """Прогноз экономии часов в месяц — считается только если задана внешняя
    оценка времени ручной вычитки (``manual_minutes``). Без неё возвращает
    ``None``: подставлять правдоподобное число вместо отсутствующего замера
    запрещено (AGENTS.md, «ничего не выдумывать»)."""
    if manual_minutes is None:
        return None
    manual_seconds = manual_minutes * 60
    saved_seconds_per_doc = manual_seconds - automated_seconds
    return contracts_per_month * saved_seconds_per_doc / 3600


# ---------------------------------------------------------------------------
# Печать
# ---------------------------------------------------------------------------


def _print_stage_timings(per_stage: dict[str, list[float]], repeats: int, doc: Path) -> None:
    print(f"\nВремя по стадиям графа — {doc.name}, медиана {repeats} прогонов")
    print(f"{'стадия':<16}{'медиана, с':>12}")
    order = [
        "extract",
        "detect",
        "profile",
        "judge",
        "policy",
        "apply_answers",
        "finalize",
        "plan",
        "summary",
        "render",
        "validate",
        "report",
    ]
    total = 0.0
    for stage in order:
        values = per_stage.get(stage)
        if not values:
            continue
        med = statistics.median(values)
        total += med
        print(f"{stage:<16}{med:>12.3f}")
    print(f"{'ИТОГО':<16}{total:>12.3f}")


def _print_critical_recall(name: str, metrics: CorpusMetrics) -> list[str]:
    m = score(metrics.critical_expected, metrics.critical_found)
    print(
        f"критичные типы, {name:<28}recall={m['recall']:.3f}  "
        f"({m['tp']}/{m['tp'] + m['fn']})  FN={m['fn']}  документов={metrics.docs}"
    )
    failures = []
    if m["fn"]:
        failures.append(f"{name}: пропущены критичные сущности — FN={m['fn']}")
    return failures


def _print_size_table(measurements: list[SizeMeasurement]) -> None:
    print("\nВремя и пиковая память по документам разного размера")
    print(f"{'документ':<48}{'время, с':>12}{'RSS, МиБ':>12}{'N':>4}")
    for m in measurements:
        print(f"{m.label:<48}{m.seconds_median:>12.2f}{m.peak_rss_mb_median:>12.1f}{m.repeats:>4}")


def _print_card_table(rows: list[tuple[str, int, int]]) -> None:
    print("\nЧисло страниц PDF против числа заполненных полей карточки договора")
    print(f"{'документ':<32}{'страниц':>10}{'полей карточки':>16}")
    for name, pages, fields in rows:
        print(f"{name:<32}{pages:>10}{fields:>16}")


def run(args: argparse.Namespace) -> int:
    print("=" * 78)
    print("ЗАМЕРЕНО (граф прогнан, числа получены запуском, не оценкой)")
    print("=" * 78)

    _print_stage_timings(stage_timings(STAGE_DOC, STAGE_REPEATS), STAGE_REPEATS, STAGE_DOC)

    labeled_corpus, labeled_skipped = _filter_graph_supported(load_corpus(FIXTURES))
    holdout_corpus, holdout_skipped = _filter_graph_supported(load_corpus(FIXTURES_HOLDOUT))
    registry = corpus_registry(labeled_corpus + holdout_corpus)

    for skipped in (*labeled_skipped, *holdout_skipped):
        if skipped.stem.startswith(_SCAN_PREFIX):
            reason = (
                "скан без текстового слоя, замер идёт без OCR-провайдера; "
                "качество OCR меряется своей метрикой scan_critical_recall"
            )
        else:
            reason = (
                f"граф не прогоняет {skipped.suffix} целиком "
                f"(extract_node знает {', '.join(sorted(_GRAPH_SUPPORTED_SUFFIXES))})"
            )
        print(f"{skipped.name}: пропущен в замерах — {reason}")

    print()
    labeled_metrics = measure_corpus(labeled_corpus, registry)
    holdout_metrics = measure_corpus(holdout_corpus, registry)
    failures = []
    failures += _print_critical_recall("основной корпус", labeled_metrics)
    failures += _print_critical_recall("holdout", holdout_metrics)
    leaked_total = labeled_metrics.leaked_total + holdout_metrics.leaked_total
    print(f"leaked_total (основной корпус + holdout){leaked_total:>10}")
    if leaked_total:
        failures.append(f"leaked_total {leaked_total} > 0 — утечка в артефактах")

    print(
        "время ручной вычитки того же документа: нет данных — это внешний "
        "замер (нужен человек с секундомером), у нас его нет; не подставляем "
        "правдоподобное число вместо него."
    )

    size_measurements = measure_size_docs()
    _print_size_table(size_measurements)

    card_rows = [(path.name, *card_metrics(path)) for path in CARD_DOCS]
    _print_card_table(card_rows)

    print()
    print("=" * 78)
    print("ПРОГНОЗ (считается из замеренного выше, не замер)")
    print("=" * 78)
    typical_seconds = statistics.median(
        seconds for doc, seconds in labeled_metrics.elapsed_by_doc.items() if doc.endswith(".docx")
    )
    print(
        f"типичное время обработки договора (медиана DOCX основного корпуса): "
        f"{typical_seconds:.2f} с"
    )
    saved_hours = forecast_hours_saved(
        contracts_per_month=args.contracts_per_month,
        automated_seconds=typical_seconds,
        manual_minutes=args.manual_minutes,
    )
    if saved_hours is None:
        print(
            "экономия часов в месяц: не считается — не задан --manual-minutes "
            "(внешняя оценка времени ручной вычитки одного договора; без неё "
            "прогноз был бы выдумкой, а не расчётом)."
        )
    else:
        print(
            f"экономия часов в месяц при потоке {args.contracts_per_month} договоров "
            f"(внешняя оценка ручной вычитки: {args.manual_minutes:.1f} мин/договор): "
            f"{saved_hours:.1f} ч — ПРОГНОЗ, не замер."
        )

    if failures:
        print("\nПРОВАЛ:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="masker.bench",
        description="Замеры практического эффекта (К3): таблица ЗАМЕРЕНО/ПРОГНОЗ.",
    )
    parser.add_argument(
        "--manual-minutes",
        type=float,
        default=None,
        help=(
            "внешняя оценка минут на ручную вычитку одного договора (не наш "
            "замер); без неё прогноз экономии часов не считается"
        ),
    )
    parser.add_argument(
        "--contracts-per-month",
        type=int,
        default=100,
        help="гипотетический поток договоров в месяц — только для прогноза, не измерение",
    )
    parser.add_argument(
        "--child-measure",
        type=Path,
        default=None,
        help=argparse.SUPPRESS,  # внутренний режим подпроцесса, не часть публичного CLI
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.child_measure is not None:
        _run_child_measure(args.child_measure)
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
