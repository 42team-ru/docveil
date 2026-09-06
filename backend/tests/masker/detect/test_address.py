from __future__ import annotations

from pathlib import Path

import pytest

from masker.detect import DetectAgent, RuleDetector
from masker.detect.address import AddressDetector, address_markers
from masker.detect.ner import NatashaDetector, NerSpan, memoize_tagger
from masker.ingest.docx_ingest import ingest_docx
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


def _split_cell_document() -> Document:
    return Document(
        path="test.docx",
        fmt="docx",
        segments=[
            Segment(
                text="адрес регистрации по месту жительства:",
                anchor=Anchor("docx", ("table", 0, 0, 0, 0)),
                order=0,
            ),
            Segment(
                text="309512, Белгородская область, г. Старый Оскол,",
                anchor=Anchor("docx", ("table", 0, 0, 0, 1)),
                order=1,
            ),
            Segment(
                text="мкр. Жукова, д. 20, кв. 15",
                anchor=Anchor("docx", ("table", 0, 0, 0, 2)),
                order=2,
            ),
        ],
    )


def test_address_split_across_cell_paragraphs_yields_two_spans() -> None:
    result = DetectAgent([AddressDetector()]).detect(_split_cell_document())

    assert [(entity.segment_order, entity.text) for entity in result.entities] == [
        (1, "309512, Белгородская область, г. Старый Оскол"),
        (2, "мкр. Жукова, д. 20, кв. 15"),
    ]


def test_trailing_comma_is_not_in_span() -> None:
    result = DetectAgent([AddressDetector()]).detect(_split_cell_document())

    assert result.entities[0].text.endswith("Оскол")
    assert not result.entities[0].text.endswith(",")


def test_address_split_across_cell_paragraphs_shares_normalized_key() -> None:
    """Один адрес, разорванный границей абзаца ячейки, должен склеиться в один ключ."""
    result = DetectAgent([AddressDetector()]).detect(_split_cell_document())

    assert len(result.entities) == 2
    assert result.entities[0].normalized == result.entities[1].normalized
    assert result.entities[0].normalized == (
        "309512, белгородская область, г. старый оскол мкр. жукова, д. 20, кв. 15"
    )


def _unrelated_addresses_document() -> Document:
    return Document(
        path="test.docx",
        fmt="docx",
        segments=[
            Segment(
                text="г. Воронеж, ул. Мира, 12",
                anchor=Anchor("docx", ("table", 0, 0, 0, 0)),
                order=0,
            ),
            Segment(
                text="394024, Воронежская область, г Воронеж, пер Здоровья, д 86а, кв 95",
                anchor=Anchor("docx", ("table", 0, 0, 0, 1)),
                order=1,
            ),
        ],
    )


def test_unrelated_addresses_in_neighboring_paragraphs_keep_different_keys() -> None:
    result = DetectAgent([AddressDetector()]).detect(_unrelated_addresses_document())

    assert len(result.entities) == 2
    assert result.entities[0].normalized != result.entities[1].normalized


def test_partial_address_requires_value_label() -> None:
    assert [(entity.text, entity.confidence) for entity in _detect("Адрес: г. Воронеж")] == [
        ("г. Воронеж", 0.5)
    ]
    assert _detect("Определение вынес Арбитражный суд г. Воронежа") == []


def test_partial_address_confidence_is_below_full() -> None:
    partial = _detect("Адрес: г. Воронеж")[0]
    full = _detect("Адрес: г. Воронеж, ул. Мира, 12")[0]

    assert partial.confidence == 0.5
    assert full.confidence == 0.9
    assert partial.confidence < full.confidence


def test_birth_place_is_not_emitted_as_address() -> None:
    assert _detect("место рождения: гор. Старый Оскол Белгородской обл.") == []


def test_label_in_previous_paragraph_of_the_same_cell() -> None:
    document = Document(
        path="test.docx",
        fmt="docx",
        segments=[
            Segment(
                text="адрес регистрации по месту жительства:",
                anchor=Anchor("docx", ("table", 0, 0, 0, 0)),
                order=0,
            ),
            Segment(
                text="г. Воронеж",
                anchor=Anchor("docx", ("table", 0, 0, 0, 1)),
                order=1,
            ),
            Segment(
                text="Адрес:",
                anchor=Anchor("docx", ("table", 0, 0, 1, 0)),
                order=2,
            ),
            Segment(
                text="г. Воронеж",
                anchor=Anchor("docx", ("table", 0, 0, 0, 2)),
                order=3,
            ),
        ],
    )

    entities = AddressDetector().detect(document)

    # Пропагация: «г. Воронеж» обнаружено в сег 1 через метку «Адрес:» из сег 2,
    # затем _propagate_to_occurrences добавляет непокрытое вхождение в сег 3.
    assert [(entity.segment_order, entity.text) for entity in entities] == [
        (1, "г. Воронеж"),
        (3, "г. Воронеж"),
    ]


@pytest.mark.parametrize(
    "suffix",
    [
        "ИНН 3662103003",
        "телефон +7 (473) 250-10-10",
        "р/с 40702810100000000002",
    ],
)
def test_address_stops_before_requisites(suffix: str) -> None:
    text = f"Адрес: 394018, г. Воронеж, ул. Кирова, д. 4, {suffix}"

    address = _detect(text)[0]

    assert address.text == "394018, г. Воронеж, ул. Кирова, д. 4"
    assert suffix not in address.text


def test_address_and_rule_entity_both_survive_in_agent() -> None:
    text = "Адрес: 394018, г. Воронеж, ул. Кирова, д. 4, ИНН 3662103003"
    document = Document(
        path="test.docx",
        fmt="docx",
        segments=[Segment(text=text, anchor=Anchor("docx", ("body", 0)), order=0)],
    )

    entities = DetectAgent([RuleDetector(), AddressDetector()]).detect(document).entities

    assert [(entity.type.value, entity.text) for entity in entities] == [
        ("address", "394018, г. Воронеж, ул. Кирова, д. 4"),
        ("inn", "3662103003"),
    ]


class _MeasuredAddressTagger:
    def spans(self, text: str) -> list[NerSpan]:
        assert text == ("309512, Белгородская область, г. Старый Оскол, мкр. Жукова, д. 20, кв. 15")
        return [
            NerSpan(8, 30, "LOC"),
            NerSpan(34, 46, "LOC"),
            NerSpan(52, 58, "PER"),
        ]


def _zhukova_document() -> Document:
    text = "309512, Белгородская область, г. Старый Оскол, мкр. Жукова, д. 20, кв. 15"
    return Document(
        path="test.docx",
        fmt="docx",
        segments=[Segment(text=text, anchor=Anchor("docx", ("body", 0)), order=0)],
    )


def test_address_absorbs_false_person_span() -> None:
    tagger = _MeasuredAddressTagger()
    entities = (
        DetectAgent([AddressDetector(), NatashaDetector(tagger)])
        .detect(_zhukova_document())
        .entities
    )

    assert [(entity.type.value, entity.text) for entity in entities] == [
        (
            "address",
            "309512, Белгородская область, г. Старый Оскол, мкр. Жукова, д. 20, кв. 15",
        )
    ]


@pytest.mark.models
def test_address_absorbs_false_person_span_real_model() -> None:
    entities = DetectAgent().detect(_zhukova_document()).entities

    assert [entity.type.value for entity in entities] == ["address"]


def test_loc_signal_raises_partial_confidence() -> None:
    class LocationTagger:
        def spans(self, text: str) -> list[NerSpan]:
            assert text == "Адрес: г. Воронеж"
            return [NerSpan(10, 17, "LOC")]

    entities = AddressDetector(LocationTagger()).detect(
        Document(
            path="test.docx",
            fmt="docx",
            segments=[
                Segment(
                    text="Адрес: г. Воронеж",
                    anchor=Anchor("docx", ("body", 0)),
                    order=0,
                )
            ],
        )
    )

    assert entities[0].confidence == 0.7


def test_tagger_is_called_once_per_segment() -> None:
    class CountingTagger:
        def __init__(self) -> None:
            self.calls = 0

        def spans(self, text: str) -> list[NerSpan]:
            self.calls += 1
            return []

    raw_tagger = CountingTagger()
    tagger = memoize_tagger(raw_tagger)
    document = Document(
        path="test.docx",
        fmt="docx",
        segments=[
            Segment("Адрес: г. Воронеж", Anchor("docx", ("body", 0)), 0),
            Segment("Сидорова Анна Петровна", Anchor("docx", ("body", 1)), 1),
        ],
    )

    DetectAgent([AddressDetector(tagger), NatashaDetector(tagger)]).detect(document)

    assert raw_tagger.calls == len(document.segments)


@pytest.mark.models
def test_body_address_ends_before_signatory() -> None:
    fixture = Path(__file__).resolve().parents[3] / "fixtures/labeled/contract_06_address.docx"
    document = ingest_docx(fixture)
    segment = next(segment for segment in document.segments if "312822458000" in segment.text)

    entities = [
        entity
        for entity in DetectAgent().detect(document).entities
        if entity.segment_order == segment.order and entity.type.value in {"address", "person"}
    ]

    assert [(entity.type.value, entity.text) for entity in entities] == [
        (
            "address",
            "394024, Воронежская область, г Воронеж, пер Здоровья, д 86а, кв 95",
        ),
        ("person", "Атараев Б.М"),
    ]


def test_index_like_number_past_hard_boundary_does_not_crash() -> None:
    """Регрессия, найденная на реальном PDF-блоке (план T2.2.1, шаг 8):

    номер договора «2025.334807» после открывающей кавычки содержит
    случайный шестизначный кусок «334807», похожий на почтовый индекс, но
    расположенный дальше «жёсткой» границы (кавычки). Раньше `value_start`
    уезжал за эту границу, а `_component_end` — нет, и чанк получал
    `end < start`, что ронял `DetectAgent._validate` с «invalid entity span».
    """
    text = 'Документ подписан на ЭП "РТС-тендер" Договор №2025.334807 Страница 5 из 44 '
    assert _detect(text) == []


def test_number_after_decimal_point_is_not_a_postal_index() -> None:
    """Тот же ложный «индекс» без кавычки рядом (план T2.2.1, шаг 9):

    найден при рендере реального PDF — узкий прямоугольник ложного
    «адреса» из шести цифр номера договора уронил вставку маркера
    (`insert_textbox` не смог вписать `[СТОРОНА-1-АДРЕС]` в ширину «334807»).
    """
    text = "Договор № 2025.334807 на оказание услуг по организации питания"
    assert _detect(text) == []
