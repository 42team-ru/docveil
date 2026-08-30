"""Контракты, общие для всех агентов.

Единственное место, где определены типы, пересекающие границы агентов.
Менять сигнатуры здесь — значит править всех потребителей.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EntityType(StrEnum):
    """Типы данных, которые пользователь может попросить обезличить."""

    ORG_NAME = "org_name"
    PERSON = "person"
    INN = "inn"
    KPP = "kpp"
    OGRN = "ogrn"
    SNILS = "snils"
    BANK_ACCOUNT = "bank_account"
    BIK = "bik"
    BANK_NAME = "bank_name"
    ADDRESS = "address"
    PHONE = "phone"
    EMAIL = "email"
    PASSPORT = "passport"
    CONTRACT_NUMBER = "contract_number"
    MONEY = "money"
    DATE = "date"
    SITE = "site"


#: Типы, пропуск которых — утечка персональных/платёжных данных.
#: Для них порог recall в воротах равен 1.0.
CRITICAL_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.INN,
        EntityType.OGRN,
        EntityType.SNILS,
        EntityType.BANK_ACCOUNT,
        EntityType.PASSPORT,
    }
)


class Source(StrEnum):
    """Кем найдена сущность: слой детекции, выдавший её."""

    RULE = "rule"  # регулярка + контрольная сумма
    NER = "ner"  # локальная модель
    LLM = "llm"  # арбитр


@dataclass(frozen=True, slots=True)
class Anchor:
    """Место сегмента в исходном файле.

    Наружу — непрозрачный ключ: сравнивать можно, разбирать — только
    адаптеру своего формата.
    """

    fmt: str  # "docx" | "xlsx" | "pdf"
    locator: tuple[str | int, ...]  # docx: ("body", para_idx)
    label: str = ""  # «абзац 7» — для отчёта человеку


@dataclass(slots=True)
class Segment:
    """Непрерывный кусок текста документа с якорем."""

    text: str
    anchor: Anchor
    order: int  # плотная позиция в линейном обходе, 0..N-1


@dataclass(slots=True)
class Entity:
    """Найденная сущность: что, где, кем найдено, насколько уверенно."""

    type: EntityType
    text: str  # исходное значение как в документе
    segment_order: int
    start: int  # смещения внутри Segment.text, [start, end)
    end: int
    source: Source
    confidence: float = 1.0
    normalized: str = ""  # ключ согласованности, заполняет детектор


@dataclass(slots=True)
class Document:
    """Разобранный документ — то, с чем работают все агенты после Ingest."""

    path: str
    fmt: str
    segments: list[Segment]
    meta: dict[str, str] = field(default_factory=dict)

    def text(self) -> str:
        """Линейный текст документа — вход для NER и LLM."""
        return "\n".join(s.text for s in self.segments)
