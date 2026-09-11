"""Тесты таблицы приоритетов разрешения пересечений слоя правил (план T2.2.1, Р2).

Каждый тест бьёт по одному из пяти правил `masker.detect.resolve`:

1. Валидированная сущность неприкосновенна.
2. Между двумя валидированными побеждает более длинная.
3. Невалидированная внутри валидированной отбрасывается целиком.
4. Невалидированная, пересекающая валидированную частично, обрезается.
5. Модельный спан режется об принятые — это `DetectAgent`, не этот модуль
   (см. `test_overlap_carving.py`); здесь только интеграционная проверка,
   что результат `resolve_overlaps` совместим с этой логикой.
"""

from __future__ import annotations

import dataclasses

from masker.detect.agent import DetectAgent
from masker.detect.resolve import is_validated, resolve_overlaps
from masker.model import Anchor, ConfidenceLevel, Document, Entity, EntityType, Segment, Source


def _entity(etype: str, text: str, start: int, confidence: float = 1.0) -> Entity:
    return Entity(
        type=etype,
        text=text,
        segment_order=0,
        start=start,
        end=start + len(text),
        source=Source.RULE,
        confidence=confidence,
    )


def test_rule1_validated_entity_is_untouchable() -> None:
    """Правило 1: валидированный ИНН не двигается и не обрезается, даже
    если его целиком перекрывает невалидированный кандидат подлиннее."""
    inn = _entity(EntityType.INN, "3662103003", start=0)
    overlapping_phone = _entity(EntityType.PHONE, "36621030031234", start=0, confidence=0.9)

    result = resolve_overlaps([inn, overlapping_phone])

    kept_inn = [e for e in result if e.type == EntityType.INN]
    assert kept_inn == [inn]


def test_rule2_longer_validated_wins_between_two_validated() -> None:
    """Правило 2: ОГРН (13 цифр, валидированный тип) длиннее и побеждает
    перекрывающий его ИНН (10 цифр, тоже валидированный тип)."""
    inn = _entity(EntityType.INN, "1023601546902"[:10], start=0)
    ogrn = _entity(EntityType.OGRN, "1023601546902", start=0)

    result = resolve_overlaps([inn, ogrn])

    assert result == [ogrn]


def test_rule3_unvalidated_fully_inside_validated_is_dropped() -> None:
    """Правило 3: телефон, целиком лежащий внутри валидированного счёта,
    отбрасывается — это корень дефекта Р2 (счёт не должен пропадать)."""
    account = _entity(EntityType.BANK_ACCOUNT, "40702810100000000002", start=0, confidence=1.0)
    phone_inside = _entity(EntityType.PHONE, "810100000000", start=3, confidence=0.9)

    result = resolve_overlaps([account, phone_inside])

    assert result == [account]
    assert not any(e.type == EntityType.PHONE for e in result)


def test_rule4_unvalidated_partial_overlap_is_trimmed() -> None:
    """Правило 4: невалидированная сущность, пересекающая валидированную
    лишь частично, обрезается до непересекающегося остатка."""
    kpp = _entity(EntityType.KPP, "366201001", start=5)  # [5, 14)
    contract = _entity(EntityType.CONTRACT_NUMBER, "ABCDEFGHIJ", start=0, confidence=0.9)  # [0, 10)

    result = resolve_overlaps([kpp, contract])

    trimmed = [e for e in result if e.type == EntityType.CONTRACT_NUMBER]
    assert len(trimmed) == 1
    assert trimmed[0].text == "ABCDE"
    assert (trimmed[0].start, trimmed[0].end) == (0, 5)
    assert any(e.type == EntityType.KPP for e in result)


def test_rule4_short_remainder_is_dropped_not_kept_as_junk() -> None:
    """Обрезка не должна оставлять однобуквенный мусор."""
    kpp = _entity(EntityType.KPP, "366201001", start=1)  # [1, 10)
    contract = _entity(EntityType.CONTRACT_NUMBER, "AB", start=0, confidence=0.9)  # [0, 2)

    result = resolve_overlaps([kpp, contract])

    assert not any(e.type == EntityType.CONTRACT_NUMBER for e in result)


def test_rule4_drops_incomplete_bank_account_fragment() -> None:
    """Р13: остаток «1 » от 20-значного кандидата — не банковский счёт."""
    text = "1 7710474375 770301001"
    account = _entity(EntityType.BANK_ACCOUNT, text, start=0, confidence=0.75)
    inn = _entity(EntityType.INN, "7710474375", start=text.index("7710474375"))
    kpp = _entity(EntityType.KPP, "770301001", start=text.index("770301001"))

    result = resolve_overlaps([account, inn, kpp])

    assert [(entity.type, entity.text) for entity in result] == [
        (EntityType.INN, "7710474375"),
        (EntityType.KPP, "770301001"),
    ]


def test_rule5_resolved_rule_layer_still_gets_carved_by_agent() -> None:
    """Правило 5 — не здесь (см. `DetectAgent._carve`), но результат этого
    модуля должен оставаться пригодным входом для него: модельный спан,
    перекрывающий уже принятый счёт, обрезается агентом как раньше."""
    text = 'ООО "Ромашка" р/с 40702810100000000002'
    document = Document(
        path="t.docx",
        fmt="docx",
        segments=[Segment(text, Anchor("docx", ("body", 0)), 0)],
    )
    number_start = text.index("40702810100000000002")

    class _StubRule:
        name = "rules"
        source = Source.RULE
        priority = 100

        def detect(self, doc: Document) -> list[Entity]:
            return resolve_overlaps(
                [
                    _entity(
                        EntityType.BANK_ACCOUNT,
                        "40702810100000000002",
                        start=number_start,
                        confidence=1.0,
                    )
                ]
            )

    class _StubModel:
        name = "model"
        source = Source.NER
        priority = 50

        def detect(self, doc: Document) -> list[Entity]:
            return [Entity(EntityType.ORG_NAME, text, 0, 0, len(text), Source.NER)]

    result = DetectAgent([_StubModel(), _StubRule()]).detect(document)

    # Не проверяем точную границу обрезки модельного спана — это внутренняя
    # кухня `orgforms.shrink_span`, отдельная зона ответственности (план
    # T2.2.1). Важно для правила 5: результат `resolve_overlaps` остаётся
    # неприкосновенным якорем для агента, а счёт не утекает ни в одну
    # другую сущность после обрезки.
    accounts = [e for e in result.entities if e.type == EntityType.BANK_ACCOUNT]
    # Счёт — критичный тип (Р8): уровень уверенности всегда `CONFIRMED`,
    # это не зависит от исхода обрезки, проверяемого этим тестом.
    assert accounts == [
        dataclasses.replace(
            _entity(
                EntityType.BANK_ACCOUNT, "40702810100000000002", start=number_start, confidence=1.0
            ),
            level=ConfidenceLevel.CONFIRMED,
        )
    ]
    others = [e for e in result.entities if e.type != EntityType.BANK_ACCOUNT]
    assert not any("40702810100000000002" in e.text for e in others)


def test_bik_is_not_in_the_untouchable_tier() -> None:
    """БИК — форматное правило без контрольной суммы: надёжнее телефона
    (см. `FALLBACK_PRIORITY`), но не входит в `VALIDATED_TYPES` — иначе
    правило 1 сделало бы его неприкосновенным наравне с ИНН/ОГРН/СНИЛС/КПП."""
    bik = _entity(EntityType.BIK, "044525225", start=0, confidence=1.0)
    assert not is_validated(bik)


def test_bank_account_is_validated_only_with_matching_bik() -> None:
    """Счёт входит в неприкосновенный уровень только при confidence=1.0
    (контрольная сумма сошлась с реальным БИК рядом) — просто «формат
    сошёлся, БИК проверить нечем» (confidence=0.75) достаточным не считается."""
    validated_account = _entity(EntityType.BANK_ACCOUNT, "4" * 20, start=0, confidence=1.0)
    unvalidated_account = _entity(EntityType.BANK_ACCOUNT, "4" * 20, start=0, confidence=0.75)

    assert is_validated(validated_account)
    assert not is_validated(unvalidated_account)
