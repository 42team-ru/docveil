"""Детекторы коммерческих параметров договора: сумма и срок поставки (Фаза 1 плана).

``MoneyDetector`` — находит все денежные суммы в рублях. Он использует тот же
проверенный шаблон, что и детектор цены договора, чтобы граница суммы (включая
сумму прописью и копейки) была одинаковой для обоих типов.

``ContractAmountDetector`` — находит денежную сумму договора: ищет числа с
рублёвым суффиксом и проверяет, есть ли рядом (в том же или соседнем сегменте)
ключевые слова «цена договора», «сумма договора» и т.д. Если контекст есть —
тип ``contract_amount``, иначе сущность не испускается (это не общий детектор
денег, а только цены договора).

``DeliveryPeriodDetector`` — находит срок поставки/выполнения по regex-шаблонам
вида «в течение 30 рабочих дней», «не позднее 5 дней с момента» и т.д.

Эти детекторы не пересекаются по результатам с правилами (``RuleDetector``):
они испускают типы ``money``, ``contract_amount`` и ``delivery_period``,
которых в PATTERNS нет.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from masker.detect.normalize import normalize_value
from masker.model import Document, Entity, EntityType, Segment, Source

# ---------------------------------------------------------------------------
# PaymentTermsDetector — «Условия оплаты»
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ContractAmountDetector
# ---------------------------------------------------------------------------

#: Числовая сумма в рублях: «1 234 567,89 руб.», «250 000 (Двести... ) рублей»,
#: «1000000 руб.». Неразрывный пробел — типичный разделитель разрядов.
#: Опциональная группа `(?:\s*\([^)]{0,160}\))?` — сумма прописью в скобках
#: между цифрами и словом «рублей»: «13 439 891 (Тринадцать миллионов ...)
#: рубль 28 копеек» — обычная формулировка цены договора, найденная на
#: `contract_pdf_02_school.pdf` (Д1): без неё регулярка не находит саму цену
#: договора вовсе, потому что скобки разрывают число и единицу измерения.
#: Единица измерения — целым словом, а не префиксом: прежнее `руб\.?` цеплялось
#: к началу «рубль», спан обрывался на «руб», и в документе оставалось
#: «[СУММА-ДОГОВОРА]ль 28 копеек» — огрызок слова плюс видимые копейки, то есть
#: часть суммы не замаскирована. Копейки захватываются тем же спаном.
_MONEY_RE = re.compile(
    r"(?<!\d)"
    r"(\d[\d\s ]*)"
    r"(?:\s*\([^)]{0,160}\))?"
    r"(?:[.,]\d{1,2})?"
    r"\s*(?:₽|руб(?:\.|л[а-яё]{0,3})?)(?![а-яё])"
    r"(?:\s*\d{1,2}\s*коп(?:\.|[а-яё]{0,5})?(?![а-яё]))?",
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


class MoneyDetector:
    """Все денежные суммы в рублях по общему формату договоров."""

    name = "money"
    source = Source.RULE
    priority = 84
    types: frozenset[str] = frozenset({EntityType.MONEY})

    def detect(self, document: Document) -> list[Entity]:
        found: list[Entity] = []
        for seg in document.segments:
            for match in _MONEY_RE.finditer(seg.text):
                value = match.group()
                found.append(
                    Entity(
                        type=EntityType.MONEY,
                        text=value,
                        segment_order=seg.order,
                        start=match.start(),
                        end=match.end(),
                        source=Source.RULE,
                        confidence=CONFIDENCE,
                        normalized=normalize_value(EntityType.MONEY, value),
                    )
                )
        return found


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


_PAYMENT_CONTEXT_RADIUS = 400

#: Маркеры разделов об оплате.
_PAYMENT_SECTION_KEYWORDS = (
    "порядок расчётов",
    "порядок расчетов",
    "условия оплаты",
    "порядок оплаты",
    "оплата производится",
    "оплата осуществляется",
    "расчёты по договору",
    "расчеты по договору",
)

#: Паттерны условий оплаты (конкретные фразы, а не заголовки разделов).
_PAYMENT_PATTERNS = [
    # «оплата производится Заказчиком по факту оказания услуг ...».
    # В таких формулировках условие задаёт сам способ оплаты, но может не
    # быть процентов либо выражения «в течение N дней».
    re.compile(
        r"(?<!\w)оплата\s+(?:производится|осуществляется)\b[^.;:\n]{2,500}?"
        r"(?=\s+(?:(?:в\s+течение|за\s+каждые|не\s+позднее)\s+\d+)|[.;:\n]|$)",
        re.IGNORECASE,
    ),
    # «100% предоплата», «авансовый платёж 30%», «аванс 50%»
    re.compile(
        r"(?:\d+\s*%\s*(?:авансовый\s+платёж|авансовый\s+платеж|аванс[а-я]*|предоплат[а-я]+|оплат[а-я]+)"
        r"|(?:авансовый\s+платёж|авансовый\s+платеж|аванс[а-я]*|предоплат[а-я]+)\s*[-—–:]*\s*\d+\s*%)",
        re.IGNORECASE,
    ),
    # «оплата в течение N (рабочих|банковских|календарных) дней»
    # (?<!\w) не допускает совпадение «оплата» внутри «постоплата»
    re.compile(
        r"(?<!\w)оплат[а-я]*\s+в\s+течение\s+\d+\s*(?:\([^)]+\)\s*)?(?:рабочих|банковских|календарных)?\s*(?:дн[её]й|дня|суток)",
        re.IGNORECASE,
    ),
    # «не позднее N (рабочих|банковских|календарных) дней»
    re.compile(
        r"не\s+позднее\s+\d+\s*(?:\([^)]+\)\s*)?(?:рабочих|банковских|календарных)?\s*(?:дн[её]й|дня|суток)"
        r"(?!\s+(?:с\s+момента\s+)?(?:поставки|отгрузки|передачи|выполнения|подписания\s+акта\s+приёмки"
        r"|подписания\s+акта\s+приемки|сдачи|оказания))",
        re.IGNORECASE,
    ),
    # «в течение N банковских дней (со дня|с момента) (получения счёта|подписания акта|оплаты)»
    re.compile(
        r"в\s+течение\s+\d+\s*(?:\([^)]+\)\s*)?(?:банковских|рабочих|календарных)?\s*(?:дн[её]й|дня)\s+"
        r"(?:со?\s+(?:дня|момента|даты)\s+(?:получения\s+счёт|получения\s+счет|подписания|оплаты|выставления)|после\s+подписания)",
        re.IGNORECASE,
    ),
    # «постоплата», «100% постоплата»
    re.compile(
        r"(?:\d+\s*%\s*)?постоплат[а-я]+",
        re.IGNORECASE,
    ),
]


def _has_payment_context(context: str) -> bool:
    return any(kw in context for kw in _PAYMENT_SECTION_KEYWORDS)


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


class PaymentTermsDetector:
    """Условия оплаты: regex-паттерны с контекстным фильтром (Фаза 2, план).

    Контекстный фильтр (±400 символов + соседние сегменты) требует, чтобы
    рядом с найденной фразой был маркер раздела об оплате — «Порядок расчётов»,
    «Условия оплаты» и т.д. Это отсекает сроки оплаты в других разделах (напр.,
    штрафные санкции), которые синтаксически похожи, но семантически отличаются.
    """

    name = "payment_terms"
    source = Source.RULE
    priority = 85
    types: frozenset[str] = frozenset({EntityType.PAYMENT_TERMS})

    def detect(self, document: Document) -> list[Entity]:
        segments_sorted = sorted(document.segments, key=lambda s: s.order)
        seg_texts = {seg.order: seg.text for seg in segments_sorted}
        found: list[Entity] = []
        for seg in segments_sorted:
            for pattern in _PAYMENT_PATTERNS:
                for m in pattern.finditer(seg.text):
                    context = _payment_context(seg_texts, seg.order, m.start(), m.end())
                    if not _has_payment_context(context):
                        continue
                    value = m.group()
                    if any(
                        e.segment_order == seg.order and e.start < m.end() and m.start() < e.end
                        for e in found
                    ):
                        continue
                    found.append(
                        Entity(
                            type=EntityType.PAYMENT_TERMS,
                            text=value,
                            segment_order=seg.order,
                            start=m.start(),
                            end=m.end(),
                            source=Source.RULE,
                            confidence=CONFIDENCE,
                            normalized=normalize_value(EntityType.PAYMENT_TERMS, value),
                        )
                    )
        return found


def _payment_context(seg_texts: dict[int, str], seg_order: int, start: int, end: int) -> str:
    own = seg_texts.get(seg_order, "")
    parts = [own[max(0, start - _PAYMENT_CONTEXT_RADIUS) : end + _PAYMENT_CONTEXT_RADIUS]]
    for delta in range(-2, 3):
        if delta == 0:
            continue
        neighbour = seg_texts.get(seg_order + delta)
        if neighbour:
            parts.append(neighbour)
    return " ".join(parts).casefold()
