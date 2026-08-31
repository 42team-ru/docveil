from masker.profile.labels import find_labels


def test_storony_is_not_a_role() -> None:
    """«Стороны» называет сразу обе стороны договора — ролью одной стороны быть не может."""
    assert find_labels("8. Адреса и платежные реквизиты Сторон") == []


def test_requisites_still_finds_a_real_role() -> None:
    assert find_labels("Реквизиты Поставщика") == [(10, "поставщика")]


def test_signature_line_with_a_number_is_not_captured() -> None:
    """Регресс: цифра в метке ломает захват группы SIGNATURE — фиксируем факт поведения."""
    assert find_labels("Сторона-1: ____") == []


def test_preamble_still_finds_a_role_next_to_the_word_side() -> None:
    """Метка рядом со словом «сторона», но не являющаяся им самим, не должна отбрасываться."""
    assert find_labels('__, именуемое в дальнейшем "Продавец", с одной стороны') == [
        (28, "продавец")
    ]
