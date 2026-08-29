"""Контракты, общие для всех агентов.

Единственное место, где определены типы, пересекающие границы агентов.
Менять сигнатуры здесь — значит править всех потребителей.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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


class Party(StrEnum):
    """Роль стороны договора."""

    SUPPLIER = "supplier"
    BUYER = "buyer"
    THIRD_PARTY = "third_party"
    UNKNOWN = "unknown"


class Source(StrEnum):
    """Чем найдена сущность. Попадает в отчёт для ручной валидации."""

    RULE = "rule"  # регулярка + контрольная сумма
    NER = "ner"  # локальная модель
    LLM = "llm"  # арбитр
    USER = "user"  # подтверждено человеком


@dataclass(frozen=True, slots=True)
class Anchor:
    """Место сегмента в исходном файле. Форма зависит от формата.

    Наружу трактуется как непрозрачный ключ: сравнивать можно, разбирать —
    только адаптеру того формата, который его выдал.
    """

    fmt: str  # "docx" | "xlsx" | "pdf"
    locator: tuple[Any, ...]  # (part, para, run) / (sheet, cell) / (page, span)
    page: int | None = None  # для отчёта, человекочитаемо
    label: str = ""  # "Лист «Смета», D14" — тоже для отчёта


@dataclass(slots=True)
class Segment:
    """Непрерывный кусок текста документа с якорем."""

    text: str
    anchor: Anchor
    order: int  # позиция в линейном обходе документа
    is_table: bool = False


class MaskStyle(StrEnum):
    """Стиль мазка. Один план маскирования — два разных документа.

    BLACK отдают контрагенту, HIGHLIGHT проверяет человек. В обоих случаях
    исходный текст физически удалён: чёрный прямоугольник поверх текста —
    не обезличивание, а иллюзия.
    """

    BLACK = "black"
    HIGHLIGHT = "highlight"


@dataclass(slots=True)
class Entity:
    """Найденная сущность: что, где, кем найдено и насколько уверенно."""

    type: EntityType
    text: str  # исходное значение как в документе
    segment_order: int
    start: int  # смещения внутри Segment.text
    end: int
    source: Source
    confidence: float = 1.0
    party: Party = Party.UNKNOWN
    normalized: str = ""  # ключ согласованности: одна сущность — один маркер
    profile_id: str = ""  # к какому субъекту относится

    @property
    def key(self) -> tuple[EntityType, str]:
        return (self.type, self.normalized or self.text.casefold())

    @property
    def id(self) -> str:
        """Стабильный идентификатор: по нему человек отвечает судье.

        Детерминирован по содержанию, а не по порядку обхода: два прогона
        на одном документе дают одинаковые идентификаторы.
        """
        raw = f"{self.type}|{self.text}|{self.segment_order}|{self.start}"
        return hashlib.blake2s(raw.encode(), digest_size=6).hexdigest()


@dataclass(slots=True)
class Profile:
    """Профиль субъекта: все сущности одного лица или организации вместе.

    Смысл группировки в трёх вещах. Роль (поставщик/покупатель) — свойство
    субъекта, а не отдельного ИНН. Маркер становится читаемым:
    `[ПОСТАВЩИК-ДИРЕКТОР]` вместо `[ФИО-3]`, и обезличенный договор остаётся
    понятным. И судья проверяет профиль целиком одним вызовом модели вместо
    пяти по числу реквизитов.
    """

    id: str
    party: Party = Party.UNKNOWN
    display_name: str = ""  # для отчёта: «АО «Триема» (поставщик)»
    members: list[Entity] = field(default_factory=list)
    confidence: float = 1.0

    def of_type(self, t: EntityType) -> list[Entity]:
        return [e for e in self.members if e.type == t]


@dataclass(slots=True)
class Replacement:
    """Одна выполненная замена. Строка отчёта."""

    entity: Entity
    marker: str
    anchor: Anchor


@dataclass(slots=True)
class Document:
    """Разобранный документ. То, с чем работают все агенты после Ingest."""

    path: str
    fmt: str
    segments: list[Segment]
    meta: dict[str, str] = field(default_factory=dict)  # автор, заголовок и пр.
    ocr_used: bool = False
    parties: dict[Party, str] = field(default_factory=dict)

    def text(self) -> str:
        """Линейный текст документа — вход для NER и LLM."""
        return "\n".join(s.text for s in self.segments)


@dataclass(slots=True)
class Question:
    """Уточняющий вопрос пользователю от JudgeAgent.

    Вопросы задаются пачкой в одном прерывании графа. Про критичные типы
    вопросов не бывает — их маскируют молча, см. `CRITICAL_TYPES`.
    """

    entity_id: str
    text: str
    options: list[str] = field(default_factory=list)
    profile_id: str = ""


@dataclass(slots=True)
class MaskResult:
    """Итог работы пайплайна: три артефакта плюс доказательства."""

    artifacts: dict[str, str]  # "black" / "highlight" / "report" -> путь
    replacements: list[Replacement]
    profiles: list[Profile] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    leaked: list[str] = field(default_factory=list)  # непустое = провал
    ocr_used: bool = False
    elapsed_sec: float = 0.0
