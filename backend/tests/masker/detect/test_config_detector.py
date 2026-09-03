"""Тесты ConfigDetector: литералы, регулярки, бюджет времени (шаг 5 T1.13)."""

from __future__ import annotations

from typing import Any

import pytest

from masker.detect import config_detector as config_detector_module
from masker.detect.agent import DetectAgent
from masker.detect.config_detector import ConfigDetector
from masker.entity_types import EntityTypeRegistry
from masker.model import Anchor, Document, Segment, Source
from masker.typeconfig import CustomTypeError, load_type_config


def _segment(text: str, order: int = 0) -> Segment:
    return Segment(text=text, anchor=Anchor(fmt="docx", locator=("body", order)), order=order)


def _document(*segments: Segment) -> Document:
    return Document(path="document.docx", fmt="docx", segments=list(segments))


def _literal_config(
    values: list[str], match: str = "whole_word", type_id: str = "internal_secret"
) -> dict[str, Any]:
    return {
        "version": 1,
        "types": [
            {
                "id": type_id,
                "title": "Скрыть по списку",
                "marker": "[СКРЫТО-{n}]",
                "detect": {"kind": "literals", "values": values, "match": match},
            }
        ],
    }


def _regex_config(
    pattern: str, context: list[str] | None = None, type_id: str = "shipment_date"
) -> dict[str, Any]:
    detect: dict[str, Any] = {"kind": "regex", "pattern": pattern, "ignorecase": False}
    if context is not None:
        detect["context"] = context
    return {
        "version": 1,
        "types": [
            {
                "id": type_id,
                "title": "Дата отгрузки",
                "marker": "[ДАТА-ОТГРУЗКИ-{n}]",
                "detect": detect,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Контракт EntityDetector
# ---------------------------------------------------------------------------


def test_class_attributes() -> None:
    assert ConfigDetector.name == "config"
    assert ConfigDetector.source is Source.USER
    assert ConfigDetector.priority == 95


def test_types_property_reflects_specs() -> None:
    specs = load_type_config(_literal_config(["Заря"]))
    detector = ConfigDetector(specs)
    assert detector.types == {"internal_secret"}


# ---------------------------------------------------------------------------
# Литералы
# ---------------------------------------------------------------------------


def test_literal_found_once_and_whole() -> None:
    specs = load_type_config(_literal_config(["Проект «Заря»"]))
    detector = ConfigDetector(specs)
    text = "Проект «Заря» стартовал в январе, отчёт по проекту «Заря» готов позже."
    document = _document(_segment(text))

    entities = detector.detect(document)

    matches = [e for e in entities if e.text == "Проект «Заря»"]
    assert len(matches) == 1
    entity = matches[0]
    assert entity.type == "internal_secret"
    assert entity.source is Source.USER
    assert entity.confidence == 1.0
    assert text[entity.start : entity.end] == "Проект «Заря»"


def test_literal_whole_word_does_not_match_inside_longer_word() -> None:
    specs = load_type_config(_literal_config(["Заря"]))
    detector = ConfigDetector(specs)
    text = "Заря напоминает о весне. Зарядное устройство лежит в ящике."
    document = _document(_segment(text))

    entities = detector.detect(document)

    assert len(entities) == 1
    assert entities[0].text == "Заря"
    assert entities[0].start == 0
    assert entities[0].end == 4


def test_literal_substring_mode_matches_inside_longer_word() -> None:
    specs = load_type_config(_literal_config(["Заря"], match="substring"))
    detector = ConfigDetector(specs)
    text = "Зарядное устройство."
    document = _document(_segment(text))

    entities = detector.detect(document)

    assert len(entities) == 1
    assert entities[0].text == "Заря"


# ---------------------------------------------------------------------------
# Регулярки и context
# ---------------------------------------------------------------------------


def test_context_required_within_window() -> None:
    specs = load_type_config(_regex_config(r"\d{2}\.\d{2}\.\d{4}", context=["отгрузк", "поставк"]))
    detector = ConfigDetector(specs)
    with_context = _segment("Отгрузка товара состоится 12.02.2026 согласно графику.", order=0)
    without_context = _segment("Оплата произведена, дата операции 12.02.2026.", order=1)
    document = _document(with_context, without_context)

    entities = detector.detect(document)

    assert len(entities) == 1
    assert entities[0].segment_order == 0
    assert entities[0].text == "12.02.2026"
    assert entities[0].confidence == 0.9


def test_regex_without_context_field_matches_everywhere() -> None:
    specs = load_type_config(_regex_config(r"№\s?\d+/\d{4}", type_id="contract_no"))
    detector = ConfigDetector(specs)
    document = _document(_segment("Договор № 44/2026 заключён сторонами."))

    entities = detector.detect(document)

    assert len(entities) == 1
    assert entities[0].text == "№ 44/2026"
    assert entities[0].type == "contract_no"


# ---------------------------------------------------------------------------
# Совместимость с DetectAgent._validate
# ---------------------------------------------------------------------------


def test_entities_pass_detect_agent_validate() -> None:
    literal_specs = load_type_config(_literal_config(["Проект «Заря»"]))
    regex_specs = load_type_config(_regex_config(r"\d{2}\.\d{2}\.\d{4}", context=["отгрузк"]))
    specs = [*literal_specs, *regex_specs]
    detector = ConfigDetector(specs)
    registry = EntityTypeRegistry.builtin().extend(custom.spec for custom in specs)
    document = _document(
        _segment("Проект «Заря» отгрузка состоится 12.02.2026 согласно графику отгрузки.")
    )
    agent = DetectAgent(detectors=[detector], registry=registry)

    entities = detector.detect(document)
    agent._validate(detector, document, entities)  # не должно бросить

    for entity in entities:
        assert entity.type in registry
        assert entity.text == document.segments[0].text[entity.start : entity.end]


# ---------------------------------------------------------------------------
# Детерминизм
# ---------------------------------------------------------------------------


def test_two_runs_identical() -> None:
    specs = load_type_config(_literal_config(["внутренний код 42", "Проект «Заря»"]))
    detector = ConfigDetector(specs)
    document = _document(_segment("Проект «Заря» использует внутренний код 42 для отчётности."))

    first = detector.detect(document)
    second = detector.detect(document)

    assert first == second


# ---------------------------------------------------------------------------
# Бюджет времени
# ---------------------------------------------------------------------------


def test_regex_budget_exceeded_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    specs = load_type_config(_regex_config(r"\d{2}\.\d{2}\.\d{4}"))
    detector = ConfigDetector(specs)
    document = _document(_segment("Дата 12.02.2026."))

    values = iter([0.0, config_detector_module.CUSTOM_REGEX_BUDGET_S + 1.0])
    monkeypatch.setattr(config_detector_module, "perf_counter", lambda: next(values))

    with pytest.raises(CustomTypeError, match="бюджет"):
        detector.detect(document)
