"""Тесты executor'а `regex_llm_filter` (план T1.13, шаг 13)."""

from __future__ import annotations

import json

import pytest

from masker.detect.llm_filter_detector import (
    MAX_LLM_FILTER_CALLS_PER_DOCUMENT,
    LlmFilterDetector,
)
from masker.llm import FakeProvider
from masker.model import Anchor, Document, Segment, Source
from masker.typeconfig import CustomTypeError, load_type_config


def _segment(text: str, order: int = 0) -> Segment:
    return Segment(text=text, anchor=Anchor(fmt="docx", locator=("body", order)), order=order)


def _spec(pattern: str = r"\d{4}") -> object:
    return load_type_config(
        {
            "version": 1,
            "types": [
                {
                    "id": "internal_code",
                    "title": "Внутренний код",
                    "marker": "[КОД-{n}]",
                    "critical": False,
                    "detect": {"kind": "regex_llm_filter", "pattern": pattern},
                }
            ],
        }
    )[0]


def _mask(value: bool) -> str:
    return json.dumps({"mask": value})


def test_typeconfig_accepts_regex_llm_filter_kind() -> None:
    spec = _spec()
    assert spec.kind == "regex_llm_filter"
    assert spec.pattern is not None


def test_positive_verdict_keeps_entity() -> None:
    document = Document(
        path="doc.docx", fmt="docx", segments=[_segment("Договор № 4821 от сего дня.")]
    )
    llm = FakeProvider([_mask(True)])
    detector = LlmFilterDetector([_spec()], llm)

    entities = detector.detect(document)

    assert len(entities) == 1
    assert entities[0].text == "4821"
    assert entities[0].source == Source.LLM
    assert entities[0].type == "internal_code"


def test_negative_verdict_removes_entity() -> None:
    document = Document(
        path="doc.docx", fmt="docx", segments=[_segment("Дом построен в 1975 году.")]
    )
    llm = FakeProvider([_mask(False)])
    detector = LlmFilterDetector([_spec()], llm)

    entities = detector.detect(document)

    assert entities == []


def test_repeated_value_across_segments_calls_llm_once() -> None:
    segments = [_segment(f"Код 4821 упомянут в разделе {i}.", order=i) for i in range(10)]
    document = Document(path="doc.docx", fmt="docx", segments=segments)
    llm = FakeProvider([_mask(True)])
    detector = LlmFilterDetector([_spec()], llm)

    entities = detector.detect(document)

    assert llm.calls == 1
    assert len(entities) == 10  # решение тиражировано на все вхождения
    assert {e.segment_order for e in entities} == set(range(10))


def test_different_values_call_llm_once_each() -> None:
    segments = [_segment("Код 1111."), _segment("Код 2222.", order=1)]
    document = Document(path="doc.docx", fmt="docx", segments=segments)
    llm = FakeProvider([_mask(True), _mask(False)])
    detector = LlmFilterDetector([_spec()], llm)

    entities = detector.detect(document)

    assert llm.calls == 2
    assert len(entities) == 1
    assert entities[0].text == "1111"


def test_same_value_twice_in_one_segment_is_asked_separately_with_description() -> None:
    """Одинаковые даты различаются только положением и русским описанием типа."""
    spec = load_type_config(
        {
            "version": 1,
            "types": [
                {
                    "id": "shipment_date",
                    "title": "Дата отгрузки",
                    "marker": "[ДАТА-ОТГРУЗКИ-{n}]",
                    "detect": {
                        "kind": "regex_llm_filter",
                        "pattern": r"\d{2}\.\d{2}\.\d{4}",
                        "description": "Дата фактической отгрузки товара, не подписания договора.",
                    },
                }
            ],
        }
    )[0]
    document = Document(
        path="doc.docx",
        fmt="docx",
        segments=[_segment("Подписано 12.02.2026, отгрузка 12.02.2026.")],
    )

    class RecordingProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__([_mask(False), _mask(True)])
            self.messages: list[object] = []

        def complete(self, messages: list[object]) -> str:
            self.messages.extend(messages)
            return super().complete(messages)  # type: ignore[arg-type]

    llm = RecordingProvider()
    entities = LlmFilterDetector([spec], llm).detect(document)

    assert llm.calls == 2
    assert [(entity.start, entity.text) for entity in entities] == [(31, "12.02.2026")]
    payloads = [
        json.loads(message.content)
        for message in llm.messages
        if getattr(message, "role", "") == "user"
    ]
    assert all(payload["type_description"].startswith("Дата фактической") for payload in payloads)
    assert payloads[0]["context"] != payloads[1]["context"]


def test_budget_exceeded_raises_with_the_configured_number() -> None:
    count = MAX_LLM_FILTER_CALLS_PER_DOCUMENT + 1
    segments = [_segment(f"Код {1000 + i}.", order=i) for i in range(count)]
    document = Document(path="doc.docx", fmt="docx", segments=segments)
    llm = FakeProvider([_mask(True)] * count)
    detector = LlmFilterDetector([_spec()], llm)

    with pytest.raises(CustomTypeError) as excinfo:
        detector.detect(document)
    assert str(MAX_LLM_FILTER_CALLS_PER_DOCUMENT) in str(excinfo.value)
    assert str(count) in str(excinfo.value)


def test_unparseable_llm_response_defaults_to_masking() -> None:
    """Утечка дороже лишней маски — неразборчивый ответ трактуется как "да"."""
    document = Document(path="doc.docx", fmt="docx", segments=[_segment("Код 9999 указан тут.")])
    llm = FakeProvider(["совсем не json"])
    detector = LlmFilterDetector([_spec()], llm)

    entities = detector.detect(document)

    assert len(entities) == 1


def test_llm_error_defaults_to_masking() -> None:
    class BrokenProvider:
        calls = 0

        def complete(self, messages: list[object]) -> str:
            self.calls += 1
            from masker.llm import LLMError

            raise LLMError("сеть недоступна")

    document = Document(path="doc.docx", fmt="docx", segments=[_segment("Код 5555 указан тут.")])
    detector = LlmFilterDetector([_spec()], BrokenProvider())

    entities = detector.detect(document)

    assert len(entities) == 1


def test_entity_confidence_is_lower_than_plain_regex() -> None:
    from masker.detect.config_detector import REGEX_CONFIDENCE

    document = Document(path="doc.docx", fmt="docx", segments=[_segment("Код 4821 указан тут.")])
    llm = FakeProvider([_mask(True)])
    detector = LlmFilterDetector([_spec()], llm)

    entities = detector.detect(document)

    assert entities[0].confidence < REGEX_CONFIDENCE
