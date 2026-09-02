"""Тесты `OrgFormDetector` — словарный детектор организаций по оргформе
(Д11, план T2.2.2, шаг 6): Natasha на этих строках не отдаёт спана вовсе,
расширять нечего — нужен отдельный детектор."""

from __future__ import annotations

from masker.detect.org_rules import OrgFormDetector
from masker.model import Anchor, Document, Segment


def _detect(text: str) -> list:  # type: ignore[type-arg]
    document = Document(
        path="test.pdf",
        fmt="pdf",
        segments=[Segment(text=text, anchor=Anchor("pdf", ("page", 0, 0, len(text))), order=0)],
    )
    return OrgFormDetector().detect(document)


def test_org_form_without_quotes_takes_name() -> None:
    """Оргформа без кавычек — «Муниципальное автономное общеобразовательное
    учреждение гимназия № 144» — реальная строка стр. 1, где Natasha не
    отдаёт спана вовсе (диагностика плана T2.2.2, Д11)."""
    text = (
        "Муниципальное автономное общеобразовательное учреждение гимназия № 144, "
        "в лице директора Мокиной Светланы Владимировны, действующего на основании Устава"
    )
    entities = _detect(text)
    assert len(entities) == 1, entities
    assert (
        entities[0].text == "Муниципальное автономное общеобразовательное учреждение гимназия № 144"
    )
    assert entities[0].source.value == "rule"


def test_org_form_abbreviation_maou() -> None:
    """`МАОУ гимназия №144` и `МАОУ гимназии № 144` — по одной сущности каждая."""
    entities_nominative = _detect("МАОУ гимназия №144, в лице директора")
    assert [e.text for e in entities_nominative] == ["МАОУ гимназия №144"]

    entities_genitive = _detect("режима работы  МАОУ гимназии № 144, расписания уроков")
    assert [e.text for e in entities_genitive] == ["МАОУ гимназии № 144"]


def test_org_form_double_space_from_pdf_layout_is_matched() -> None:
    """Двойной пробел внутри многословной формы (артефакт вёрстки PDF) не
    должен потерять «Общество с» — план T2.2.2, шаг 6, докстринг модуля."""
    text = (
        "и Общество с  Ограниченной Ответственностью "
        "«Школьно-базовая столовая № 11», именуемое в дальнейшем"
    )
    entities = _detect(text)
    assert len(entities) == 1, entities
    assert (
        entities[0].text
        == "Общество с  Ограниченной Ответственностью «Школьно-базовая столовая № 11»"
    )


def test_org_form_stops_at_role_words() -> None:
    """Расширение вправо останавливается на ролевом токене/стоп-слове, не
    захватывая продолжение предложения («в лице директора…»)."""
    text = (
        "Муниципальное автономное общеобразовательное учреждение гимназия № 144 "
        "в лице директора Иванова"
    )
    entities = _detect(text)
    assert len(entities) == 1, entities
    assert (
        entities[0].text == "Муниципальное автономное общеобразовательное учреждение гимназия № 144"
    )


def test_org_form_stops_after_number_in_prose() -> None:
    """В обычной прозе («в обеденном зале МАОУ гимназия №144 силами своих
    работников») номер — естественный конец названия, а не начало
    захваченного продолжения фразы (реальный дефект на стр. с п. 4.15)."""
    text = (
        "накрытие столов в обеденном зале МАОУ  гимназия №144 "
        "силами своих работников и за счет средств"
    )
    entities = _detect(text)
    assert len(entities) == 1, entities
    assert entities[0].text == "МАОУ  гимназия №144"


def test_public_body_is_not_detected() -> None:
    """«Администрация города Екатеринбурга» — публичный орган, не ПДн."""
    entities = _detect("Постановлением Администрации города Екатеринбурга от 01.01.2020")
    assert entities == []


def test_org_form_without_name_is_dropped() -> None:
    """Форма без продолжения (название дальше не следует) не выпускается."""
    entities = _detect("общеобразовательное учреждение,")
    assert entities == []


def test_number_stays_in_org_name() -> None:
    """Группа «№ <цифры>» входит в название целиком — `shrink_span` к
    результату этого детектора не применяется."""
    entities = _detect("МАОУ гимназия № 144, действующего на основании")
    assert len(entities) == 1
    assert entities[0].text.endswith("№ 144")


def test_org_form_quoted_name_matches_existing_behaviour() -> None:
    """На форме, знакомой существующему `expand_org_span` (ООО в кавычках),
    результат — одна и ровно та же строка, что и раньше."""
    entities = _detect("ООО «Ромашка», именуемое в дальнейшем «Поставщик»")
    assert [e.text for e in entities] == ["ООО «Ромашка»"]
