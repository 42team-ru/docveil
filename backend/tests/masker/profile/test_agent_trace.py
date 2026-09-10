from __future__ import annotations

import json

from masker.detect.result import DetectionResult
from masker.llm import FakeProvider, TracingProvider
from masker.model import Anchor, Document, Entity, EntityType, Segment, Source
from masker.profile import ProfileAgent


def _seller_document() -> tuple[Document, DetectionResult]:
    """Профиль с надёжной структурной ролью «Продавец» (role_confidence == 0.9)."""
    text = '____, именуемое в дальнейшем "Продавец", ИНН 7701234567'
    inn_start = text.index("7701234567")
    segment = Segment(text, Anchor("docx", ("body", 0)), 0)
    entity = Entity(
        EntityType.INN,
        "7701234567",
        0,
        inn_start,
        inn_start + len("7701234567"),
        Source.RULE,
        0.9,
        "7701234567",
    )
    document = Document("test.docx", "docx", [segment])
    detection = DetectionResult([entity], [])
    return document, detection


def _unlabeled_document() -> tuple[Document, DetectionResult]:
    """Профиль без структурной роли (role_confidence == 0.0)."""
    text = "ИНН 7701234567"
    inn_start = text.index("7701234567")
    segment = Segment(text, Anchor("docx", ("body", 0)), 0)
    entity = Entity(
        EntityType.INN,
        "7701234567",
        0,
        inn_start,
        inn_start + len("7701234567"),
        Source.RULE,
        0.9,
        "7701234567",
    )
    document = Document("test.docx", "docx", [segment])
    detection = DetectionResult([entity], [])
    return document, detection


def test_trace_records_empty_role_outcome() -> None:
    document, detection = _unlabeled_document()
    response = json.dumps(
        {"profiles": [{"id": "P1", "role_title": "", "confidence": 0.8, "members": ["E1"]}]}
    )
    tracer = TracingProvider(FakeProvider([response]))

    ProfileAgent(tracer).profile(document, detection)

    assert len(tracer.batches) == 1
    batch = tracer.batches[0]
    assert batch.proposed_profiles == 1
    assert batch.valid_profiles == 1
    assert len(batch.outcomes) == 1
    outcome = batch.outcomes[0]
    assert outcome.profile_id == "P1"
    assert outcome.outcome == "empty_role"
    assert outcome.old_role_title == ""
    assert outcome.new_role_title == ""


def test_trace_is_empty_when_heuristic_role_is_confident() -> None:
    document, detection = _seller_document()
    response = json.dumps(
        {"profiles": [{"id": "P1", "role_title": "Продавец", "confidence": 0.5, "members": ["E1"]}]}
    )
    tracer = TracingProvider(FakeProvider([response]))

    ProfileAgent(tracer).profile(document, detection)

    assert tracer.calls == []
    assert tracer.batches == []


def test_trace_records_rejected_by_validation_outcome() -> None:
    document, detection = _unlabeled_document()
    # Модель пытается поменять состав профиля — valid_decision отклонит это.
    response = json.dumps(
        {
            "profiles": [
                {
                    "id": "P1",
                    "role_title": "Покупатель",
                    "confidence": 0.9,
                    "members": [],
                }
            ]
        }
    )
    tracer = TracingProvider(FakeProvider([response]))

    ProfileAgent(tracer).profile(document, detection)

    assert len(tracer.batches) == 1
    batch = tracer.batches[0]
    assert batch.proposed_profiles == 1
    assert batch.valid_profiles == 0
    outcome = batch.outcomes[0]
    assert outcome.profile_id == "P1"
    assert outcome.outcome == "rejected_by_validation"
    assert "P1" in outcome.reason
    assert "состав" in outcome.reason


def test_trace_records_applied_outcome() -> None:
    document, detection = _unlabeled_document()
    response = json.dumps(
        {
            "profiles": [
                {"id": "P1", "role_title": "Арендатор", "confidence": 0.9, "members": ["E1"]}
            ]
        }
    )
    tracer = TracingProvider(FakeProvider([response]))

    ProfileAgent(tracer).profile(document, detection)

    outcome = tracer.batches[0].outcomes[0]
    assert outcome.outcome == "applied"
    assert outcome.old_role_title == ""
    assert outcome.new_role_title == "Арендатор"
    assert outcome.old_confidence == 0.0
    assert outcome.new_confidence == 0.9


def test_trace_batch_call_index_matches_wire_call() -> None:
    document, detection = _unlabeled_document()
    response = json.dumps(
        {
            "profiles": [
                {"id": "P1", "role_title": "Арендатор", "confidence": 0.9, "members": ["E1"]}
            ]
        }
    )
    tracer = TracingProvider(FakeProvider([response]))

    ProfileAgent(tracer).profile(document, detection)

    assert tracer.batches[0].call_index == tracer.calls[0].index == 1


def test_result_is_unchanged_without_tracer() -> None:
    """Без трейсера ProfileResult идентичен прежнему поведению — байт в байт."""
    document, detection = _unlabeled_document()
    response = json.dumps(
        {
            "profiles": [
                {"id": "P1", "role_title": "Арендатор", "confidence": 0.9, "members": ["E1"]}
            ]
        }
    )

    plain = ProfileAgent(FakeProvider([response])).profile(document, detection)
    traced_provider = TracingProvider(FakeProvider([response]))
    traced = ProfileAgent(traced_provider).profile(document, detection)

    assert plain.llm_calls == traced.llm_calls
    assert plain.diagnostics == traced.diagnostics
    profile_plain = plain.profiles[0]
    profile_traced = traced.profiles[0]
    assert profile_plain.role_title == profile_traced.role_title
    assert profile_plain.role_confidence == profile_traced.role_confidence
    assert profile_plain.source == profile_traced.source
    assert profile_plain.evidence == profile_traced.evidence
