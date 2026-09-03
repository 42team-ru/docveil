"""Тесты live preview пользовательского типа (план T1.13, шаг 10)."""

from __future__ import annotations

from typing import Any

from masker.customtypes.preview import DEFAULT_SEGMENT_LIMIT, preview
from masker.detect.gliner import GlinerDetector
from masker.model import Anchor, Document, Segment
from masker.typeconfig import load_type_config


def _segment(order: int, text: str) -> Segment:
    return Segment(text, Anchor("docx", ("body", order), f"абзац {order}"), order)


def _document(*texts: str) -> Document:
    return Document(
        path="doc.docx", fmt="docx", segments=[_segment(i, t) for i, t in enumerate(texts)]
    )


def _shipment_date_spec() -> Any:
    return load_type_config(
        {
            "version": 1,
            "types": [
                {
                    "id": "shipment_date",
                    "title": "Дата отгрузки",
                    "marker": "[ДАТА-ОТГРУЗКИ-{n}]",
                    "critical": False,
                    "detect": {
                        "kind": "regex",
                        "pattern": r"\d{2}\.\d{2}\.\d{4}",
                        "context": ["отгрузк"],
                    },
                }
            ],
        }
    )[0]


def _product_code_spec() -> Any:
    return load_type_config(
        {
            "version": 1,
            "types": [
                {
                    "id": "product_code",
                    "title": "Код товара",
                    "marker": "[КОД-{n}]",
                    "critical": True,
                    "detect": {"kind": "literals", "values": ["SKU-42"]},
                }
            ],
        }
    )[0]


def test_preview_finds_matches_in_first_segments_by_order() -> None:
    document = _document(
        "Преамбула договора без дат.",
        "Дата отгрузки товара — 01.02.2026.",
        "Оплата производится в течение 10 дней после отгрузки 05.03.2026.",
    )
    result = preview(_shipment_date_spec(), document)

    assert result.total_matches == 2
    assert [segment.segment_order for segment in result.segments] == [1, 2]


def test_preview_matches_offsets_point_into_returned_text() -> None:
    """Смещения preview считаны от документа, а не выдуманы поверх окна."""
    document = _document("Дата отгрузки товара 01.02.2026 согласно договору.")
    result = preview(_shipment_date_spec(), document)

    segment = result.segments[0]
    assert len(segment.matches) == 1
    match = segment.matches[0]
    assert segment.text[match.start : match.end] == match.value == "01.02.2026"


def test_preview_zero_matches_returns_first_segments_and_zero_total() -> None:
    document = _document("Первый абзац.", "Второй абзац.", "Третий абзац.", "Четвёртый абзац.")
    result = preview(_product_code_spec(), document)

    assert result.total_matches == 0
    assert [segment.matches for segment in result.segments] == [[], [], []]
    assert [segment.segment_order for segment in result.segments] == [0, 1, 2]


def test_preview_zero_matches_skips_empty_segments() -> None:
    document = _document("", "   ", "Единственный непустой абзац без совпадений.")
    result = preview(_product_code_spec(), document)

    assert result.total_matches == 0
    assert [segment.segment_order for segment in result.segments] == [2]


def test_preview_is_deterministic_across_repeated_calls() -> None:
    document = _document(
        "SKU-42 указан здесь.",
        "И снова SKU-42 в другом месте.",
        "Третий абзац без кода.",
        "SKU-42 в четвёртом абзаце тоже.",
    )
    spec = _product_code_spec()
    first = preview(spec, document)
    second = preview(spec, document)

    assert first == second


def test_preview_respects_segment_limit() -> None:
    texts = [f"SKU-42 в абзаце {i}." for i in range(10)]
    document = _document(*texts)
    result = preview(_product_code_spec(), document, limit=2)

    assert len(result.segments) == 2
    assert result.total_matches == 10


def test_preview_default_limit_is_three() -> None:
    assert DEFAULT_SEGMENT_LIMIT == 3


def test_preview_window_is_bounded_around_match_not_whole_segment() -> None:
    long_prefix = "текст " * 100
    document = _document(f"{long_prefix}дата отгрузки 01.02.2026 согласно графику.")
    result = preview(_shipment_date_spec(), document)

    segment = result.segments[0]
    assert len(segment.text) < len(document.segments[0].text)
    match = segment.matches[0]
    assert segment.text[match.start : match.end] == "01.02.2026"


def test_preview_dispatches_gliner_kind_via_injected_model() -> None:
    """Диспетчер preview.py умеет и gliner_*-исполнители (модель подставляется явно)."""

    class FakeGliner:
        def extract_entities(self, text: str, labels: Any, **kwargs: Any) -> dict[str, Any]:
            start = text.find("инженер")
            return {
                "entities": {
                    "должность": [
                        {
                            "text": "инженер",
                            "start": start,
                            "end": start + len("инженер"),
                            "confidence": 0.9,
                        }
                    ]
                }
            }

    spec = load_type_config(
        {
            "version": 1,
            "types": [
                {
                    "id": "job_title",
                    "title": "Должность",
                    "marker": "[ДОЛЖНОСТЬ-{n}]",
                    "detect": {
                        "kind": "gliner_label",
                        "label": "должность",
                        "description": "Название должности",
                    },
                }
            ],
        }
    )[0]
    document = _document("Главный инженер подписал договор.")

    import masker.detect.gliner as gliner_module

    original_detector = gliner_module.GlinerDetector

    def _patched(specs: Any, model: Any = None) -> GlinerDetector:
        return original_detector(specs, model=FakeGliner())

    gliner_module.GlinerDetector = _patched  # type: ignore[assignment]
    try:
        result = preview(spec, document)
    finally:
        gliner_module.GlinerDetector = original_detector

    assert result.total_matches == 1
    assert result.segments[0].matches[0].value == "инженер"
