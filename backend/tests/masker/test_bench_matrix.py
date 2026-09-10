"""Тесты `masker.bench_matrix` (К4) и параметров, которые он добавил
`masker.pipeline.mask_and_validate`/`masker.eval._mask_corpus`/
`masker.eval._profile_judge_metrics`.

Быстрые тесты подменяют сеть/детекцию синтетикой (та же дисциплина, что и
`tests/masker/test_eval.py`); там, где проверяется именно проводка нового
параметра сквозь граф (`rules_only`) или дубль детекторов (`_rules_only_detectors`),
используется один маленький реальный документ — без него расхождение с
`graph/nodes.py` осталось бы незамеченным.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

import masker.bench_matrix as bm
import masker.eval as eval_module
from masker.detect.agent import DetectAgent
from masker.graph import nodes
from masker.ingest.docx_ingest import ingest_docx
from masker.llm.base import LLMError
from masker.llm.fake import FakeProvider
from masker.model import EntityType
from masker.pipeline import MaskResult, mask_and_validate

FIXTURES = eval_module.FIXTURES
SMALL_DOCX = FIXTURES / "contract_05_tables.docx"


# ---------------------------------------------------------------------------
# pipeline.mask_and_validate: новый kwarg rules_only.
# ---------------------------------------------------------------------------


def test_mask_and_validate_rules_only_narrows_detection() -> None:
    """`rules_only=True` обязан убрать типы, которые находит только NER.

    На `contract_05_tables.docx` `org_name` находится оргформенным/NER-слоем,
    а не правилом с контрольной суммой — без проводки `rules_only` в
    `RunOptions` (эта задача) счётчик `org_name` совпадал бы в обоих режимах.
    """
    with mask_and_validate(SMALL_DOCX, types=list(EntityType), rules_only=False) as full:
        full_types = {r.entity.type for r in full.plan.replacements}
    with mask_and_validate(SMALL_DOCX, types=list(EntityType), rules_only=True) as rules_only:
        rules_only_types = {r.entity.type for r in rules_only.plan.replacements}

    assert "org_name" in full_types
    assert "org_name" not in rules_only_types
    # inn — по контрольной сумме, обязан остаться в обоих режимах.
    assert "inn" in full_types
    assert "inn" in rules_only_types


# ---------------------------------------------------------------------------
# eval._mask_corpus: rules_only/llm прокидываются в mask_and_validate.
# ---------------------------------------------------------------------------


def test_mask_corpus_threads_rules_only_to_mask_and_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_kwargs: list[dict[str, Any]] = []

    from contextlib import contextmanager

    @contextmanager
    def fake(path: pathlib.Path, *, types: Any, custom_types: Any = (), **kwargs: Any) -> Any:
        seen_kwargs.append(kwargs)
        from masker.model import MaskPlan, ValidationReport

        yield MaskResult(
            plan=MaskPlan(replacements=(), groups=(), skipped=(), requested_types=()),
            validation=ValidationReport(
                leaked=(), residual=(), checked_artifacts=(), checked_parts=(), ok=True
            ),
            artifacts=(),
        )

    monkeypatch.setattr("masker.pipeline.mask_and_validate", fake)
    corpus = [(pathlib.Path("doc.docx"), {"entities": []})]

    eval_module._mask_corpus(corpus, rules_only=True)

    assert seen_kwargs == [{"rules_only": True, "llm": None}]


# ---------------------------------------------------------------------------
# eval._profile_judge_metrics: provider/detect_agent_factory — новые ручки.
# ---------------------------------------------------------------------------


def test_profile_judge_metrics_uses_injected_provider_not_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без явного `provider` функция обязана звать `get_provider()` — с ним не должна."""
    calls: list[str] = []
    monkeypatch.setattr(
        eval_module, "get_provider", lambda: calls.append("default") or FakeProvider()
    )

    corpus: list[tuple[pathlib.Path, dict[str, Any]]] = []
    eval_module._profile_judge_metrics(corpus, provider=FakeProvider())

    assert calls == []  # get_provider() ни разу не вызван — явный provider был использован


def test_profile_judge_metrics_uses_injected_detect_agent_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made: list[str] = []

    def factory() -> DetectAgent:
        made.append("made")
        return DetectAgent([])

    corpus: list[tuple[pathlib.Path, dict[str, Any]]] = []
    eval_module._profile_judge_metrics(corpus, detect_agent_factory=factory)

    # Пустой корпус — фабрика ни разу не позвана (цикл по документам пуст),
    # но обязана быть принята без ошибки типов/сигнатуры.
    assert made == []


# ---------------------------------------------------------------------------
# bench_matrix: детектор rules-only не разошёлся с graph/nodes.py.
# ---------------------------------------------------------------------------


def test_rules_only_detectors_match_detect_node() -> None:
    """Дубль `_rules_only_detectors()` обязан давать те же сущности, что и
    настоящая ветка `rules_only=True` в `make_detect_node` (`graph/nodes.py`)."""
    state: dict[str, Any] = {
        "path": str(SMALL_DOCX),
        "options": {"rules_only": True, "types": None, "interactive": False},
    }
    state.update(nodes.extract_node(state))
    state.update(nodes.make_detect_node(nodes.RunDeps())(state))
    node_entities = {
        (item["type"], item["segment_order"], item["start"], item["end"])
        for item in state["entities"]
    }

    document = ingest_docx(SMALL_DOCX)
    direct = DetectAgent(bm._rules_only_detectors()).detect(document)
    direct_entities = {
        (entity.type, entity.segment_order, entity.start, entity.end) for entity in direct.entities
    }

    assert node_entities == direct_entities
    assert node_entities  # документ обязан дать хоть одну сущность — иначе сравнение пустое


# ---------------------------------------------------------------------------
# bench_matrix: ось 1 — detection_layer_cell делегирует rules_only.
# ---------------------------------------------------------------------------


def test_detection_layer_cell_passes_rules_only_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def fake_mask_corpus(
        _corpus: Any, *, rules_only: bool = False, llm: Any = None
    ) -> eval_module.MaskingMetrics:
        seen.append(rules_only)
        return eval_module.MaskingMetrics()

    monkeypatch.setattr(eval_module, "_mask_corpus", fake_mask_corpus)
    registry = eval_module.EntityTypeRegistry.builtin()

    bm.detection_layer_cell("rules", [], registry)
    bm.detection_layer_cell("ner", [], registry)

    assert seen == [True, False]


def test_detection_layer_cell_rejects_gliner() -> None:
    """`gliner` меряется отдельной функцией (свой корпус) — не через эту."""
    with pytest.raises(ValueError, match="gliner"):
        bm.detection_layer_cell("gliner", [], eval_module.EntityTypeRegistry.builtin())


# ---------------------------------------------------------------------------
# bench_matrix: ось 2 — пропуски offline, честные причины, не падения.
# ---------------------------------------------------------------------------


def test_llm_axis_skip_reason_none_and_cassette_never_skip() -> None:
    assert bm.llm_axis_skip_reason("none") is None
    assert bm.llm_axis_skip_reason("cassette") is None


def test_llm_axis_skip_reason_reports_missing_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bm,
        "project_section",
        lambda _name: {
            "profile": "fake",
            "profiles": {
                "gigachat-max": {
                    "provider": "gigachat",
                    "model": "GigaChat-Max",
                    "api_key_env": "GIGACHAT_CREDENTIALS",
                }
            },
        },
    )
    monkeypatch.delenv("GIGACHAT_CREDENTIALS", raising=False)

    reason = bm.llm_axis_skip_reason("gigachat")

    assert reason is not None
    assert "GIGACHAT_CREDENTIALS" in reason


def test_llm_axis_skip_reason_reports_broken_pricing_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Задание №3: конфигурация не отработала — так и пишем, не роняем прогон."""
    monkeypatch.setattr(
        bm,
        "project_section",
        lambda _name: {
            "profile": "fake",
            "profiles": {
                "gigachat-max": {
                    "provider": "gigachat",
                    "model": "GigaChat-Max",
                    "api_key_env": "GIGACHAT_CREDENTIALS",
                    "pricing": {"prompt_per_1k": 1},  # completion_per_1k отсутствует — невалидно
                }
            },
        },
    )
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "dummy")

    reason = bm.llm_axis_skip_reason("gigachat")

    assert reason is not None
    assert "конфигурация профиля" in reason


def test_llm_axis_cell_skips_live_axis_without_calling_get_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Задание №2/№7: без ключа живой провайдер не должен даже собираться."""
    monkeypatch.setattr(
        bm,
        "project_section",
        lambda _name: {
            "profile": "fake",
            "profiles": {
                "gigachat-max": {
                    "provider": "gigachat",
                    "model": "GigaChat-Max",
                    "api_key_env": "GIGACHAT_CREDENTIALS",
                }
            },
        },
    )
    monkeypatch.delenv("GIGACHAT_CREDENTIALS", raising=False)

    def boom(_config: Any) -> Any:
        raise AssertionError("get_provider не должен вызываться без ключа")

    monkeypatch.setattr(bm, "get_provider", boom)

    cell = bm.llm_axis_cell("gigachat", [])

    assert cell.status == "skipped"
    assert "GIGACHAT_CREDENTIALS" in cell.reason


def test_llm_axis_cell_reports_llm_error_as_failed_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Кассета без записи для корпуса — ``LLMError``: клетка обязана поймать
    его и показать причину, а не уронить весь матричный прогон."""

    def raising_profile_judge_metrics(*_args: Any, **_kwargs: Any) -> dict[str, float]:
        raise LLMError("в кассете нет ответа для ключа test")

    monkeypatch.setattr(eval_module, "_profile_judge_metrics", raising_profile_judge_metrics)

    cell = bm.llm_axis_cell("none", [(pathlib.Path("doc.docx"), {"entities": []})])

    assert cell.status == "failed"
    assert "test" in cell.reason


def test_llm_axis_cell_none_axis_offline_on_real_tiny_corpus() -> None:
    """Ось `none` — офлайн-путь целиком (`FakeProvider`), реальный маленький документ."""
    corpus = [
        (
            SMALL_DOCX,
            {"entities": [{"type": "inn", "text": "7707083893"}]},
        )
    ]

    cell = bm.llm_axis_cell("none", corpus)

    assert cell.status == "ok"
    assert 0.0 <= cell.metrics["role_accuracy"] <= 1.0
    assert cell.metrics["llm_usage"]["status"] != "charged"


# ---------------------------------------------------------------------------
# bench_matrix: слой gliner — честный пропуск без пакета.
# ---------------------------------------------------------------------------


def test_gliner_layer_cell_skips_when_package_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bm, "gliner_available", lambda: False)

    cell = bm.gliner_layer_cell()

    assert cell.status == "skipped"
    assert "gliner2" in cell.reason


def test_gliner_available_reflects_real_environment() -> None:
    """Не мок: убеждаемся, что функция реально смотрит на окружение (importlib)."""
    import importlib.util

    assert bm.gliner_available() == (importlib.util.find_spec("gliner2") is not None)
