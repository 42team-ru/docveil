from masker.detect.ner import NatashaDetector
from masker.detect.orgforms import (
    expand_org_span,
    fix_person_initials,
    is_organization_form_only,
    is_public_body,
    is_role_stopword,
    org_forms,
    shrink_span,
)
from masker.model import Anchor, Document, EntityType, Segment


def _org_names(text: str) -> list[str]:
    document = Document(
        path="x.pdf",
        fmt="pdf",
        segments=[Segment(text=text, anchor=Anchor(fmt="pdf", locator=("page", 0)), order=0)],
    )
    return [
        entity.text
        for entity in NatashaDetector().detect(document)
        if entity.type is EntityType.ORG_NAME
    ]


def test_full_form_expanded() -> None:
    text = "Поставщик: Общество с ограниченной ответственностью «Вектор»"
    start = text.index("Вектор")
    assert expand_org_span(text, start, start + len("Вектор")) == (11, len(text))


def test_abbreviation_untouched() -> None:
    text = "ООО «Вектор»"
    assert expand_org_span(text, 0, len(text)) == (0, len(text))


def test_aktiv_not_dropped() -> None:
    assert not is_role_stopword("Актив")
    assert not is_role_stopword("Актион")
    assert is_role_stopword("Акт")


def test_seller_role_is_dropped() -> None:
    for value in (
        "Продавец",
        "Продавца",
        "Продавцу",
        "Должника",
        "Финансовый управляющий",
    ):
        assert is_role_stopword(value)


def test_document_heading_dropped() -> None:
    assert is_role_stopword("ДОГОВОР ПОСТАВКИ")
    assert is_role_stopword("ПРОТОКОЛ СОГЛАСОВАНИЯ")
    assert is_role_stopword("ПРОВЕРКА ТАБЛИЦ")


def test_role_stopword_does_not_drop_org_names() -> None:
    assert not is_role_stopword("Договор и партнёры")
    assert not is_role_stopword("Продавцов и сыновья")


def test_common_prefix_forms_are_deterministic() -> None:
    text = "Закрытое акционерное общество «Ромашка»"
    start = text.index("Ромашка")
    assert expand_org_span(text, start, start + len("Ромашка")) == (0, len(text))


def test_yaml_order_does_not_matter(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    before = [is_role_stopword(value) for value in ("Продавца", "Актив", "ДОГОВОР ПОСТАВКИ")]
    data = org_forms()
    monkeypatch.setattr(
        "masker.detect.orgforms.org_forms",
        lambda: type(data)(
            forms=tuple(reversed(data.forms)),
            role_stems=tuple(reversed(data.role_stems)),
            role_words=frozenset(reversed(tuple(data.role_words))),
            requisite_labels=frozenset(reversed(tuple(data.requisite_labels))),
            public_bodies=tuple(reversed(data.public_bodies)),
            landmark_stems=tuple(reversed(data.landmark_stems)),
            quote_pairs=tuple(reversed(data.quote_pairs)),
        ),
    )
    assert [
        is_role_stopword(value) for value in ("Продавца", "Актив", "ДОГОВОР ПОСТАВКИ")
    ] == before


def test_shrink_drops_requisite_label() -> None:
    text = 'ООО "Ромашка" (ИНН'
    assert shrink_span(text, 0, len(text)) == (0, len('ООО "Ромашка"'))


def test_shrink_drops_unlisted_requisite() -> None:
    for text, expected in (
        ('ООО "Ромашка" р/с', 'ООО "Ромашка"'),
        ("Кузнецов Пётр Алексеевич паспорт", "Кузнецов Пётр Алексеевич"),
    ):
        assert shrink_span(text, 0, len(text)) == (0, len(expected))


def test_shrink_keeps_digits_inside_quotes() -> None:
    text = 'ООО "Спорт 24"'
    assert shrink_span(text, 0, len(text)) == (0, len(text))


def test_shrink_does_not_cut_word_ending_in_label() -> None:
    for text in ("ООО Магазинн", "Сидоров Куинн"):
        assert shrink_span(text, 0, len(text)) == (0, len(text))


def test_shrink_is_idempotent() -> None:
    text = 'ООО "Ромашка" (ОКПО 12345678'
    first = shrink_span(text, 0, len(text))
    assert first is not None
    assert shrink_span(text, *first) == first


def test_public_body_is_dropped_without_prefix_collisions() -> None:
    assert is_public_body("Арбитражного суда")
    assert is_public_body("ФНС")
    assert not is_public_body("Судостроительный завод")


def test_person_initial_gets_trailing_dot() -> None:
    text = "ИП Сидоров С.С."
    assert fix_person_initials(text, 3, len(text) - 1) == (3, len(text))


def test_person_initial_dot_survives_shrink_span() -> None:
    """Р4, кейс 3 (`Пилипенко С.А.`): NER-спан уже содержит завершающую точку
    инициала, но `shrink_span` стриг её безусловно первой же операцией
    (``_trim_shrink_bounds``), не заглянув, что это не случайная пунктуация,
    а точка после одиночной заглавной буквы («С.А.»). Обычную сентенс-точку
    ``shrink_span`` по-прежнему обязан снимать — второй кейс ниже."""
    text = "Пилипенко С.А."
    assert shrink_span(text, 0, len(text)) == (0, len(text))


def test_shrink_span_still_drops_plain_trailing_dot() -> None:
    text = "ООО «Ромашка»."
    assert shrink_span(text, 0, len(text)) == (0, len("ООО «Ромашка»"))


def test_fix_person_initials_extends_oglu_suffix() -> None:
    """Р4, кейс 2 (`Мамедов Э.Г.о.`): NER отдаёт спан только по последний
    инициал без точки («Мамедов Э.Г»), хвост «о.» (сокращение «оглы») —
    за пределами спана."""
    text = "Согласовано: Мамедов Э.Г.о., начальник ОТК"
    start = text.index("Мамедов")
    raw_end = start + len("Мамедов Э.Г")
    assert fix_person_initials(text, start, raw_end) == (start, start + len("Мамедов Э.Г.о."))


# ---------------------------------------------------------------------------
# Границы ORG вправо, в кавычки после оргформы (план T2.2.1, шаг 5, Д5).
# ---------------------------------------------------------------------------


def test_org_span_expands_right_into_quoted_name() -> None:
    """Модель отдаёт только форму и обрывается ровно перед открывающей
    кавычкой с названием (реальный обрыв Natasha со страницы 1: спан
    `'Ограниченной Ответственностью'`, без ведущего «Общество с» и без
    названия справа) — спан обязан продлиться вправо до конца названия."""
    text = "и Общество с Ограниченной Ответственностью «Вектор», зарегистрированное в ЕГРЮЛ."
    start = text.index("Ограниченной")
    end = start + len("Ограниченной Ответственностью")
    assert expand_org_span(text, start, end) == (
        start,
        text.index("«Вектор»") + len("«Вектор»"),
    )


def test_org_span_stops_at_first_closing_quote() -> None:
    """«Ближайшая» закрывающая кавычка обязательна: иначе `ООО «X»,
    именуемое в дальнейшем «Потребитель»` схлопнется в один спан. Модель
    отдаёт только аббревиатуру («ООО»), без кавычек вовсе — ровно тот
    случай, когда расширение вправо обязано найти название само."""
    text = "ООО «X», именуемое в дальнейшем «Потребитель», заключило договор."
    assert expand_org_span(text, 0, len("ООО")) == (0, len("ООО «X»"))


def test_org_form_without_name_is_dropped() -> None:
    """Формы, которые Natasha возвращает отдельным спаном без имени
    (`Ограниченной Ответственностью`, `Муниципальное автономное
    общеобразовательное учреждение`), не несут ПДн, если справа нет
    названия — их обязана отбрасывать `is_organization_form_only`."""
    assert is_organization_form_only("Ограниченной Ответственностью")
    assert is_organization_form_only("Муниципальное автономное общеобразовательное учреждение")
    assert not is_organization_form_only("Ограниченной Ответственностью «Вектор»")


def test_org_span_recovers_full_name_on_real_pdf_page_blocks() -> None:
    """Регрессия на реальном документе (`contract_pdf_02_school.pdf`,
    страницы 1, 27, 36): строки блока склеены одним пробелом — так, как их
    отдаст `page_chars` после шага 8, — и на всех трёх текст ЕГРЮЛ-формы
    сходится с полным названием, а не обрывается на форме."""
    page_blocks = {
        1: (
            "и Общество с  Ограниченной Ответственностью «Школьно-базовая "
            "столовая № 11»  , в лице Директора Зубрицкой Татьяны."
        ),
        27: (
            "с одной стороны,  и Общество с Ограниченной Ответственностью "
            "«Школьно-базовая столовая № 11», в лице Директора Зубрицкой."
        ),
        36: (
            "с одной стороны, и Общество с Ограниченной Ответственностью "
            "«Школьно-базовая  столовая № 11», именуемое в дальнейшем "
            "«Потребитель», в лице Директора Зубрицкой Татьяны Ивановны."
        ),
    }
    expected = "Общество с Ограниченной Ответственностью «Школьно-базовая столовая № 11»"
    for page, text in page_blocks.items():
        orgs = [" ".join(value.split()) for value in _org_names(text)]
        assert expected in orgs, f"страница {page}: {orgs!r}"
