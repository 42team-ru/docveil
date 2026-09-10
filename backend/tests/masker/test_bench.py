"""Тесты `masker.bench` — замеры практического эффекта (К3).

Дорогие функции (полный прогон графа на весь корпус, подпроцесс на каждый
замер памяти) проверяются на маленьких реальных документах напрямую —
секунды, не минуты. Оркестрация `run()` (что печатается, когда прогноз не
считается, когда считается, как формируется код возврата) проверяется с
подменёнными дорогими шагами — тот же приём, что и в `test_eval.py`
(`mask_and_validate` там подменена по той же причине).
"""

from __future__ import annotations

import argparse
import json

import pytest

from masker.bench import (
    CorpusMetrics,
    SizeDoc,
    _count_summary_fields,
    _run_child_measure,
    card_metrics,
    forecast_hours_saved,
    measure_corpus,
    measure_size_docs,
    run,
    run_once,
    stage_timings,
)
from masker.eval import FIXTURES, corpus_registry, load_corpus

_SMALL_DOCX = FIXTURES / "contract_05_tables.docx"
_CUSTOM_DOCX = FIXTURES / "contract_09_custom.docx"
_SMALL_PDF = FIXTURES / "contract_pdf_01.pdf"

_STAGE_ORDER = (
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
)


# ---------------------------------------------------------------------------
# _count_summary_fields — чистая функция, каждая ветка отдельно.
# ---------------------------------------------------------------------------


def test_count_summary_fields_empty_summary_is_zero() -> None:
    empty: dict[str, object] = {
        "customer": None,
        "supplier": None,
        "federal_law": [],
        "contract_amount": None,
        "delivery_periods": [],
        "payment_terms": None,
        "contract_number": None,
    }
    assert _count_summary_fields(empty) == 0


def test_count_summary_fields_counts_party_leaf_fields() -> None:
    summary = {
        "customer": {"name": "АО «Триема»", "role_title": "Покупатель", "inn": None, "ogrn": None},
        "supplier": {"name": "ООО «Ромашка»", "role_title": None, "inn": "123", "ogrn": "456"},
    }
    # customer: name + role_title = 2; supplier: name + inn + ogrn = 3.
    assert _count_summary_fields(summary) == 5


def test_count_summary_fields_counts_list_items_individually() -> None:
    summary = {
        "federal_law": ["44-ФЗ", "223-ФЗ"],
        "delivery_periods": ["10 дней"],
        "contract_amount": "100 000 руб.",
        "payment_terms": None,
        "contract_number": "Д-1",
    }
    # 2 (federal_law) + 1 (delivery_periods) + contract_amount + contract_number = 5.
    assert _count_summary_fields(summary) == 5


def test_count_summary_fields_ignores_service_fields() -> None:
    summary = {"generated_at": "2026-01-01T00:00:00", "llm_calls": 7}
    assert _count_summary_fields(summary) == 0


# ---------------------------------------------------------------------------
# forecast_hours_saved — граница «нет внешней оценки» / «оценка задана».
# ---------------------------------------------------------------------------


def test_forecast_hours_saved_is_none_without_manual_minutes() -> None:
    """Без внешней оценки ручной вычитки прогноз не считается — не выдумываем."""
    result = forecast_hours_saved(
        contracts_per_month=100, automated_seconds=5.0, manual_minutes=None
    )
    assert result is None


def test_forecast_hours_saved_computes_explicitly_from_inputs() -> None:
    # 100 договоров, вручную 10 минут = 600с, автоматически 5с экономии 595с/договор.
    result = forecast_hours_saved(
        contracts_per_month=100, automated_seconds=5.0, manual_minutes=10.0
    )
    assert result is not None
    assert result == pytest.approx(100 * 595 / 3600)


def test_forecast_hours_saved_reports_negative_when_automated_slower() -> None:
    """Не подгоняем знак — если автоматика медленнее «ручной» оценки, число отрицательное."""
    result = forecast_hours_saved(
        contracts_per_month=10, automated_seconds=120.0, manual_minutes=1.0
    )
    assert result is not None
    assert result < 0


# ---------------------------------------------------------------------------
# stage_timings — реальный граф на маленьком документе.
# ---------------------------------------------------------------------------


def test_stage_timings_covers_every_graph_stage_with_positive_time() -> None:
    per_stage = stage_timings(_SMALL_DOCX, repeats=1)
    for stage in _STAGE_ORDER:
        # ask_human не должен запускаться (interactive=False) — остальные обязаны.
        assert stage in per_stage, f"стадия {stage!r} не отработала"
        assert all(value >= 0 for value in per_stage[stage])
    assert "ask_human" not in per_stage


def test_stage_timings_repeats_controls_sample_size() -> None:
    per_stage = stage_timings(_SMALL_DOCX, repeats=3)
    assert len(per_stage["extract"]) == 3


# ---------------------------------------------------------------------------
# run_once — обёртка над графом, время меряется вокруг вызова.
# ---------------------------------------------------------------------------


def test_run_once_finishes_and_reports_positive_elapsed_time() -> None:
    elapsed, outcome = run_once(_SMALL_DOCX)
    assert outcome.status == "done"
    assert elapsed > 0
    assert "plan" in outcome.state
    assert "contract_summary" in outcome.state


# ---------------------------------------------------------------------------
# measure_corpus — recall по критичным типам и leaked_total, включая
# пользовательские критичные типы (не только встроенный CRITICAL_TYPES).
# ---------------------------------------------------------------------------


def test_measure_corpus_finds_all_critical_entities_on_clean_fixture() -> None:
    corpus = [(path, labels) for path, labels in load_corpus(FIXTURES) if path == _SMALL_DOCX]
    assert corpus, "фикстура contract_05_tables.docx должна быть в корпусе"
    registry = corpus_registry(corpus)

    metrics = measure_corpus(corpus, registry)

    assert metrics.docs == 1
    assert metrics.critical_expected
    assert metrics.critical_found == metrics.critical_expected
    assert metrics.leaked_total == 0
    assert _SMALL_DOCX.name in metrics.elapsed_by_doc
    assert metrics.elapsed_by_doc[_SMALL_DOCX.name] > 0


def test_measure_corpus_counts_custom_critical_type_via_registry() -> None:
    """`contract_09_custom.docx` объявляет `product_code` критичным через
    custom_types — обычный `masker.model.is_critical` этого типа не знает
    вовсе (это не встроенный `EntityType`), поэтому без реестра сущность
    молча выпала бы из recall критичных типов, а провал остался бы незамечен."""
    corpus = [(path, labels) for path, labels in load_corpus(FIXTURES) if path == _CUSTOM_DOCX]
    assert corpus
    registry = corpus_registry(corpus)
    assert registry.is_critical("product_code")

    metrics = measure_corpus(corpus, registry)

    product_codes = {key for key in metrics.critical_expected if key[1] == "product_code"}
    assert product_codes, "критичный пользовательский тип product_code не попал в expected"
    assert product_codes <= metrics.critical_found


def test_measure_corpus_is_empty_for_empty_corpus() -> None:
    from masker.entity_types import EntityTypeRegistry

    metrics = measure_corpus([], EntityTypeRegistry.builtin())
    assert metrics == CorpusMetrics()


# ---------------------------------------------------------------------------
# card_metrics — реальное число страниц PDF против числа полей карточки.
# ---------------------------------------------------------------------------


def test_card_metrics_uses_real_pdf_page_count_and_consistent_field_count() -> None:
    pages, fields = card_metrics(_SMALL_PDF)
    assert pages == 1  # физический факт: contract_pdf_01.pdf — один лист.

    _elapsed, outcome = run_once(_SMALL_PDF)
    expected_fields = _count_summary_fields(dict(outcome.state.get("contract_summary", {})))
    assert fields == expected_fields
    assert fields > 0


# ---------------------------------------------------------------------------
# Подпроцесс: время + пиковая память измеряются изолированно.
# ---------------------------------------------------------------------------


def test_child_measure_prints_result_line_with_positive_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_child_measure(_SMALL_DOCX)
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith("BENCH_RESULT ")]
    assert len(lines) == 1
    payload = json.loads(lines[0][len("BENCH_RESULT ") :])
    assert payload["seconds"] > 0
    assert payload["peak_rss_kb"] > 0


def test_measure_size_docs_runs_isolated_subprocess_per_repeat() -> None:
    docs = (SizeDoc("тестовый docx", _SMALL_DOCX, 2),)
    results = measure_size_docs(docs)
    assert len(results) == 1
    measurement = results[0]
    assert measurement.repeats == 2
    assert len(measurement.seconds) == 2
    assert len(measurement.peak_rss_kb) == 2
    assert measurement.seconds_median > 0
    assert measurement.peak_rss_mb_median > 0


# ---------------------------------------------------------------------------
# main() / run() — точка входа: маршрутизация --child-measure и код возврата.
# ---------------------------------------------------------------------------


def test_main_child_measure_route_does_not_call_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import masker.bench as bench_module

    called = False

    def _fail_run(_args: argparse.Namespace) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(bench_module, "run", _fail_run)
    exit_code = bench_module.main(["--child-measure", str(_SMALL_DOCX)])
    assert exit_code == 0
    assert called is False


# ---------------------------------------------------------------------------
# run() с подменёнными дорогими шагами — оркестрация и разделение
# ЗАМЕРЕНО/ПРОГНОЗ, оба ветвления (прогноз задан / прогноз не задан).
# ---------------------------------------------------------------------------


@pytest.fixture
def _patched_expensive_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    import masker.bench as bench_module

    fake_metrics = CorpusMetrics(
        critical_expected={("doc.docx", "inn", "123")},
        critical_found={("doc.docx", "inn", "123")},
        leaked_total=0,
        docs=1,
        elapsed_by_doc={"doc.docx": 2.0},
    )

    monkeypatch.setattr(bench_module, "stage_timings", lambda *_a, **_k: {"extract": [0.01]})
    monkeypatch.setattr(bench_module, "measure_corpus", lambda *_a, **_k: fake_metrics)
    monkeypatch.setattr(bench_module, "measure_size_docs", lambda *_a, **_k: [])
    monkeypatch.setattr(bench_module, "card_metrics", lambda _path: (1, 1))


def test_run_prints_forecast_missing_notice_without_manual_minutes(
    _patched_expensive_steps: None, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(manual_minutes=None, contracts_per_month=100, child_measure=None)
    exit_code = run(args)
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "не считается" in out
    assert "--manual-minutes" in out
    assert "ПРОГНОЗ" in out
    assert "ЗАМЕРЕНО" in out


def test_run_computes_forecast_when_manual_minutes_given(
    _patched_expensive_steps: None, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(manual_minutes=15.0, contracts_per_month=50, child_measure=None)
    exit_code = run(args)
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "ПРОГНОЗ, не замер" in out
    assert "не считается" not in out


def test_run_returns_failure_code_when_leaked_total_positive(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import masker.bench as bench_module

    leaking_metrics = CorpusMetrics(
        critical_expected={("doc.docx", "inn", "123")},
        critical_found={("doc.docx", "inn", "123")},
        leaked_total=1,
        docs=1,
        elapsed_by_doc={"doc.docx": 1.0},
    )
    monkeypatch.setattr(bench_module, "stage_timings", lambda *_a, **_k: {"extract": [0.01]})
    monkeypatch.setattr(bench_module, "measure_corpus", lambda *_a, **_k: leaking_metrics)
    monkeypatch.setattr(bench_module, "measure_size_docs", lambda *_a, **_k: [])
    monkeypatch.setattr(bench_module, "card_metrics", lambda _path: (1, 1))

    args = argparse.Namespace(manual_minutes=None, contracts_per_month=100, child_measure=None)
    exit_code = run(args)
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "ПРОВАЛ" in out


def test_run_returns_failure_code_when_critical_recall_below_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import masker.bench as bench_module

    missed_metrics = CorpusMetrics(
        critical_expected={("doc.docx", "inn", "123"), ("doc.docx", "inn", "456")},
        critical_found={("doc.docx", "inn", "123")},
        leaked_total=0,
        docs=1,
        elapsed_by_doc={"doc.docx": 1.0},
    )
    monkeypatch.setattr(bench_module, "stage_timings", lambda *_a, **_k: {"extract": [0.01]})
    monkeypatch.setattr(bench_module, "measure_corpus", lambda *_a, **_k: missed_metrics)
    monkeypatch.setattr(bench_module, "measure_size_docs", lambda *_a, **_k: [])
    monkeypatch.setattr(bench_module, "card_metrics", lambda _path: (1, 1))

    args = argparse.Namespace(manual_minutes=None, contracts_per_month=100, child_measure=None)
    exit_code = run(args)
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "ПРОВАЛ" in out
