from __future__ import annotations

import pytest

from masker.detect.address import AddressDetector, address_markers
from masker.model import Anchor, Document, Segment


def _detect(text: str):
    document = Document(
        path="test.docx",
        fmt="docx",
        segments=[Segment(text=text, anchor=Anchor("docx", ("body", 0)), order=0)],
    )
    return AddressDetector().detect(document)


def test_address_markers_are_sorted_and_cached() -> None:
    address_markers.cache_clear()

    markers = address_markers()

    assert markers is address_markers()
    assert len(markers.street) > 10
    assert markers.street == tuple(
        sorted(markers.street, key=lambda value: (-len(value), value.casefold()))
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "Адрес: 394018, г. Воронеж, ул. Кирова, д. 4, оф. 12",
            "394018, г. Воронеж, ул. Кирова, д. 4, оф. 12",
        ),
        (
            "394024, Воронежская область, г Воронеж, пер Здоровья, д 86а, кв 95",
            "394024, Воронежская область, г Воронеж, пер Здоровья, д 86а, кв 95",
        ),
        (
            "309512, Белгородская область, г. Старый Оскол, мкр. Жукова, д. 20, кв. 15",
            "309512, Белгородская область, г. Старый Оскол, мкр. Жукова, д. 20, кв. 15",
        ),
    ],
)
def test_full_address_with_index_is_one_span(text: str, expected: str) -> None:
    entities = _detect(text)

    assert [(entity.text, entity.confidence) for entity in entities] == [(expected, 0.9)]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("г. Воронеж, ул. Мира, 12", "г. Воронеж, ул. Мира, 12"),
        (
            "Воронежская обл., Новоусманский р-н, с. Отрадное, ул. Мира, 12",
            "Воронежская обл., Новоусманский р-н, с. Отрадное, ул. Мира, 12",
        ),
    ],
)
def test_address_without_index_and_without_street_marker(text: str, expected: str) -> None:
    assert [entity.text for entity in _detect(text)] == [expected]


def test_city_in_preamble_is_not_an_address() -> None:
    assert _detect("г. Воронеж, 15 января 2026 г.") == []


def test_address_span_matches_segment_text() -> None:
    text = "Адрес: 394018, г. Воронеж, ул. Кирова, д. 4, оф. 12"

    for entity in _detect(text):
        assert entity.text == text[entity.start : entity.end]
