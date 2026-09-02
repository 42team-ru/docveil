"""Границы PERSON: фамилия слева, должность прочь (план T2.2.1, шаг 6, Д4);
защита precision от расширенных границ (шаг 7)."""

from __future__ import annotations

from masker.detect.agent import DetectAgent
from masker.detect.persons import (
    drop_role_prefix,
    expand_person_left,
    single_token_person_is_confirmed,
)
from masker.model import Anchor, Document, EntityType, Segment


def _persons(text: str) -> list[str]:
    document = Document(
        path="x.pdf",
        fmt="pdf",
        segments=[Segment(text=text, anchor=Anchor(fmt="pdf", locator=("page", 0)), order=0)],
    )
    return [
        entity.text
        for entity in DetectAgent().detect(document).entities
        if entity.type is EntityType.PERSON
    ]


def test_person_span_drops_role_prefix() -> None:
    """«Директора Зубрицкой» → «Зубрицкой»: должность внутри спана (Д4)."""
    text = "в лице Директора Зубрицкой действующего на основании Устава"
    start = text.index("Директора")
    end = text.index(" действующего")
    assert drop_role_prefix(text, start, end) == (text.index("Зубрицкой"), end)


def test_drop_role_prefix_returns_none_when_span_is_only_role_words() -> None:
    """Спан целиком из ролевых слов — сущности нет вовсе, не пустая строка."""
    text = "оплата производится Финансовый управляющий подтверждает"
    start = text.index("Финансовый")
    end = text.index(" подтверждает")
    assert drop_role_prefix(text, start, end) is None


def test_person_span_recovers_surname_on_the_left() -> None:
    """Фамилия в родительном падеже слева от спана возвращается на место."""
    text = "директор Мокиной Светланы Владимировны, действующего на основании"
    start = text.index("Светланы")
    end = text.index(", действующего")
    assert expand_person_left(text, start, end) == (text.index("Мокиной"), end)


def test_expand_person_left_does_not_pull_role_word() -> None:
    """Слева от «Зубрицкой» после отсечения стоит «Директора» — его
    обратно подхватывать нельзя, иначе отсечение ролевого префикса
    обесценивается следующим же шагом."""
    text = "в лице Директора Зубрицкой действующего"
    start = text.index("Зубрицкой")
    end = start + len("Зубрицкой")
    assert expand_person_left(text, start, end) == (start, end)


def test_person_span_does_not_cross_punctuation() -> None:
    """Через запятую фамилия не подхватывается — сосед отделён не только пробелом."""
    text = "Романов, Иванов работает по доверенности"
    start = text.index("Иванов")
    end = start + len("Иванов")
    assert expand_person_left(text, start, end) == (start, end)


def test_expand_person_left_skips_street_marker() -> None:
    """«ул. Банникова» — улица, а не фамилия (защита от Д4 наоборот)."""
    text = "проживает по адресу ул. Банникова, д. 2"
    start = text.index("Банникова")
    end = start + len("Банникова")
    assert expand_person_left(text, start, end) == (start, end)


def test_real_pdf_page_1_and_9_recover_full_names() -> None:
    """Регрессия на реальном документе (`contract_pdf_02_school.pdf`)."""
    page_1 = (
        "и Общество с Ограниченной Ответственностью «Школьно-базовая столовая № 11»  , "
        "в лице Директора Зубрицкой Татьяны  Ивановны,  действующего на основании Устава, "
        "с другой стороны."
    )
    persons_1 = _persons(page_1)
    assert "Зубрицкой Татьяны  Ивановны" in persons_1, persons_1

    page_1_customer = (
        "года Муниципальное автономное общеобразовательное учреждение гимназия № 144, "
        "в лице директора  Мокиной Светланы Владимировны, действующего на основании Устава, "
        "с одной стороны."
    )
    persons_customer = _persons(page_1_customer)
    assert "Мокиной Светланы Владимировны" in persons_customer, persons_customer

    page_9 = (
        "взаимодействия с Заказчиком при исполнении настоящего договора является "
        "директор Зубрицкая Татьяна Ивановна, тел. +7 (343) 360-62-28."
    )
    persons_9 = _persons(page_9)
    assert "Зубрицкая Татьяна Ивановна" in persons_9, persons_9


# ---------------------------------------------------------------------------
# Защита precision от расширенных границ (план T2.2.1, шаг 7).
# ---------------------------------------------------------------------------


def test_single_token_person_needs_evidence() -> None:
    """Однотокенный PER без независимого подтверждения не выпускается —
    ровно то, что убирает `Мармит`, `Суп`, `Амортизац`, `Корректировочных`
    (расширенные границы шага 6 сделали бы такие ложные срабатывания шире,
    а не реже, без этой защиты)."""
    assert not single_token_person_is_confirmed("Суп", "Выдать: Суп.", 8, frozenset())
    assert not single_token_person_is_confirmed(
        "Амортизация", "Начислена Амортизация за март.", 10, frozenset()
    )


def test_single_token_person_confirmed_by_full_mention() -> None:
    """Та же фамилия уже встречается с именем в другом месте документа."""
    confirmed = frozenset({"мокин", "светлан", "владимировн"})
    assert single_token_person_is_confirmed("Мокина", "вернула Мокина.", 8, confirmed)


def test_single_token_person_confirmed_by_trigger() -> None:
    """Триггер («директор», «в лице», ...) достаточен и без повторного упоминания."""
    text = "документ подписал директор Смирнов."
    start = text.index("Смирнов")
    assert single_token_person_is_confirmed("Смирнов", text, start, frozenset())


def test_single_token_person_ignores_multi_token_span() -> None:
    """Проверка применяется только к однотокенным спанам."""
    assert single_token_person_is_confirmed("Иван Иванов", "текст Иван Иванов", 6, frozenset())


def test_person_inside_address_is_dropped() -> None:
    """PER сразу за адресным маркером не выпускается — «Банникова» улица,
    не фамилия (Д4 наоборот)."""
    text = "проживает по адресу: ул. Банникова, д. 2."
    assert "Банникова" not in _persons(text)


def test_role_phrase_is_not_an_organization() -> None:
    """ORG без кавычек и без оргформы, но с ролевым токеном — не организация."""
    from masker.detect.orgforms import is_role_phrase

    for phrase in (
        "Заказчика информации",
        "Исполнителем услуг",
        "Объект Арендодателю",
        "Заказчик направляет Исполнителю",
    ):
        assert is_role_phrase(phrase), phrase
    # С кавычками или формой — это уже организация, ролевой токен не решает.
    assert not is_role_phrase("ООО «Поставщик Плюс»")
