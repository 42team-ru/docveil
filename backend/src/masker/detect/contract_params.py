"""Детекторы коммерческих параметров договора: сумма и срок поставки (Фаза 1 плана).

``ContractAmountDetector`` — находит денежную сумму договора: ищет числа с
рублёвым суффиксом и проверяет, есть ли рядом (в том же или соседнем сегменте)
ключевые слова «цена договора», «сумма договора» и т.д. Если контекст есть —
тип ``contract_amount``, иначе сущность не испускается (это не общий детектор
денег, а только цены договора).

``DeliveryPeriodDetector`` — находит срок поставки/выполнения по regex-шаблонам
вида «в течение 30 рабочих дней», «не позднее 5 дней с момента» и т.д.

Оба детектора не пересекаются по результатам с правилами (``RuleDetector``):
они испускают типы ``contract_amount`` и ``delivery_period``, которых в PATTERNS
нет, поэтому в ``DetectAgent._resolve_overlaps`` конфликтов не возникает.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from masker.detect.normalize import normalize_value
from masker.model import Document, Entity, EntityType, Segment, Source

# ---------------------------------------------------------------------------
# ContractAmountDetector
# ---------------------------------------------------------------------------

#: Числовая сумма в рублях: «1 234 567,89 руб.», «250 000 (Двести... ) рублей»,
#: «1000000 руб.». Неразрывный пробел — типичный разделитель разрядов.
_MONEY_RE = re.compile(
    r"(?<!\d)"
    r"(\d[\d\s ]*(?:[.,]\d{1,2})?)"
    r"\s*(?:рублей|рубл[её]й|руб\.?|₽)",
    re.IGNORECASE,
)

#: Признаки «цена договора» — контекстное окно ±500 символов от суммы.
_AMOUNT_KEYWORDS = (
    "цена договора",
    "цена контракта",
    "стоимость договора",
    "стоимость контракта",
    "сумма договора",
    "общая стоимость",
    "цена поставки",
    "цена работ",
    "цена услуг",
    "итоговая стоимость",
)

#: Размер контекстного окна (в символах) по каждую сторону от суммы.
_AMOUNT_CONTEXT_RADIUS = 500

#: Количество соседних сегментов для расширения контекста.
_AMOUNT_SEG_LOOKAROUND = 2

CONFIDENCE = 0.90


def _amount_context(
    segments_by_order: Sequence[Segment], seg_order: int, start: int, end: int
) -> str:
    """Текст окна: собственный сегмент с радиусом + соседние сегменты."""
    seg_texts = {seg.order: seg.text for seg in segments_by_order}
    own = seg_texts.get(seg_order, "")
    context_parts = [own[max(0, start - _AMOUNT_CONTEXT_RADIUS) : end + _AMOUNT_CONTEXT_RADIUS]]
    for delta in range(-_AMOUNT_SEG_LOOKAROUND, _AMOUNT_SEG_LOOKAROUND + 1):
        if delta == 0:
            continue
        neighbour = seg_texts.get(seg_order + delta)
        if neighbour:
            context_parts.append(neighbour)
    return " ".join(context_parts).casefold()


def _has_amount_context(context: str) -> bool:
    return any(kw in context for kw in _AMOUNT_KEYWORDS)


class ContractAmountDetector:
    """Денежная сумма договора с контекстным фильтром (Фаза 1, план)."""

    name = "contract_amount"
    source = Source.RULE
    priority = 85
    types: frozenset[str] = frozenset({EntityType.CONTRACT_AMOUNT})

    def detect(self, document: Document) -> list[Entity]:
        segments_sorted = sorted(document.segments, key=lambda s: s.order)
        found: list[Entity] = []
        for seg in segments_sorted:
            for m in _MONEY_RE.finditer(seg.text):
                context = _amount_context(segments_sorted, seg.order, m.start(), m.end())
                if not _has_amount_context(context):
                    continue
                value = seg.text[m.start() : m.end()]
                found.append(
                    Entity(
                        type=EntityType.CONTRACT_AMOUNT,
                        text=value,
                        segment_order=seg.order,
                        start=m.start(),
                        end=m.end(),
                        source=Source.RULE,
                        confidence=CONFIDENCE,
                        normalized=normalize_value(EntityType.CONTRACT_AMOUNT, value),
                    )
                )
        return found


# ---------------------------------------------------------------------------
# DeliveryPeriodDetector
# ---------------------------------------------------------------------------

#: Шаблоны для срока поставки/выполнения.
_DELIVERY_PATTERNS = [
    # «в течение 30 рабочих дней»
    re.compile(
        r"в\s+течение\s+\d+\s*(?:(?:рабочих|календарных)\s+)?(?:дн[её]й|дня|суток)",
        re.IGNORECASE,
    ),
    # «не позднее 5 (пяти) рабочих дней с момента ...»
    re.compile(
        r"не\s+позднее\s+\d+\s*(?:\([^)]+\)\s*)?(?:рабочих|календарных)?\s*(?:дн[её]й|дня|суток)",
        re.IGNORECASE,
    ),
    # «срок поставки — 10 рабочих дней»
    re.compile(
        r"срок[аи]?\s+(?:поставки|поставок|отгрузки|выполнения|оказания)\s*[-—–:]*\s*"
        r"\d+\s*(?:рабочих|календарных)?\s*(?:дн[её]й|дня|суток)",
        re.IGNORECASE,
    ),
    # «10 рабочих дней с момента/с даты/со дня»
    re.compile(
        r"\d+\s+(?:рабочих|календарных)\s+(?:дн[её]й|дня|суток)\s+(?:с|со)\s+(?:момента|дня|даты)",
        re.IGNORECASE,
    ),
]


class DeliveryPeriodDetector:
    """Срок поставки/выполнения по regex-шаблонам (Фаза 1, план)."""

    name = "delivery_period"
    source = Source.RULE
    priority = 85
    types: frozenset[str] = frozenset({EntityType.DELIVERY_PERIOD})

    def detect(self, document: Document) -> list[Entity]:
        found: list[Entity] = []
        for seg in document.segments:
            for pattern in _DELIVERY_PATTERNS:
                for m in pattern.finditer(seg.text):
                    value = m.group()
                    if any(
                        e.segment_order == seg.order and e.start < m.end() and m.start() < e.end
                        for e in found
                    ):
                        continue
                    found.append(
                        Entity(
                            type=EntityType.DELIVERY_PERIOD,
                            text=value,
                            segment_order=seg.order,
                            start=m.start(),
                            end=m.end(),
                            source=Source.RULE,
                            confidence=CONFIDENCE,
                            normalized=normalize_value(EntityType.DELIVERY_PERIOD, value),
                        )
                    )
        return found
