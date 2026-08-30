from masker.detect.orgforms import (
    expand_org_span,
    fix_person_initials,
    is_public_body,
    is_role_stopword,
    org_forms,
    shrink_span,
)


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
