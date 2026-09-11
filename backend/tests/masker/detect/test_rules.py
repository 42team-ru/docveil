"""Тесты слоя правил: регулярки, контрольные суммы, разрешение пересечений."""

from pathlib import Path

from masker.detect.rules import _has_passport_context, detect_by_rules
from masker.ingest.docx_ingest import ingest_docx
from masker.model import Anchor, EntityType, Segment


def test_bank_account_found_with_valid_checksum() -> None:
    """Дефект 1: счёт 40702810100000000002 должен находиться с БИК 042007681."""
    segments = [
        Segment(
            text="БИК: 042007681",
            anchor=Anchor(fmt="docx", locator=("body", 0), label="абзац 1"),
            order=0,
        ),
        Segment(
            text="Расчётный счёт: 40702810100000000002",
            anchor=Anchor(fmt="docx", locator=("body", 1), label="абзац 2"),
            order=1,
        ),
    ]

    entities = detect_by_rules(segments)

    # Должен найтись БИК
    biks = [e for e in entities if e.type == EntityType.BIK]
    assert len(biks) == 1
    assert biks[0].text == "042007681"

    # Должен найтись счёт
    accounts = [e for e in entities if e.type == EntityType.BANK_ACCOUNT]
    assert len(accounts) == 1
    assert accounts[0].text == "40702810100000000002"
    assert accounts[0].confidence == 1.0


def test_personal_account_found_only_with_account_context() -> None:
    """Р14: одиннадцатизначный л/сч — счёт только после его метки."""
    contexts = (
        "л/с 39062000144",
        "л/сч 39062000144",
        "лицевой счёт 39062000144",
        "лицевого счёта: 39062000144",
    )

    for text in contexts:
        segment = Segment(
            text=text,
            anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
            order=0,
        )

        accounts = [
            entity
            for entity in detect_by_rules([segment])
            if entity.type is EntityType.BANK_ACCOUNT
        ]

        assert [(entity.text, entity.confidence) for entity in accounts] == [("39062000144", 1.0)]


def test_treasury_personal_account_with_letter_and_qualified_label_is_found() -> None:
    """Р18: лицевой счёт допускает букву и уточнение между меткой и значением."""
    segment = Segment(
        text=(
            "Номер лицевого счета на сайте федерального казначейства: "
            "03061А74190"
        ),
        anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
        order=0,
    )

    accounts = [
        entity for entity in detect_by_rules([segment]) if entity.type is EntityType.BANK_ACCOUNT
    ]

    assert [(entity.text, entity.normalized) for entity in accounts] == [
        ("03061А74190", "03061А74190")
    ]


def test_eleven_digit_numbers_without_personal_account_context_are_not_accounts() -> None:
    """Р14: ОКТМО, СНИЛС и голый код не становятся лицевыми счетами."""
    segment = Segment(
        text="ОКТМО 65701000001; СНИЛС 112-233-445 95; код 39062000144",
        anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
        order=0,
    )

    entities = detect_by_rules([segment])

    assert not any(entity.type is EntityType.BANK_ACCOUNT for entity in entities)
    assert [(entity.type, entity.text) for entity in entities] == [
        (EntityType.SNILS, "112-233-445 95"),
    ]


def test_invalid_inn_not_detected_as_passport() -> None:
    """Дефект 2: ИНН с битой контрольной цифрой не должен опознаваться как паспорт."""
    segments = [
        Segment(
            text="Накладная № 3662103004 от 12.02.2026.",
            anchor=Anchor(fmt="docx", locator=("body", 0), label="абзац 1"),
            order=0,
        ),
    ]

    entities = detect_by_rules(segments)

    # 3662103004 не должно попасть ни в одну сущность
    assert not any(e.text.replace(" ", "").replace("-", "") == "3662103004" for e in entities)

    # ИНН с битой контрольной цифрой не должен находиться
    inns = [e for e in entities if e.type == EntityType.INN]
    assert len(inns) == 0


def test_real_passport_with_context_detected() -> None:
    """Настоящий паспорт с правильным контекстом должен находиться."""
    segments = [
        Segment(
            text="Паспорт: 20 04 123456, выдан ОУФМС по Воронежской области.",
            anchor=Anchor(fmt="docx", locator=("body", 0), label="абзац 1"),
            order=0,
        ),
    ]

    entities = detect_by_rules(segments)

    passports = [e for e in entities if e.type == EntityType.PASSPORT]
    assert len(passports) == 1
    assert passports[0].text == "20 04 123456"


def test_phone_not_found_inside_bank_account() -> None:
    """Дефект 3: телефон 810100000000 не должен находиться внутри 20-значного счёта."""
    segments = [
        Segment(
            text="БИК: 042007681",
            anchor=Anchor(fmt="docx", locator=("body", 0), label="абзац 1"),
            order=0,
        ),
        Segment(
            text="Счёт: 40702810100000000002",
            anchor=Anchor(fmt="docx", locator=("body", 1), label="абзац 2"),
            order=1,
        ),
    ]

    entities = detect_by_rules(segments)

    # Не должно быть ложного телефона
    false_phones = [
        e
        for e in entities
        if e.type == EntityType.PHONE and "810100000000" in e.text.replace(" ", "").replace("-", "")
    ]
    assert len(false_phones) == 0

    # Счёт должен найтись
    accounts = [e for e in entities if e.type == EntityType.BANK_ACCOUNT]
    assert len(accounts) == 1


def test_passport_context_detection() -> None:
    """Проверка функции определения контекста паспорта."""
    # Паспорт с правильным контекстом
    assert _has_passport_context("Паспорт: 20 04 123456 выдан", 9, 19)
    assert _has_passport_context("Серия и номер: 20 04 123456", 15, 25)
    assert _has_passport_context("Удостоверение личности 20 04 123456", 24, 34)

    # Накладная - не паспорт
    assert not _has_passport_context("Накладная № 3662103004 от 12.02.2026", 12, 22)

    # ИНН - не паспорт
    assert not _has_passport_context("ИНН: 3662103004", 5, 15)

    # Договор - не паспорт
    assert not _has_passport_context("Договор № 1234567890", 10, 20)


def test_overlaps_resolution_priority() -> None:
    """Проверка, что более длинные и приоритетные сущности побеждают короткие."""
    # 20-значный счёт должен победить 11-значный СНИЛС внутри него
    segments = [
        Segment(
            text="БИК 042007681 счёт 40702810100000000002",
            anchor=Anchor(fmt="docx", locator=("body", 0), label="абзац 1"),
            order=0,
        ),
    ]

    entities = detect_by_rules(segments)

    # Должны быть БИК и счёт, но не СНИЛС внутри счёта
    types = {e.type for e in entities}
    assert EntityType.BIK in types
    assert EntityType.BANK_ACCOUNT in types
    assert EntityType.SNILS not in types

    # Телефон не должен найтись внутри счёта
    assert EntityType.PHONE not in types


def test_golden_snapshot_contract_01() -> None:
    """Общий нормализатор не изменил контракт слоя правил.

    Первая запись — `contract_number` из шага 10 плана T2.2.1 (Д6):
    `document.segments[0].text == "ДОГОВОР ПОСТАВКИ № 44/2026"`, триггер
    «ДОГОВОР» слева от «№», тело «44/2026» без самого «№». Реальный номер
    договора в тексте — не значение из `contract_01.labels.json`
    (`"ДП-2024/117"`, которого в документе не встречается ни разу) —
    расхождение разметки и текста существовало до этого шага и им не
    введено; отдельная находка, не эта задача.
    """
    root = Path(__file__).resolve().parents[3]
    document = ingest_docx(root / "fixtures/labeled/contract_01.docx")

    actual = [
        (item.type, item.text, item.segment_order, item.start, item.end, item.normalized)
        for item in detect_by_rules(document.segments)
    ]

    assert actual == [
        (EntityType.CONTRACT_NUMBER, "44/2026", 0, 19, 26, "44/2026"),
        (EntityType.INN, "3662103003", 2, 35, 45, "3662103003"),
        (EntityType.KPP, "366201001", 2, 51, 60, "366201001"),
        (EntityType.OGRN, "1023601546902", 2, 67, 80, "1023601546902"),
        (EntityType.INN, "7707083893", 3, 55, 65, "7707083893"),
        (EntityType.KPP, "770701001", 3, 71, 80, "770701001"),
        (EntityType.BANK_ACCOUNT, "40702810100000000002", 6, 16, 36, "40702810100000000002"),
        (EntityType.BIK, "042007681", 7, 5, 14, "042007681"),
        (EntityType.PHONE, "+7 (473) 250-10-10", 8, 9, 27, "+7(473)2501010"),
        (EntityType.EMAIL, "info@triema.example", 8, 37, 56, "info@triema.example"),
        (EntityType.PHONE, "8-910-347-51-07", 11, 9, 24, "89103475107"),
        (EntityType.EMAIL, "zakupki@vektor.example", 12, 8, 30, "zakupki@vektor.example"),
    ]


def test_real_phones_still_detected() -> None:
    """Настоящие телефоны должны находиться."""
    segments = [
        Segment(
            text="Телефон: +7 (473) 250-10-10, 8-910-347-51-07",
            anchor=Anchor(fmt="docx", locator=("body", 0), label="абзац 1"),
            order=0,
        ),
    ]

    entities = detect_by_rules(segments)

    phones = [e for e in entities if e.type == EntityType.PHONE]
    assert len(phones) == 2
    assert any("+7 (473) 250-10-10" in e.text for e in phones)
    assert any("8-910-347-51-07" in e.text for e in phones)


def test_phone_with_seven_country_prefix_without_plus_is_found() -> None:
    """Р18: ``7(814)259-09-61`` — полный телефон и без знака «+»."""
    segment = Segment(
        text="Номер контактного телефона: 7(814)259-09-61",
        anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
        order=0,
    )

    phones = [entity for entity in detect_by_rules([segment]) if entity.type is EntityType.PHONE]

    assert [entity.text for entity in phones] == ["7(814)259-09-61"]


def test_ten_digit_phone_requires_phone_context() -> None:
    """Р18: десять цифр без телефонного контекста не становятся телефоном."""
    segment = Segment(
        text="Код поставки: 1234567890",
        anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
        order=0,
    )

    assert not any(entity.type is EntityType.PHONE for entity in detect_by_rules([segment]))


def test_ten_digit_phones_are_found_in_contact_field_and_phone_table() -> None:
    """Р18: голые номера разрешены только полем телефона либо его таблицей."""
    segments = [
        Segment(
            text="Контактный телефон: 3833300807; 3833320032",
            anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
            order=0,
        ),
        Segment(
            text="Перечень абонентских номеров",
            anchor=Anchor(fmt="pdf", locator=("page", 1), label="стр. 2"),
            order=1,
        ),
        Segment(
            text="1 3833300975 шт.",
            anchor=Anchor(fmt="pdf", locator=("page", 2), label="стр. 3"),
            order=2,
        ),
    ]

    phones = [entity for entity in detect_by_rules(segments) if entity.type is EntityType.PHONE]

    assert [entity.text for entity in phones] == ["3833300807", "3833320032", "3833300975"]


def test_treasury_bik_wins_over_kpp() -> None:
    """Д8, план T2.2.1: `016577551` — казначейский БИК, а не КПП.

    Формат совпадает с обоими типами (девять цифр), но `PRIORITY` ставит
    BIK выше KPP, а без метки «КПП»/ИНН рядом KPP-кандидат вообще не
    выпускается — победитель однозначен.
    """
    segments = [
        Segment(
            text="БИК 016577551",
            anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
            order=0,
        ),
    ]

    entities = detect_by_rules(segments)

    assert len(entities) == 1
    assert entities[0].type is EntityType.BIK
    assert entities[0].text == "016577551"


def test_account_is_kept_when_valid_bik_is_in_same_segment() -> None:
    """Регрессия под Р9 (план T2.2.1, риск шага 8): когда БИК и счёт
    окажутся в одном сегменте (после будущего укрупнения сегментов PDF),
    казначейский счёт не должен пропасть из-за старой болезни ключа (Д8) —
    до шага 4 он был бы отброшен, потому что `near` уже не пуст, а старый
    `is_valid_account` считал его недействительным."""
    segments = [
        Segment(
            text="БИК 016577551 р/с 03234643657010006200",
            anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
            order=0,
        ),
    ]

    entities = detect_by_rules(segments)

    accounts = [e for e in entities if e.type is EntityType.BANK_ACCOUNT]
    assert len(accounts) == 1
    assert accounts[0].text == "03234643657010006200"
    assert accounts[0].confidence == 1.0


def test_kpp_requires_label_or_inn_context() -> None:
    """КПП перестаёт быть пылесосом (Д8, план T2.2.1, шаг 4)."""
    # Голое девятизначное число из таблицы питания — не КПП.
    no_context = [
        Segment(
            text="101260292",
            anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
            order=0,
        ),
    ]
    assert not any(e.type is EntityType.KPP for e in detect_by_rules(no_context))

    # Метка «КПП» вплотную — выпускается.
    with_label = [
        Segment(
            text="КПП: 668601001",
            anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
            order=0,
        ),
    ]
    kpps = [e for e in detect_by_rules(with_label) if e.type is EntityType.KPP]
    assert len(kpps) == 1
    assert kpps[0].text == "668601001"


def test_kpp_accepted_via_valid_inn_in_same_segment_without_label() -> None:
    """Второй путь принятия КПП — валидный ИНН рядом, метка не обязательна."""
    segments = [
        Segment(
            text="6663057404 668601001",
            anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
            order=0,
        ),
    ]

    kpps = [e for e in detect_by_rules(segments) if e.type is EntityType.KPP]
    assert len(kpps) == 1
    assert kpps[0].text == "668601001"


def test_landline_phone_without_country_code() -> None:
    """Городской номер в формате (код) XXX-XX-XX без +7/8 должен детектироваться."""
    segments = [
        Segment(
            text="тел: (812) 411-11-22",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]
    phones = [e for e in detect_by_rules(segments) if e.type == EntityType.PHONE]
    assert len(phones) == 1
    assert "(812) 411-11-22" in phones[0].text


# ---------------------------------------------------------------------------
# Номер договора/закупки: контекстное правило без контрольной суммы (Д6).
# ---------------------------------------------------------------------------


def test_contract_number_double_space() -> None:
    """Реальная строка со страницы 1 `contract_pdf_02_school.pdf`: два
    пробела между «№» и телом номера, триггер «закупочной» слева."""
    segments = [
        Segment(
            text=(
                "во исполнение протокола закупочной комиссии от 24.12.2025г. "
                "№  32515504247-01, заключили настоящий договор"
            ),
            anchor=Anchor(fmt="pdf", locator=("page", 0, 0, 10)),
            order=0,
        ),
    ]
    numbers = [e for e in detect_by_rules(segments) if e.type is EntityType.CONTRACT_NUMBER]
    assert len(numbers) == 1
    assert numbers[0].text == "32515504247-01"


def test_contract_number_zero_space() -> None:
    """Реальная строка футера `contract_pdf_02_school.pdf`: «№» вплотную
    к телу номера, без пробела, триггер «Договор» слева."""
    segments = [
        Segment(
            text='Документ подписан на ЭП "РТС-тендер" Договор №2025.334807 Страница 5 из 44',
            anchor=Anchor(fmt="pdf", locator=("page", 0, 0, 10)),
            order=0,
        ),
    ]
    numbers = [e for e in detect_by_rules(segments) if e.type is EntityType.CONTRACT_NUMBER]
    assert len(numbers) == 1
    assert numbers[0].text == "2025.334807"


def test_contract_number_requires_trigger() -> None:
    """Без триггера слева «№ + число» не становится номером договора —
    иначе номер гимназии и номер приложения тоже стали бы contract_number."""
    segments = [
        Segment(
            text="Муниципальное автономное учреждение гимназия № 144",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
        Segment(
            text="Техническое задание (приложение № 1) прилагается",
            anchor=Anchor(fmt="docx", locator=("body", 1), label=""),
            order=1,
        ),
        Segment(
            text="Товар соответствует требованиям ТР ТС 021/2011",
            anchor=Anchor(fmt="docx", locator=("body", 2), label=""),
            order=2,
        ),
    ]
    numbers = [e for e in detect_by_rules(segments) if e.type is EntityType.CONTRACT_NUMBER]
    assert numbers == []


def test_contract_number_short_body_is_not_enough_even_with_trigger() -> None:
    """Тело короче пяти символов не становится номером договора, даже
    рядом с триггером — «гимназия» здесь намеренно не единственная защита."""
    segments = [
        Segment(
            text="Договор № 5 вступает в силу",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]
    numbers = [e for e in detect_by_rules(segments) if e.type is EntityType.CONTRACT_NUMBER]
    assert numbers == []


# ---------------------------------------------------------------------------
# Р2 — воспроизводимая утечка: регулярка телефона выедала часть счёта и
# выигрывала разрешение пересечений (план T2.2.1).
# ---------------------------------------------------------------------------


def test_defect_bank_account_survives_overlapping_phone_digits() -> None:
    """Дефект из плана T2.2.1 (Р2): раньше `phone='810100000012'` съедал
    часть счёта, а `bank_account` пропадал. Теперь счёт находится, а
    ложного телефона внутри него нет."""
    segments = [
        Segment(
            text="р/с 40702810100000012345 в банке, БИК 044525225",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]

    entities = detect_by_rules(segments)

    accounts = [e for e in entities if e.type is EntityType.BANK_ACCOUNT]
    assert len(accounts) == 1
    assert accounts[0].text == "40702810100000012345"
    assert not any(e.type is EntityType.PHONE for e in entities)
    assert any(e.type is EntityType.BIK for e in entities)


def test_two_valid_accounts_both_found_with_shared_bik() -> None:
    """Приёмка Р2: строка с расчётным и корреспондентским счётом при одном
    БИК рядом должна дать ОБА счёта, а не один."""
    segments = [
        Segment(
            text=("Расчётный счёт 40702810100000012345, БИК 044525225, к/с 30101810400000000225"),
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]

    entities = detect_by_rules(segments)

    accounts = {e.text for e in entities if e.type is EntityType.BANK_ACCOUNT}
    assert accounts == {"40702810100000012345", "30101810400000000225"}


# ---------------------------------------------------------------------------
# Р3 — недописанные формы правил (план T2.2.1).
# ---------------------------------------------------------------------------


def test_passport_form_series_word_before_number_symbol() -> None:
    """`серия 2004 № 123456` — самая частая реальная форма (Р3)."""
    segments = [
        Segment(
            text="паспорт серия 2004 № 123456 выдан ОВД",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]
    passports = [e for e in detect_by_rules(segments) if e.type is EntityType.PASSPORT]
    assert len(passports) == 1
    assert passports[0].normalized == "2004123456"


def test_passport_form_split_series_number_symbol_no_space() -> None:
    """`20 04 №123456` — серия через пробел, «№» вплотную к номеру (Р3)."""
    segments = [
        Segment(
            text="паспорт 20 04 №123456 выдан ОВД",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]
    passports = [e for e in detect_by_rules(segments) if e.type is EntityType.PASSPORT]
    assert len(passports) == 1
    assert passports[0].normalized == "2004123456"


def test_passport_form_series_glued_no_number_symbol() -> None:
    """`2004 123456` — серия слитно, без «№» вовсе (Р3)."""
    segments = [
        Segment(
            text="паспорт 2004 123456 выдан ОВД",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]
    passports = [e for e in detect_by_rules(segments) if e.type is EntityType.PASSPORT]
    assert len(passports) == 1
    assert passports[0].normalized == "2004123456"


def test_snils_dot_separator_found_and_normalized_like_hyphenated() -> None:
    """`112.233.445.95` — реальная форма записи СНИЛС через точки (Р3);
    нормализованный ключ должен совпасть с дефисной записью того же СНИЛС."""
    dot_segments = [
        Segment(
            text="СНИЛС 112.233.445.95 указан в анкете",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]
    hyphen_segments = [
        Segment(
            text="СНИЛС 112-233-445 95 указан в анкете",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]

    dot_snils = [e for e in detect_by_rules(dot_segments) if e.type is EntityType.SNILS]
    hyphen_snils = [e for e in detect_by_rules(hyphen_segments) if e.type is EntityType.SNILS]

    assert len(dot_snils) == 1
    assert dot_snils[0].text == "112.233.445.95"
    assert len(hyphen_snils) == 1
    assert dot_snils[0].normalized == hyphen_snils[0].normalized == "11223344595"


def test_snils_dot_separator_with_broken_checksum_is_rejected() -> None:
    """Битый СНИЛС (контрольные разряды не сходятся) не должен находиться
    даже в новой форме через точки — форма не отменяет проверку суммы."""
    segments = [
        Segment(
            text="СНИЛС 112.233.445.96 указан в анкете",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]
    assert not any(e.type is EntityType.SNILS for e in detect_by_rules(segments))


def test_phone_dot_separator_found() -> None:
    """`8.473.250.30.30` — телефон с точками вместо дефисов (Р3)."""
    segments = [
        Segment(
            text="тел. 8.473.250.30.30 звонить с 9 до 18",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]
    phones = [e for e in detect_by_rules(segments) if e.type is EntityType.PHONE]
    assert len(phones) == 1
    assert phones[0].text == "8.473.250.30.30"


def test_phone_does_not_trigger_inside_longer_digit_run() -> None:
    """Корень дефекта Р2: телефон не должен находиться внутри более
    длинной цифровой последовательности — даже когда рядом нет БИК и
    сравнивать не с чем."""
    segments = [
        Segment(
            text="код заказа 81234567890123456789 присвоен автоматически",
            anchor=Anchor(fmt="docx", locator=("body", 0), label=""),
            order=0,
        ),
    ]
    assert not any(e.type is EntityType.PHONE for e in detect_by_rules(segments))


# ---------------------------------------------------------------------------
# Р16/Р17 — ключи открытых реестров.
# ---------------------------------------------------------------------------


def test_registry_key_detector_masks_ikz_as_a_single_entity() -> None:
    """ИКЗ не дробится на реквизиты и сам становится одной заменой."""
    segment = Segment(
        text="ИКЗ: 24 1 7710474375 770301001 0038 001 0000 244",
        anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
        order=0,
    )

    entities = detect_by_rules([segment])

    assert [(entity.type, entity.text) for entity in entities] == [
        (EntityType.REGISTRY_KEY, "24 1 7710474375 770301001 0038 001 0000 244")
    ]


def test_registry_key_detector_masks_license_number_by_its_format() -> None:
    """Стандартный номер лицензии — самостоятельный ключ реестра."""
    segment = Segment(
        text="Л030-00114-77/00078235 выдана для оказания услуг связи",
        anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
        order=0,
    )

    assert [(entity.type, entity.text) for entity in detect_by_rules([segment])] == [
        (EntityType.REGISTRY_KEY, "Л030-00114-77/00078235")
    ]


def test_registry_key_detector_masks_okpo_only_after_its_label() -> None:
    """ОКПО — восемь цифр только с явной меткой классификатора."""
    segment = Segment(
        text="ОКПО 12711098; код по ОКПО: 84454733",
        anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
        order=0,
    )

    assert [(entity.type, entity.text) for entity in detect_by_rules([segment])] == [
        (EntityType.REGISTRY_KEY, "12711098"),
        (EntityType.REGISTRY_KEY, "84454733"),
    ]


def test_registry_key_detector_does_not_treat_bare_eight_digits_as_okpo() -> None:
    """Количество или сумма из восьми цифр без контекста не является ОКПО."""
    segment = Segment(
        text="В партии предусмотрено 12711098 единиц товара.",
        anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
        order=0,
    )

    assert not any(entity.type is EntityType.REGISTRY_KEY for entity in detect_by_rules([segment]))


# ---------------------------------------------------------------------------
# Р13 — ИКЗ не является контейнером для вложенных реквизитов.
# ---------------------------------------------------------------------------


def test_ikz_is_excluded_from_requisite_rules() -> None:
    """Старый 29-значный ИКЗ с группировкой не дробится на счёт, ИНН и КПП.

    Без исключения `bank_account` сначала совпадает с двадцатью цифрами,
    а затем после пересечения с вложенными ИНН/КПП превращается в «1 ».
    """
    segment = Segment(
        text="Идентификационный код закупки: 24 1 7710474375 770301001 0038 001",
        anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
        order=0,
    )

    entities = detect_by_rules([segment])

    requisites = {
        EntityType.BANK_ACCOUNT,
        EntityType.INN,
        EntityType.OGRN,
        EntityType.SNILS,
        EntityType.KPP,
        EntityType.BIK,
    }
    assert not any(entity.type in requisites for entity in entities)


def test_current_36_digit_ikz_is_also_excluded_from_requisite_rules() -> None:
    """Текущий слитный ИКЗ не отдаёт вложенный ИНН/КПП как отдельные PII."""
    segment = Segment(
        text=(
            "Идентификационный код закупки: "
            "182519150124451900100100070016110244"
        ),
        anchor=Anchor(fmt="pdf", locator=("page", 0), label="стр. 1"),
        order=0,
    )

    entities = detect_by_rules([segment])

    assert not any(
        entity.type
        in {
            EntityType.BANK_ACCOUNT,
            EntityType.INN,
            EntityType.OGRN,
            EntityType.SNILS,
            EntityType.KPP,
            EntityType.BIK,
        }
        for entity in entities
    )
