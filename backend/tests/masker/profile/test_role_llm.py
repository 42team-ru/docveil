"""И2-3: LLM уточняет только открытые роли и не выдумывает их."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from masker.detect.result import DetectionResult
from masker.llm import FakeProvider, Message, get_provider
from masker.model import Anchor, Document, Entity, EntityType, Segment, Source
from masker.profile import ProfileAgent
from masker.profile.prompt import MIN_LLM_ROLE_CONFIDENCE, ROLE_RESPONSE_SCHEMA


def _unlabeled_document() -> tuple[Document, DetectionResult]:
    text = "ООО «Ромашка»: ИНН 7701234567"
    start = text.index("7701234567")
    entity = Entity(
        EntityType.INN, "7701234567", 0, start, start + 10, Source.RULE, 0.9, "7701234567"
    )
    document = Document("test.docx", "docx", [Segment(text, Anchor("docx", ("body", 0)), 0)])
    return document, DetectionResult([entity], [])


def _mixed_document() -> tuple[Document, DetectionResult]:
    texts = [
        'ООО «Поставка», именуемое в дальнейшем "Поставщик", ИНН 7701234567',
        "1. Другой раздел",
        "ООО «Ромашка»: ИНН 7707083893",
    ]
    entities = [
        Entity(
            EntityType.INN,
            "7701234567",
            0,
            texts[0].index("7701234567"),
            texts[0].index("7701234567") + 10,
            Source.RULE,
            0.9,
            "7701234567",
        ),
        Entity(
            EntityType.INN,
            "7707083893",
            2,
            texts[2].index("7707083893"),
            texts[2].index("7707083893") + 10,
            Source.RULE,
            0.9,
            "7707083893",
        ),
    ]
    segments = [
        Segment(text, Anchor("docx", ("body", order)), order) for order, text in enumerate(texts)
    ]
    return Document("test.docx", "docx", segments), DetectionResult(entities, [])


class RecordingProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[list[Message], dict[str, Any] | None]] = []

    def complete(self, messages: list[Message], *, schema: dict[str, Any] | None = None) -> str:
        self.calls.append((messages, schema))
        return self.response


def test_llm_gets_one_document_request_only_for_open_profiles() -> None:
    document, detection = _mixed_document()
    provider = RecordingProvider(
        '{"profiles":[{"id":"P2","members":["E2"],"role_title":"Покупатель","confidence":0.9}]}'
    )

    result = ProfileAgent(provider).profile(document, detection)

    assert result.llm_calls == 1
    assert len(provider.calls) == 1
    messages, schema = provider.calls[0]
    assert schema == ROLE_RESPONSE_SCHEMA
    payload = json.loads(messages[1].content)
    assert [profile["id"] for profile in payload["profiles"]] == ["P2"]
    assert len(payload["segments"]) == 3
    assert [profile.role_title for profile in result.profiles] == ["Поставщик", "Покупатель"]


def test_low_confidence_llm_role_keeps_side_marker() -> None:
    document, detection = _unlabeled_document()
    response = json.dumps(
        {
            "profiles": [
                {
                    "id": "P1",
                    "members": ["E1"],
                    "role_title": "Покупатель",
                    "confidence": MIN_LLM_ROLE_CONFIDENCE - 0.01,
                }
            ]
        }
    )

    profile = ProfileAgent(FakeProvider([response])).profile(document, detection).profiles[0]

    assert profile.role_title == ""
    assert profile.marker_label == "СТОРОНА-1"
    assert profile.source is Source.RULE


@pytest.mark.e2e
def test_live_gigachat_keeps_profile_graph_contract() -> None:
    """Живой провайдер меняется через окружение; ProfileAgent остаётся тем же."""
    if (
        os.environ.get("MASKER_LLM") != "gigachat"
        or not os.environ.get("GIGACHAT_CREDENTIALS")
        or not os.environ.get("MASKER_LLM_MODEL")
    ):
        pytest.skip("нужны MASKER_LLM=gigachat, GIGACHAT_CREDENTIALS и MASKER_LLM_MODEL")
    document, detection = _unlabeled_document()

    result = ProfileAgent(get_provider()).profile(document, detection)

    assert result.llm_calls == 1
    assert len(result.profiles) == 1
