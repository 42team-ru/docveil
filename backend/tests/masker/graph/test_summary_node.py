"""Тест узла summary_node: читает entities/profiles из State, пишет contract_summary."""

from __future__ import annotations

import json

from masker.graph.nodes import RunDeps, make_summary_node, summary_node
from masker.graph.serde import entity_to_dict, plan_to_dict, profiles_to_dicts
from masker.llm import FakeProvider
from masker.mask.agent import PlanAgent
from masker.model import Anchor, Document, Entity, EntityType, Profile, ProfileMember, Segment, Source

_ANCHOR = Anchor(fmt="docx", locator=("body", 0))


def _entity(entity_type: str, text: str) -> Entity:
    return Entity(
        type=entity_type,
        text=text,
        segment_order=0,
        start=0,
        end=len(text),
        source=Source.RULE,
        confidence=0.9,
    )


def _profile_dict(role: str, *entities: Entity) -> dict:
    profile = Profile(
        id=f"prof-{role}",
        role_title=role,
        members=[
            ProfileMember(entity=e, anchor=_ANCHOR, ref=f"ref-{i}") for i, e in enumerate(entities)
        ],
    )
    return profiles_to_dicts([profile])[0]


def _state(**overrides) -> dict:
    base: dict = {
        "path": "doc.docx",
        "fmt": "docx",
        "segments": [],
        "entities": [],
        "profiles": [],
        "llm_calls": 0,
    }
    base.update(overrides)
    return base


def _segment(text: str) -> dict:
    return {
        "text": text,
        "anchor": {"fmt": "docx", "locator": ["body", 0], "label": ""},
        "order": 0,
    }


def test_summary_node_returns_contract_summary_key() -> None:
    result = summary_node(_state())
    assert "contract_summary" in result


def test_summary_node_empty_state_gives_blank_summary() -> None:
    result = summary_node(_state())
    data = result["contract_summary"]
    assert data["customer"] is None
    assert data["supplier"] is None
    assert data["federal_law"] == []
    assert data["contract_amount"] is None
    assert data["delivery_periods"] == []


def test_summary_node_picks_up_federal_law_entities() -> None:
    law = _entity(EntityType.FEDERAL_LAW, "44-ФЗ")
    state = _state(segments=[_segment(law.text)], entities=[entity_to_dict(law)])
    result = summary_node(state)
    assert result["contract_summary"]["federal_law"] == ["44-ФЗ"]


def test_summary_node_picks_up_contract_amount() -> None:
    amount = _entity(EntityType.CONTRACT_AMOUNT, "1 000 000 руб.")
    state = _state(segments=[_segment(amount.text)], entities=[entity_to_dict(amount)])
    result = summary_node(state)
    assert result["contract_summary"]["contract_amount"] == "1 000 000 руб."


def test_summary_node_picks_up_delivery_period() -> None:
    period = _entity(EntityType.DELIVERY_PERIOD, "в течение 30 дней")
    state = _state(segments=[_segment(period.text)], entities=[entity_to_dict(period)])
    result = summary_node(state)
    assert result["contract_summary"]["delivery_periods"] == ["в течение 30 дней"]


def test_default_plan_keeps_payment_and_delivery_values_in_contract_summary() -> None:
    """12.09.2026: видимые условия сделки остаются извлечёнными для карточки."""
    text = "Оплата производится по факту оказания услуг в течение 5 рабочих дней"
    payment = _entity(EntityType.PAYMENT_TERMS, text)
    delivery = _entity(EntityType.DELIVERY_PERIOD, "в течение 5 рабочих дней")
    document = Document(
        path="doc.docx",
        fmt="docx",
        segments=[Segment(text=text, anchor=_ANCHOR, order=0)],
    )
    plan = PlanAgent().plan(document, [payment, delivery])
    result = summary_node(
        _state(
            segments=[_segment(text)],
            entities=[entity_to_dict(payment), entity_to_dict(delivery)],
            plan=plan_to_dict(plan),
        )
    )
    summary = result["contract_summary"]
    assert summary["payment_terms"] == text
    assert summary["delivery_periods"] == ["в течение 5 рабочих дней"]


def test_summary_node_resolves_customer_from_profile() -> None:
    org = _entity(EntityType.ORG_NAME, "ФГБОУ ВО МГУ")
    inn = _entity(EntityType.INN, "7700000001")
    p = _profile_dict("Заказчик", org, inn)
    state = _state(
        entities=[entity_to_dict(org), entity_to_dict(inn)],
        profiles=[p],
    )
    result = summary_node(state)
    customer = result["contract_summary"]["customer"]
    assert customer is not None
    assert customer["name"] == "ФГБОУ ВО МГУ"
    assert customer["inn"] == "7700000001"


def test_summary_node_passes_llm_calls_from_state() -> None:
    state = _state(llm_calls=3)
    result = summary_node(state)
    assert result["contract_summary"]["llm_calls"] == 3


def test_summary_node_with_fake_provider_keeps_rules_and_does_not_call_model() -> None:
    provider = FakeProvider()
    result = make_summary_node(RunDeps(llm=provider))(_state())

    assert result["contract_summary"]["document_kind"]["status"] == "unknown"
    assert result["contract_summary"]["brief_summary"] is None
    assert result["summary_llm_calls"] == 0
    assert provider.calls == 0


class _SummaryProvider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)
        self.calls = 0
        self.schemas: list[dict[str, object] | None] = []

    def complete(self, messages, *, schema=None) -> str:
        del messages
        self.calls += 1
        self.schemas.append(schema)
        return next(self._responses)


def test_summary_node_non_contract_omits_contract_fields() -> None:
    provider = _SummaryProvider(
        [
            json.dumps(
                {
                    "summary": (
                        "Это технические условия. Они задают требования. "
                        "Они описывают контроль качества."
                    ),
                    "kind": "non_contract",
                    "genre": "технические условия",
                    "confidence": 0.94,
                }
            )
        ]
    )
    amount = _entity(EntityType.CONTRACT_AMOUNT, "1 000 000 руб.")
    state = _state(
        segments=[
            {
                "text": "ТЕХНИЧЕСКИЕ УСЛОВИЯ",
                "anchor": {"fmt": "docx", "locator": ["body", 0], "label": ""},
                "order": 0,
            }
        ],
        entities=[entity_to_dict(amount)],
    )

    result = make_summary_node(RunDeps(llm=provider))(state)
    card = result["contract_summary"]
    assert card["document_kind"] == {
        "status": "non_contract",
        "genre": "технические условия",
        "confidence": 0.94,
        "source": "llm",
    }
    assert card["brief_summary"] is not None
    assert card["contract_amount"] is None
    assert card["contract_amount_fact"]["status"] == "not_found"
    assert provider.calls == 1
    assert provider.schemas[0] is not None


def test_summary_node_result_ends_up_in_report(tmp_path) -> None:
    """contract_summary появляется в report, когда граф прогоняется целиком."""
    from pathlib import Path

    from langgraph.checkpoint.sqlite import SqliteSaver

    from masker.graph.build import compile_graph
    from masker.graph.nodes import RunDeps

    root = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
    fixture = root / "fixtures" / "labeled" / "contract_01.docx"

    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t-summary"}}
    initial = {
        "path": str(fixture),
        "options": {
            "types": None,
            "rules_only": False,
            "interactive": False,
            "unmask_critical": False,
            "thread_id": "t-summary",
        },
    }

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(artifact_dir=tmp_path / "artifacts"), saver)
        result = graph.invoke(initial, config)

    assert "contract_summary" in result
    report = result.get("report", {})
    assert "contract_summary" in report
