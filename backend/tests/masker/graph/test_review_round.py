"""Раунд правок оператора — второе прерывание графа (`ask_review`).

Проверяется то, ради чего раунд сделан узлом графа, а не ручкой в API:
документ пересобирается тем же путём `plan → … → report`, поэтому защита
критичных типов, согласованность маркеров и проверка утечек продолжают
работать на правках оператора, а не только на решениях движка.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from masker.graph.nodes import RunDeps
from masker.graph.review import SCHEMA_VERSION, parse_review_edits
from masker.model import Action
from masker.run import (
    RunOptions,
    resume_review,
    sqlite_checkpointer_factory,
    start_run,
)

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"


def _factory(tmp_path: Path):
    return sqlite_checkpointer_factory(tmp_path / "state.sqlite")


def _deps(tmp_path: Path) -> RunDeps:
    return RunDeps(artifact_dir=tmp_path / "artifacts")


def _envelope(**edits: object) -> dict[str, object]:
    """Правки как их шлёт клиент; конверт вокруг них ставит ``resume_review``."""
    return dict(edits)


def _reach_review(tmp_path: Path, *, unmask_critical: bool = False):
    """Довести прогон до паузы на правках: ответы человека заданы заранее."""
    options = RunOptions(
        rules_only=True,
        types=("inn", "phone"),
        interactive=False,
        review=True,
        styles=("marker",),
        unmask_critical=unmask_critical,
    )
    outcome = start_run(
        FIXTURE, options, checkpointer_factory=_factory(tmp_path), deps=_deps(tmp_path)
    )
    assert outcome.status == "waiting"
    return outcome


def _actions(state: dict[str, object]) -> dict[str, str]:
    return {str(item["ref"]): str(item["action"]) for item in state["final_actions"]}


def test_run_without_review_option_ends_after_report(tmp_path: Path) -> None:
    """Без запроса раунда правок граф доходит до конца, как раньше."""
    outcome = start_run(
        FIXTURE,
        RunOptions(rules_only=True, types=("inn",), interactive=False, styles=("marker",)),
        checkpointer_factory=_factory(tmp_path),
        deps=_deps(tmp_path),
    )

    assert outcome.status == "done"


def test_review_round_pauses_with_report_in_payload(tmp_path: Path) -> None:
    """Пауза отдаёт готовый отчёт: оператор правит то, что видит."""
    outcome = _reach_review(tmp_path)

    assert outcome.payload is not None
    assert outcome.payload["schema_version"] == SCHEMA_VERSION
    assert outcome.payload["document"]["name"] == FIXTURE.name
    assert outcome.payload["report"]["report_version"] == 4


def test_operator_keep_removes_mask_for_non_critical_type(tmp_path: Path) -> None:
    paused = _reach_review(tmp_path)
    # Телефон некритичен: снятие маски с него — обычное решение оператора.
    ref = _phone_ref(paused)

    done = resume_review(
        paused.thread_id,
        _envelope(decisions={ref: "keep"}),
        checkpointer_factory=_factory(tmp_path),
        deps=_deps(tmp_path),
    )

    assert done.status == "done"
    assert _actions(done.state)[ref] == Action.KEEP.value


def test_operator_cannot_unmask_critical_type_without_permission(tmp_path: Path) -> None:
    """Двойной барьер держится и во втором раунде: ИНН молча не снимается."""
    paused = _reach_review(tmp_path)
    ref = _inn_ref(paused)

    done = resume_review(
        paused.thread_id,
        _envelope(decisions={ref: "keep"}),
        checkpointer_factory=_factory(tmp_path),
        deps=_deps(tmp_path),
    )

    assert _actions(done.state)[ref] == Action.MASK.value
    assert any("критичн" in line for line in done.state["decisions"]["review_diagnostics"])


def test_operator_unmasks_critical_type_with_explicit_permission(tmp_path: Path) -> None:
    paused = _reach_review(tmp_path, unmask_critical=True)
    ref = _inn_ref(paused)

    done = resume_review(
        paused.thread_id,
        _envelope(decisions={ref: "keep"}),
        checkpointer_factory=_factory(tmp_path),
        deps=_deps(tmp_path),
    )

    assert _actions(done.state)[ref] == Action.KEEP.value


def test_manual_value_is_masked_everywhere_it_occurs(tmp_path: Path) -> None:
    """Добавленное оператором значение получает один маркер по всему документу.

    Тип берётся вне отбора прогона (``types=("inn", "phone")``) намеренно:
    правка оператора не имеет права молча исчезнуть из-за фильтра типов.
    """
    paused = _reach_review(tmp_path)
    sample = paused.state["segments"][0]["text"].split()[0]

    done = resume_review(
        paused.thread_id,
        _envelope(manual=[{"type": "org_name", "text": sample}]),
        checkpointer_factory=_factory(tmp_path),
        deps=_deps(tmp_path),
    )

    added = [item for item in done.state["entities"] if item["source"] == "user"]
    assert added
    assert all(item["text"] == sample for item in added)
    markers = {
        replacement["marker"]
        for replacement in done.state["plan"]["replacements"]
        if replacement["entity"]["text"] == sample
    }
    assert len(markers) == 1


def test_review_round_runs_once_and_finishes(tmp_path: Path) -> None:
    """После применённых правок прогон завершён: второго круга вопросов нет."""
    paused = _reach_review(tmp_path)

    done = resume_review(
        paused.thread_id,
        _envelope(),
        checkpointer_factory=_factory(tmp_path),
        deps=_deps(tmp_path),
    )

    assert done.status == "done"
    assert done.state["review_round"] == 1
    assert done.state["report"]["report_version"] == 4
    # Пересобранный документ проверен валидатором заново — утечек нет.
    assert done.state["leaked"] == []


def test_edits_with_wrong_schema_version_are_rejected() -> None:
    with pytest.raises(ValueError, match="несовместимая версия"):
        parse_review_edits({"schema_version": 2, "edits": {}})


def test_unknown_action_and_unknown_type_are_dropped() -> None:
    """Мусор отбрасывается молча: молчание значит «решение движка в силе»."""
    parsed = parse_review_edits(
        {
            "schema_version": SCHEMA_VERSION,
            "edits": {
                "decisions": {"E1": "burn", "E2": "keep"},
                "manual": [{"type": "", "text": "x"}, {"type": "inn", "text": "  "}],
            },
        }
    )

    assert parsed["decisions"] == {"E2": "keep"}
    assert parsed["manual"] == []


def _ref_of_type(outcome, type_id: str) -> str:
    """Ссылка первой сущности заданного типа в текстовом порядке."""
    for item in outcome.state["final_actions"]:
        ref = str(item["ref"])
        entity = _entity_by_ref(outcome, ref)
        if entity["type"] == type_id:
            return ref
    raise AssertionError(f"в фикстуре нет сущности типа {type_id!r}")


def _entity_by_ref(outcome, ref: str) -> dict:
    entities = sorted(
        outcome.state["entities"],
        key=lambda item: (item["segment_order"], item["start"], item["end"], item["type"]),
    )
    return entities[int(ref[1:]) - 1]


def _inn_ref(outcome) -> str:
    return _ref_of_type(outcome, "inn")


def _phone_ref(outcome) -> str:
    return _ref_of_type(outcome, "phone")
