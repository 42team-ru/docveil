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

import json
import pathlib
import warnings
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
                "gigachat": {
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
                "gigachat": {
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
                "gigachat": {
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
# bench_matrix: человеческий потоковый вывод без чужого шума.
# ---------------------------------------------------------------------------


def test_run_prints_plan_and_each_cell_when_it_finishes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = [(pathlib.Path("doc.docx"), {"entities": []})]
    monkeypatch.setattr(eval_module, "load_corpus", lambda: corpus)
    monkeypatch.setattr(eval_module, "corpus_registry", lambda _corpus: object())
    monkeypatch.setattr(
        bm,
        "detection_layer_cell",
        lambda layer, _corpus, _registry: bm.CellResult(
            name=layer,
            status="ok",
            metrics={
                "precision": 1.0,
                "recall": 1.0,
                "critical_recall": 1.0,
                "leaked_total": 0,
                "custom_types": {},
            },
        ),
    )
    monkeypatch.setattr(
        bm,
        "gliner_layer_cell",
        lambda: _gliner_cell_with_library_banner(),
    )
    monkeypatch.setattr(
        bm,
        "regex_llm_filter_layer_cell",
        lambda: _class_d_cell("regex_llm_filter", f1=1.0),
    )

    def fake_llm(axis: str, _corpus: Any, **kwargs: Any) -> bm.CellResult:
        layer = kwargs.get("layer_label", "ner")
        return bm.CellResult(
            name=f"{layer}+{axis}",
            status="ok",
            metrics={
                "role_accuracy": 0.833,
                "cluster_purity": 1.0,
                "llm_usage": {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "message": "Потрачено 0: модель не понадобилась для этого документа.",
                },
            },
        )

    monkeypatch.setattr(bm, "llm_axis_cell", fake_llm)

    result = bm.run(layers=("rules", "ner", "gliner"), axes=("none", "cassette"))
    output = capsys.readouterr().out

    assert result["llm"]["ner+none"]["status"] == "ok"
    assert result["regex_llm_filter"]["status"] == "ok"
    assert "ПЛАН: 7 клеток" in output
    assert "СТОЛБЦЫ:" in output
    assert "role_acc — точность назначения роли" in output
    assert "purity — доля профилей" in output
    assert "critR — полнота только по критичным типам" in output
    assert "leaked — сколько исходных значений" in output
    assert output.index("считаю слой детекции rules") < output.index("готово: rules")
    assert output.index("считаю слой детекции ner") < output.index("готово: ner")
    assert output.index("считаю слой детекции gliner") < output.index("готово: gliner")
    assert "считаю слой детекции regex_llm_filter (живой GigaChat)" in output
    assert "шум GLiNER2" not in output
    assert output.index("считаю профиль/судья ner+none") < output.index("готово: ner+none")
    assert output.index("считаю профиль/судья ner+cassette") < output.index("готово: ner+cassette")
    assert output.index("считаю профиль/судья rules+none") < output.index("готово: rules+none")
    assert "ВЫВОД:" in output


def _gliner_cell_with_library_banner() -> bm.CellResult:
    """Имитирует banner GLiNER2, который библиотека печатает мимо logging."""
    print("шум GLiNER2")
    return bm.CellResult(
        name="gliner",
        status="ok",
        metrics={
            "by_type": {
                "shipment_date": {
                    "precision": 1.0,
                    "recall": 1.0,
                    "f1": 1.0,
                    "fn": 0,
                    "fp": 0,
                },
                "signing_date": {
                    "precision": 1.0,
                    "recall": 1.0,
                    "f1": 1.0,
                    "fn": 0,
                    "fp": 0,
                },
            }
        },
    )


def _class_d_cell(name: str, *, f1: float) -> bm.CellResult:
    return bm.CellResult(
        name=name,
        status="ok",
        metrics={
            "by_type": {
                type_id: {"precision": f1, "recall": f1, "f1": f1, "fn": 0, "fp": 0}
                for type_id in ("shipment_date", "signing_date")
            }
        },
    )


def test_quiet_library_noise_keeps_our_warning_visible() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with bm._quiet_library_noise():
            warnings.warn("product_code требует внимания", UserWarning, stacklevel=2)
            warnings.warn_explicit(
                "torch сообщает о будущем изменении",
                UserWarning,
                filename="torch_warning.py",
                lineno=1,
                module="torch.nn",
            )

    messages = [str(item.message) for item in caught]
    assert messages == ["product_code требует внимания"]


# ---------------------------------------------------------------------------
# bench_matrix: слой gliner — честный пропуск без пакета.
# ---------------------------------------------------------------------------


def test_gliner_layer_cell_skips_when_package_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bm, "gliner_available", lambda: False)

    cell = bm.gliner_layer_cell()

    assert cell.status == "skipped"
    assert "gliner2" in cell.reason


def test_regex_llm_filter_layer_cell_skips_without_gigachat_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bm, "llm_axis_skip_reason", lambda _axis: "нет GIGACHAT_CREDENTIALS")
    monkeypatch.setattr(bm, "get_provider", lambda _config: pytest.fail("провайдер не нужен"))

    cell = bm.regex_llm_filter_layer_cell()

    assert cell.status == "skipped"
    assert "GIGACHAT_CREDENTIALS" in cell.reason


def test_class_d_regex_llm_filter_types_are_separate_from_gliner_labels() -> None:
    """Сравнение не меняет исходную GLiNER-разметку и несёт русские различители."""
    payload = json.loads(bm.REGEX_LLM_FILTER_TYPES.read_text(encoding="utf-8"))

    assert [item["detect"]["kind"] for item in payload["types"]] == [
        "regex_llm_filter",
        "regex_llm_filter",
    ]
    assert all(item["detect"]["description"] for item in payload["types"])


def test_human_summary_says_when_class_d_is_unsolved(capsys: pytest.CaptureFixture[str]) -> None:
    bm._print_human_summary(
        [], _class_d_cell("gliner", f1=0.0), _class_d_cell("regex_llm_filter", f1=0.0), []
    )

    assert "Задача класса D не решена ни одним из двух подходов" in capsys.readouterr().out


def test_gliner_available_reflects_real_environment() -> None:
    """Не мок: убеждаемся, что функция реально смотрит на окружение (importlib)."""
    import importlib.util

    assert bm.gliner_available() == (importlib.util.find_spec("gliner2") is not None)
