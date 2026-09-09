"""Три уровня уверенности детекции (Р8, TASKS.md, docs/plans).

Каждый тест бьёт по одной ветке `masker.detect.confidence.classify_level`:

1. Критичный тип — всегда `CONFIRMED`, при любом источнике/уверенности.
2. Контрольная сумма (`is_validated`) — `CONFIRMED` без критичности.
3. Два независимых сигнала (`signal_count >= 2`) — `CONFIRMED` без
   критичности и без контрольной суммы.
4. Один сигнал, открытый класс (org_name/person), заглавное имя вне
   белого списка — `POSSIBLE`.
5. Один сигнал, тот же текст, но в белом списке — `PROBABLE`, не `POSSIBLE`.
6. Один сигнал, закрытый класс (например, phone/email без чек-суммы) —
   `PROBABLE`, никогда `POSSIBLE`.
"""

from __future__ import annotations

from masker.detect.confidence import classify_level
from masker.detect.whitelist import is_whitelisted, name_whitelist
from masker.entity_types import EntityTypeRegistry
from masker.model import ConfidenceLevel, Entity, EntityType, Source


def _entity(
    etype: str,
    text: str,
    *,
    source: Source = Source.RULE,
    confidence: float = 1.0,
) -> Entity:
    return Entity(
        type=etype,
        text=text,
        segment_order=0,
        start=0,
        end=len(text),
        source=source,
        confidence=confidence,
    )


def test_critical_type_is_always_confirmed_regardless_of_source_and_confidence() -> None:
    """Р8, требование 2: критичный тип не зависит от политики/уверенности."""
    weak_snils = _entity(EntityType.SNILS, "112-233-445 95", source=Source.NER, confidence=0.1)

    assert classify_level(weak_snils, signal_count=1) == ConfidenceLevel.CONFIRMED


def test_critical_type_stays_confirmed_with_custom_registry_too() -> None:
    """Кастомный критичный тип (`registry.is_critical`) — та же гарантия,
    что и встроенный `CRITICAL_TYPES` (Р8 не должен знать разницы)."""
    from masker.entity_types import EntityTypeSpec

    registry = EntityTypeRegistry.builtin().extend(
        [EntityTypeSpec(id="product_code", title="Код изделия", marker_label="КОД", critical=True)]
    )
    weak_custom = _entity("product_code", "AB-1", source=Source.NER, confidence=0.2)

    assert classify_level(weak_custom, signal_count=1, registry=registry) == (
        ConfidenceLevel.CONFIRMED
    )


def test_checksum_validated_entity_is_confirmed_without_second_signal() -> None:
    """Контрольная сумма (ИНН) — `CONFIRMED` даже при единственном сигнале."""
    inn = _entity(EntityType.INN, "7707083893", confidence=1.0)

    assert classify_level(inn, signal_count=1) == ConfidenceLevel.CONFIRMED


def test_bank_account_without_bik_confirmation_is_not_confirmed_via_checksum() -> None:
    """Счёт без сошедшегося БИК (confidence=0.75) не проходит `is_validated`,
    но остаётся `CONFIRMED` — он критичный тип (требование 2), а не через
    контрольную сумму. Тест фиксирует, что критичность перекрывает checksum-путь."""
    account = _entity(EntityType.BANK_ACCOUNT, "40702810100000000002", confidence=0.75)

    assert classify_level(account, signal_count=1) == ConfidenceLevel.CONFIRMED


def test_bik_alone_is_not_checksum_validated_and_stays_probable() -> None:
    """БИК — не критичный тип и не входит в `is_validated` (только формат,
    без настоящей контрольной суммы, см. `masker.detect.resolve`) — при
    одном сигнале он `PROBABLE`, а не `CONFIRMED`."""
    bik = _entity(EntityType.BIK, "044525225", confidence=1.0)

    assert classify_level(bik, signal_count=1) == ConfidenceLevel.PROBABLE


def test_two_independent_signals_confirm_without_checksum() -> None:
    """Требование 1 таблицы: ≥2 независимых детектора на пересекающихся
    спанах — `CONFIRMED`, хотя ни критичности, ни контрольной суммы нет."""
    org_name = _entity(EntityType.ORG_NAME, "Ромашка", source=Source.NER, confidence=0.7)

    assert classify_level(org_name, signal_count=2) == ConfidenceLevel.CONFIRMED


def test_single_signal_open_class_capitalized_name_is_possible() -> None:
    """Заглавное имя собственное вне белого списка, один сигнал — `POSSIBLE`,
    вынесено в отчёте в «снять одним кликом»."""
    person = _entity(
        EntityType.PERSON, "Зубрицкая Анна Игоревна", source=Source.NER, confidence=0.6
    )

    assert classify_level(person, signal_count=1) == ConfidenceLevel.POSSIBLE


def test_whitelisted_open_class_text_is_probable_not_possible() -> None:
    """Юридический термин из белого списка не должен тянуть маску в
    «снять одним кликом», даже если он попал в open-class тип по ошибке
    детектора: белый список понижает `POSSIBLE` до `PROBABLE`."""
    fake_org = _entity(
        EntityType.ORG_NAME, "Российская Федерация", source=Source.NER, confidence=0.6
    )

    assert classify_level(fake_org, signal_count=1) == ConfidenceLevel.PROBABLE


def test_single_signal_closed_class_type_never_becomes_possible() -> None:
    """Форматный тип (email) не относится к открытому классу — при одном
    сигнале это `PROBABLE`, `POSSIBLE` для него в принципе не определён."""
    email = _entity(EntityType.EMAIL, "ivanov@example.com", confidence=0.9)

    assert classify_level(email, signal_count=1) == ConfidenceLevel.PROBABLE


def test_lowercase_open_class_text_is_probable_not_possible() -> None:
    """`POSSIBLE` — про заглавное имя собственное; текст без заглавной
    буквы (например, обрывок NER) не квалифицируется как «похоже на имя»."""
    lowercase_hit = _entity(EntityType.ORG_NAME, "поставщик", source=Source.NER, confidence=0.6)

    assert classify_level(lowercase_hit, signal_count=1) == ConfidenceLevel.PROBABLE


def test_name_whitelist_is_data_not_hardcoded_set_and_covers_negative_corpus_terms() -> None:
    """Белый список читается из YAML (данные, а не код) и покрывает термины
    негативного корпуса (ГОСТ/ТУ) — начальный набор из задания Р8."""
    whitelist = name_whitelist()

    assert isinstance(whitelist, frozenset)
    assert "гост" in whitelist
    assert "январь" in whitelist
    assert "рубль" in whitelist


def test_is_whitelisted_matches_case_insensitively() -> None:
    assert is_whitelisted("ГОСТ")
    assert is_whitelisted("Российская Федерация")
    assert not is_whitelisted("Зубрицкая Анна Игоревна")
