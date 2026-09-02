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


def test_llm_cannot_lower_role_confidence() -> None:
    document, detection = _seller_document()
    response = json.dumps(
        {
            "profiles": [
                {"id": "P1", "role_title": "Продавец", "confidence": 0.0, "members": ["E1"]}
            ],
            "candidates": [],
        }
    )

    result = ProfileAgent(FakeProvider([response])).profile(document, detection)

    profile = result.profiles[0]
    assert profile.role_confidence == 0.9
    assert profile.source is Source.RULE
    assert profile.evidence == ["метка: продавец"]
    assert profile.role_title == "Продавец"


def test_llm_names_missing_role() -> None:
    document, detection = _unlabeled_document()
    assert result_source_is_rule_before_llm(document, detection)
    response = json.dumps(
        {
            "profiles": [
                {"id": "P1", "role_title": "Арендатор", "confidence": 0.6, "members": ["E1"]}
            ],
            "candidates": [],
        }
    )

    result = ProfileAgent(FakeProvider([response])).profile(document, detection)

    profile = result.profiles[0]
    assert profile.role_title == "Арендатор"
    assert profile.role_confidence == 0.6
    assert profile.source is Source.LLM
    assert profile.evidence == [
        "структурный блок",
        "LLM: роль «Арендатор» с уверенностью 0.6",
    ]


def result_source_is_rule_before_llm(document: Document, detection: DetectionResult) -> bool:
    baseline = ProfileAgent(None).profile(document, detection)
    profile = baseline.profiles[0]
    return profile.source is Source.RULE and profile.role_confidence == 0.0
