"""Тесты `DateDetector` (план T1.15, шаги 2–4)."""

from __future__ import annotations

import pytest

from masker.detect.dates import DateDetector
from masker.detect.normalize import normalize_value
from masker.model import CRITICAL_TYPES, Anchor, Document, EntityType, Segment, Source


def _document(text: str) -> Document:
    return Document(
        path="doc.docx",
        fmt="docx",
        segments=[Segment(text=text, anchor=Anchor(fmt="docx", locator=("body", 0)), order=0)],
    )


def _detect(text: str) -> list[tuple[str, str]]:
    entities = DateDetector().detect(_document(text))
    return [(entity.type, entity.text) for entity in entities]


def test_finds_numeric_and_textual_dates() -> None:
    assert _detect("Договор от 14.10.1986.") == [(EntityType.DATE.value, "14.10.1986")]
    assert _detect("Дата подписания 12/02/2025 г.") == [(EntityType.DATE.value, "12/02/2025")]
    assert _detect("Отчёт от 2025-02-12 подан.") == [(EntityType.DATE.value, "2025-02-12")]
    assert _detect("Утверждено 10 марта 2025 года.") == [(EntityType.DATE.value, "10 марта 2025")]
    assert _detect("«12» февраля 2025 г.") == [(EntityType.DATE.value, "«12» февраля 2025")]
    assert _detect("« 7 » февраля 2024 г.") == [(EntityType.DATE.value, "« 7 » февраля 2024")]


def test_empty_template_is_not_a_date() -> None:
    """Незаполненный шаблон подписи датой не считается — цифр года нет."""
    assert _detect("«____» __________ 202__ года") == []


def test_quoted_day_span_includes_quotes() -> None:
    """Кавычки вокруг дня входят в спан — иначе останется висящая `»`."""
    entities = DateDetector().detect(_document("«12» февраля 2025 г."))
    assert entities[0].text == "«12» февраля 2025"


def test_spaced_quoted_day_in_contract_header_is_detected() -> None:
    """Р26: дата договора в « 7 » февраля 2024 не остаётся открытой."""
    assert _detect("г. Москва « 7 » февраля 2024 г.") == [
        (EntityType.DATE.value, "« 7 » февраля 2024")
    ]
    assert normalize_value(EntityType.DATE, "« 7 » февраля 2024") == "2024-02-07"


def test_trailing_year_word_is_not_in_span() -> None:
    """«года»/«г.» после года — в спан не входят: маскируется значение,
    а не хвост предложения."""
    entities = DateDetector().detect(_document("Утверждено 10 марта 2025 года."))
    assert entities[0].text == "10 марта 2025"


@pytest.mark.parametrize(
    "text",
    (
        "В соответствии с Федеральным законом от 27 июля 2006 года № 149-ФЗ.",
        "Требованиям Федерального закона от 06.04.2011 № 63-ФЗ соответствуют.",
        "Федеральный закон Российской Федерации от 27 июля 2006г. № 149-ФЗ.",
    ),
)
def test_adoption_date_in_federal_law_reference_is_not_pii(text: str) -> None:
    """Р19: дата в конструкции «федеральный закон от <дата>» публична."""
    assert _detect(text) == []


@pytest.mark.parametrize(
    "text",
    (
        "утверждённой постановлением Правительства Российской Федерации от 15 апреля 2014 г. № 313",
        "на основании пункта 2 части 1 статьи 93 Федерального закона от 5 апреля 2013 г. № 44-ФЗ",
        "и распоряжения Правительства Российской Федерации от 23 января 2024 г. № 121-р",
        "согласно приказу Министерства от 10.05.2024 № 14",
    ),
)
def test_adoption_date_in_any_normative_act_is_not_pii(text: str) -> None:
    """Р26: публичные дата, номер и вид акта не идентифицируют сторону."""
    assert _detect(text) == []


@pytest.mark.parametrize(
    ("text", "value"),
    (
        ("Федеральным законом установлено правило. Договор подписан 14.10.2025.", "14.10.2025"),
        ("Срок поставки товара: 15.11.2025.", "15.11.2025"),
        ("Оплата производится не позднее 16.12.2025.", "16.12.2025"),
    ),
)
def test_contract_dates_are_still_detected(text: str, value: str) -> None:
    """Иммунитет касается только даты непосредственно после ссылки на закон."""
    assert _detect(text) == [(EntityType.DATE.value, value)]


def test_two_digit_year_is_not_detected() -> None:
    """Двузначный год не ловим (план, «Не ловим»): коллизий с накладными много."""
    assert _detect("Оплата 12.02.25.") == []


def test_date_span_matches_segment_text() -> None:
    """Иначе ``DetectAgent._validate`` бросит ``ValueError``."""
    document = _document("От 14.10.1986 до 12.02.2025.")
    for entity in DateDetector().detect(document):
        segment = document.segments[entity.segment_order]
        assert segment.text[entity.start : entity.end] == entity.text


def test_birth_trigger_on_the_right_gives_birth_date() -> None:
    assert _detect("Сидоровой Анны, 15 февраля 1982 года рождения.") == [
        (EntityType.BIRTH_DATE.value, "15 февраля 1982")
    ]
    assert _detect("Иванова И.И., 14.10.1986 г.р.") == [(EntityType.BIRTH_DATE.value, "14.10.1986")]


def test_birth_trigger_on_the_left_gives_birth_date() -> None:
    for text in (
        "дата рождения: 14.10.1986 г.",
        "род. 14.10.1986,",
        "Год рождения: 14.10.1986.",
    ):
        types = {t for t, _ in _detect(text)}
        assert EntityType.BIRTH_DATE.value in types, text


def test_word_rozhdenie_far_away_stays_plain_date() -> None:
    """«свидетельство о рождении выдано …» не превращает дату договора в birth_date."""
    text = "Договор от 10 марта 2025 г., свидетельство о рождении выдано ранее."
    entities = DateDetector().detect(_document(text))
    types = {entity.type for entity in entities}
    assert EntityType.BIRTH_DATE.value not in types
    assert EntityType.DATE.value in types


def test_date_and_birth_date_are_not_critical() -> None:
    """Тест-сторож: `date` и `birth_date` не должны попасть в `CRITICAL_TYPES`.

    Инвариант «судья не спрашивает про критичное» превратил бы срок оплаты
    в молчаливый маркер и сломал бы читаемость договора (план T1.15,
    раздел «Граница»).
    """
    assert EntityType.DATE not in CRITICAL_TYPES
    assert EntityType.BIRTH_DATE not in CRITICAL_TYPES


def test_date_normalizes_to_iso() -> None:
    """`14.10.1986` и `14 октября 1986` дают один ISO-ключ."""
    assert normalize_value(EntityType.DATE, "14.10.1986") == "1986-10-14"
    assert normalize_value(EntityType.DATE, "14 октября 1986") == "1986-10-14"
    assert normalize_value(EntityType.BIRTH_DATE, "14.10.1986") == "1986-10-14"
    # Неразобранный литерал — детерминированный fallback, не падение.
    assert normalize_value(EntityType.DATE, "какой-то текст") != ""


def test_source_and_confidence() -> None:
    entity = DateDetector().detect(_document("Договор от 14.10.1986."))[0]
    assert entity.source is Source.RULE
    assert entity.confidence == pytest.approx(0.9)


def test_date_does_not_collide_with_passport_or_snils() -> None:
    """Паспорт и СНИЛС не должны быть съедены датой (разделители-точки)."""
    text = "Паспорт 20 04 123456, выдан 10.05.2018."
    entities = DateDetector().detect(_document(text))
    assert [entity.text for entity in entities] == ["10.05.2018"]


def test_multiple_dates_in_segment_are_all_found() -> None:
    text = "От 14.10.1986 до 12.02.2025 согласно 10 марта 2025 г."
    entities = DateDetector().detect(_document(text))
    assert [entity.text for entity in entities] == [
        "14.10.1986",
        "12.02.2025",
        "10 марта 2025",
    ]


def test_types_frozenset_covers_both_kinds() -> None:
    """`types` — паспорт детектора: обязан содержать оба типа, иначе
    `resolve_requested_types` не даст маскировать соответствующий тип."""
    assert DateDetector().types == frozenset({EntityType.DATE.value, EntityType.BIRTH_DATE.value})
