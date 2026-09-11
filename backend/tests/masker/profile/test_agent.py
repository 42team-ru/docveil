from __future__ import annotations

import json

from masker.detect.result import DetectionResult
from masker.llm import FakeProvider
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


def test_llm_is_not_called_when_heuristic_role_is_confident() -> None:
    document, detection = _seller_document()
    response = json.dumps(
        {
            "profiles": [
                {"id": "P1", "role_title": "Продавец", "confidence": 0.0, "members": ["E1"]}
            ],
            "candidates": [],
        }
    )

    provider = FakeProvider([response])
    result = ProfileAgent(provider).profile(document, detection)

    profile = result.profiles[0]
    assert profile.role_confidence == 0.9
    assert profile.source is Source.RULE
    assert profile.evidence == ["метка: продавец"]
    assert profile.role_title == "Продавец"
    assert provider.calls == 0


def test_llm_names_missing_role() -> None:
    document, detection = _unlabeled_document()
    assert result_source_is_rule_before_llm(document, detection)
    response = json.dumps(
        {
            "profiles": [
                {"id": "P1", "role_title": "Арендатор", "confidence": 0.9, "members": ["E1"]}
            ]
        }
    )

    result = ProfileAgent(FakeProvider([response])).profile(document, detection)

    profile = result.profiles[0]
    assert profile.role_title == "Арендатор"
    assert profile.role_confidence == 0.9
    assert profile.source is Source.LLM
    assert profile.evidence == [
        "структурный блок",
        "LLM: роль «Арендатор» с уверенностью 0.9",
    ]


def test_power_of_attorney_number_and_ip_address_stay_without_party_profile() -> None:
    """Документные реквизиты не должны получать произвольную роль стороны."""
    text = "Доверенность № МЧД-42; IP-адрес: 83.171.96.195"
    segment = Segment(text, Anchor("docx", ("body", 0)), 0)
    entities = [
        Entity(
            entity_type,
            value,
            0,
            text.index(value),
            text.index(value) + len(value),
            Source.RULE,
            1.0,
            value,
        )
        for entity_type, value in (
            (EntityType.POWER_OF_ATTORNEY_NUMBER, "МЧД-42"),
            (EntityType.IP_ADDRESS, "83.171.96.195"),
        )
    ]

    result = ProfileAgent().profile(
        Document("test.docx", "docx", [segment]), DetectionResult(entities, [])
    )

    assert result.profiles == []
    assert result.unassigned == ["E1", "E2"]


def result_source_is_rule_before_llm(document: Document, detection: DetectionResult) -> bool:
    baseline = ProfileAgent(None).profile(document, detection)
    profile = baseline.profiles[0]
    return profile.source is Source.RULE and profile.role_confidence == 0.0
