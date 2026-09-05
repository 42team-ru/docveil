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


def test_empty_template_is_not_a_date() -> None:
    """Незаполненный шаблон подписи датой не считается — цифр года нет."""
    assert _detect("«____» __________ 202__ года") == []


def test_quoted_day_span_includes_quotes() -> None:
    """Кавычки вокруг дня входят в спан — иначе останется висящая `»`."""
    entities = DateDetector().detect(_document("«12» февраля 2025 г."))
    assert entities[0].text == "«12» февраля 2025"


def test_trailing_year_word_is_not_in_span() -> None:
    """«года»/«г.» после года — в спан не входят: маскируется значение,
    а не хвост предложения."""
    entities = DateDetector().detect(_document("Утверждено 10 марта 2025 года."))
    assert entities[0].text == "10 марта 2025"


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
