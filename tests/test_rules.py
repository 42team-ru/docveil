"""Тесты слоя правил: регулярки, контрольные суммы, разрешение пересечений."""

from masker.detect.rules import _has_passport_context, detect_by_rules
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
