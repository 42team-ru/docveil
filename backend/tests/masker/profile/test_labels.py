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


def test_requisites_does_not_swallow_the_rest_of_a_section_heading() -> None:
    """Регрессия плана T2.2.1, шаг 8/9: на сегменте-строке REQUISITES не
    успевала захватить больше слова-двух до конца строки; на сегменте-блоке
    (строки склеены пробелом, не переносом) без ограничения длины она
    захватывала весь заголовок раздела и слова за ним — реальный случай
    «5.БАНКОВСКИЕ РЕКВИЗИТЫ И ПОДПИСИ СТОРОН Учреждение Потребитель МАОУ
    гимназия» стал одной ролью на 6 слов, а маркер с ней не влезал ни в один
    прямоугольник PDF (`render/pdf_render.py::MarkerDoesNotFitError`)."""
    text = "5.БАНКОВСКИЕ РЕКВИЗИТЫ И ПОДПИСИ СТОРОН Учреждение Потребитель МАОУ гимназия № 144"
    labels = find_labels(text)
    assert labels == [(23, "и подписи")]
