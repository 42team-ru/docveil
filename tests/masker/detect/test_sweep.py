"""Тесты `detect.sweep` — сквозной досмотр запланированных значений (Д13, план T2.2.2, шаг 8)."""

from __future__ import annotations

from masker.detect.sweep import sweep
from masker.model import Anchor, Document, Entity, EntityType, Segment, Source


def _document(texts: list[str]) -> Document:
    return Document(
        path="test.pdf",
        fmt="pdf",
        segments=[
            Segment(text=text, anchor=Anchor("pdf", ("page", 0, 0, len(text))), order=order)
            for order, text in enumerate(texts)
        ],
    )


def _entity(
    document: Document,
    segment_order: int,
    text: str,
    *,
    etype: EntityType = EntityType.CONTRACT_NUMBER,
    confidence: float = 0.8,
) -> Entity:
    seg = document.segments[segment_order]
    start = seg.text.index(text)
    return Entity(
        type=etype,
        text=text,
        segment_order=segment_order,
        start=start,
        end=start + len(text),
        source=Source.RULE,
        confidence=confidence,
    )


def test_sweep_finds_bare_value_without_trigger() -> None:
    """Голое значение без триггерного слова рядом (реальный дефект Д13:
    `2025.334807` на стр. 45, где рядом нет слова «договор»)."""
    document = _document(
        [
            "Номер договора: 2025.334807 от 01.01.2026",
            "Оплата произведена по реквизитам: 2025.334807",
        ]
    )
    accepted = [_entity(document, 0, "2025.334807")]

    found = sweep(document, accepted)

    assert len(found) == 1, found
    assert found[0].segment_order == 1
    assert found[0].text == "2025.334807"
    assert found[0].type is EntityType.CONTRACT_NUMBER
    assert found[0].source is Source.RULE
    assert found[0].confidence == 0.8


def test_sweep_respects_word_boundaries() -> None:
    """`6663057404` не должен найтись внутри `16663057404` — граница слова
    обязательна (план, шаг 8: «иначе `144` найдётся внутри `1440`»)."""
    document = _document(
        [
            "ИНН 6663057404 указан в реквизитах",
            "Соседний номер 16663057404 не является тем же ИНН",
        ]
    )
    accepted = [_entity(document, 0, "6663057404", etype=EntityType.INN)]

    found = sweep(document, accepted)

    assert found == []


def test_sweep_does_not_duplicate_existing_entity() -> None:
    """Значение, уже принятое в каждом сегменте, где оно встречается, —
    досматривать нечего, дублей быть не должно."""
    document = _document(
        [
            "Мокина Светлана Владимировна подписала документ",
            "Мокина Светлана Владимировна упомянута снова",
        ]
    )
    accepted = [
        _entity(document, 0, "Мокина Светлана Владимировна", etype=EntityType.PERSON),
        _entity(document, 1, "Мокина Светлана Владимировна", etype=EntityType.PERSON),
    ]

    found = sweep(document, accepted)

    assert found == []


def test_sweep_ignores_short_and_unlisted_values() -> None:
    """Значения короче `MIN_VALUE_LEN` и типы вне белого списка не досматриваются."""
    document = _document(
        ["Итого 12345 к оплате 500500 руб", "Ещё раз 12345 и 500500 руб упомянуты"]
    )
    short_value = _entity(document, 0, "12345", etype=EntityType.CONTRACT_NUMBER)
    not_whitelisted = _entity(document, 0, "500500", etype=EntityType.MONEY)

    assert sweep(document, [short_value]) == []
    assert sweep(document, [not_whitelisted]) == []


def test_sweep_is_deterministic() -> None:
    """Два прогона дают идентичный результат в одном и том же порядке —
    значения по (тип, значение), сегменты по order, вхождения по смещению."""
    document = _document(
        [
            "Номер договора: 2025.334807",
            "2025.334807 голое значение",
            "Мокина Светлана Владимировна подписала",
            "Мокина Светлана Владимировна ещё раз",
        ]
    )
    accepted = [
        _entity(document, 0, "2025.334807"),
        _entity(document, 2, "Мокина Светлана Владимировна", etype=EntityType.PERSON),
    ]

    first = sweep(document, accepted)
    second = sweep(document, accepted)

    assert first == second
    assert [(e.segment_order, e.start) for e in first] == sorted(
        (e.segment_order, e.start) for e in first
    )
