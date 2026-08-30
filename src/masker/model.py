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
    locator: tuple[str | int, ...]  # docx: ("body", para_idx) | ("table", ...)
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


@dataclass(frozen=True, slots=True)
class ProfileMember:
    """Сущность профиля и её место в исходном документе."""

    entity: Entity
    anchor: Anchor
    ref: str


@dataclass(slots=True)
class Profile:
    """Детерминированная или уточнённая моделью группа одного субъекта."""

    id: str
    members: list[ProfileMember]
    role_id: str = ""
    role_title: str = ""
    marker_label: str = ""
    confidence: float = 0.0
    role_confidence: float = 0.0
    source: Source = Source.RULE
    evidence: list[str] = field(default_factory=list)


class Action(StrEnum):
    """Действие судьи над сущностью."""

    MASK = "mask"
    ASK = "ask"
    KEEP = "keep"


@dataclass(frozen=True, slots=True)
class Verdict:
    """Решение по одной сущности."""

    ref: str
    action: Action
    confidence: float
    reason: str
    profile_id: str = ""
    question_id: str = ""


@dataclass(frozen=True, slots=True)
class Question:
    """Один вопрос человеку о повторяющемся значении."""

    id: str
    kind: str
    key: str
    prompt: str
    options: tuple[str, ...]
    default: str
    refs: tuple[str, ...]
    anchors: tuple[Anchor, ...]


def is_critical(entity_type: EntityType) -> bool:
    """Вернуть, относится ли тип к типам, которые маскируются без вопроса."""
    return entity_type in CRITICAL_TYPES


#: Варианты ответа на вопрос политики или судьи. Единый набор строк для
#: всех источников решений — CLI, веб и отчёт сравнивают ответы буквально.
MASK_OPTION = "маскировать"
KEEP_OPTION = "оставить"
#: Отдельный вариант для критичных типов/профилей: обычным «оставить» снять
#: маску с критичного реквизита нельзя — см. AGENTS.md и раздел 3 плана T1.5.1.
KEEP_CRITICAL_OPTION = "оставить (осознанное решение)"


class DecisionSource:
    """Строковые константы источников решения по ссылке (``Decision.decided_by``)."""

    CRITICAL_GUARD = "critical_guard"
    ENTITY = "entity"
    PROFILE = "profile"
    TYPE = "type"
    JUDGE = "judge"
    DEFAULT = "default"


#: Порядок разрешения конфликтов между источниками решений, от самого
#: частного к самому общему. Персональное решение по сущности (``entity``)
#: сильнее решения по её профилю (``profile``), решение по профилю сильнее
#: решения по её типу (``type``). ``critical_guard`` стоит над всем и
#: применяется только пока критичный тип не подтверждён дважды — см.
#: ``PolicyAgent.apply`` и раздел 7 плана T1.5.1. Порядок фиксирован и
#: проверен тестом на любую другую перестановку.
DECISION_PRECEDENCE: tuple[str, ...] = (
    DecisionSource.CRITICAL_GUARD,
    DecisionSource.ENTITY,
    DecisionSource.PROFILE,
    DecisionSource.TYPE,
    DecisionSource.JUDGE,
    DecisionSource.DEFAULT,
)


@dataclass(frozen=True, slots=True)
class Decision:
    """Итоговое действие над одной ссылкой (``ref``) после разрешения конфликтов.

    Единица решения — ссылка на сущность, а не тип и не профиль: групповые
    ответы на вопросы политики разворачиваются в такие записи, одну на
    ``ref`` — см. раздел 4 плана T1.5.1.
    """

    ref: str
    action: Action
    decided_by: str
    question_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class PolicyQuestion:
    """Вопрос о классе сущностей: типе или профиле (субъекте), а не о ``ref``.

    В отличие от ``Question`` (вопрос про конкретную сущность с ``refs``),
    ``PolicyQuestion`` описывает группу. Разворачивание группы в решения по
    ссылкам делает предикатом ``PolicyAgent.apply``, а не список ``refs``
    внутри вопроса — см. раздел 4 плана T1.5.1.
    """

    id: str
    kind: str
    target: str
    title: str
    prompt: str
    options: tuple[str, ...]
    default: str
    critical: bool
    found: int
    by_type: tuple[tuple[str, int], ...]
    samples: tuple[str, ...]
    anchors: tuple[Anchor, ...]
    linked: tuple[str, ...]
    role_title: str = ""
