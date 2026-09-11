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


def test_signature_metadata_does_not_attach_other_side_or_country_to_executor() -> None:
    """12.09.2026: второй сертификат ЭП не наследует роль Исполнителя."""
    texts = [
        "ЗАКАЗЧИК: Угнивенко Дмитрия Константиновича",
        "ИСПОЛНИТЕЛЬ: Ермаков Валерий Викторович; Российская Федерация",
        "Данные электронной подписи",
        "Владелец: Угнивенко Дмитрий Константинович; Организация: Российская Федерация",
    ]
    segments = [
        Segment(text, Anchor("pdf", ("page", 0, order, order + len(text))), order)
        for order, text in enumerate(texts)
    ]

    def person(order: int, value: str) -> Entity:
        start = texts[order].index(value)
        return Entity(EntityType.PERSON, value, order, start, start + len(value), Source.NER, 0.9)

    customer = person(0, "Угнивенко Дмитрия Константиновича")
    executor = person(1, "Ермаков Валерий Викторович")
    false_country = person(1, "Российская Федерация")
    certificate_owner = person(3, "Угнивенко Дмитрий Константинович")
    result = ProfileAgent().profile(
        Document("signature.pdf", "pdf", segments),
        DetectionResult([customer, executor, false_country, certificate_owner], []),
    )

    executor_profile = next(
        profile for profile in result.profiles if profile.marker_label == "ИСПОЛНИТЕЛЬ"
    )
    executor_texts = {member.entity.text for member in executor_profile.members}
    assert "Угнивенко Дмитрий Константинович" not in executor_texts
    assert "Российская Федерация" not in executor_texts
    customer_profile = next(
        profile for profile in result.profiles if profile.marker_label == "ЗАКАЗЧИК"
    )
    assert "Угнивенко Дмитрий Константинович" in {
        member.entity.text for member in customer_profile.members
    }


def result_source_is_rule_before_llm(document: Document, detection: DetectionResult) -> bool:
    baseline = ProfileAgent(None).profile(document, detection)
    profile = baseline.profiles[0]
    return profile.source is Source.RULE and profile.role_confidence == 0.0
