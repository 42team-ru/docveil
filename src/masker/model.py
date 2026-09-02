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
    USER = "user"  # пользовательский детектор (custom types, T1.13)


@dataclass(frozen=True, slots=True)
class Anchor:
    """Место сегмента в исходном файле.

    Наружу — непрозрачный ключ: сравнивать можно, разбирать — только
    адаптеру своего формата.
    """

    fmt: str  # "docx" | "xlsx" | "pdf"
    locator: tuple[str | int | float, ...]  # docx: ("body", idx) | pdf: ("page", n, x0, y0, x1, y1)
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

    type: str  # id из EntityTypeRegistry; встроенные перечислены в EntityType
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


def is_critical(entity_type: str) -> bool:
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


@dataclass(frozen=True, slots=True)
class MaskGroup:
    """Группа сущностей с одним значением и одним маркером.

    Согласованность псевдонимов держится на группе, а не на отдельной
    сущности: все ``Entity`` с одним ``mask.keys.group_key`` и одним
    профилем попадают в одну группу и получают один и тот же ``marker``
    — см. T1.6 (``docs/plans/T1.6-T1.8-plan-validate.md``).
    """

    id: str  # "G1", по порядку первого вхождения в документе
    key: str  # ключ согласованности, см. mask/keys.py::group_key
    type: str  # id из EntityTypeRegistry
    marker: str  # "[ПОСТАВЩИК-ИНН-2]"
    profile_id: str  # "" — сущность без профиля
    role_label: str  # "ПОСТАВЩИК" | "СТОРОНА-2" | "" (без профиля)
    number: int  # порядковый номер внутри пары (role_label, type), от 1
    refs: tuple[str, ...]  # ссылки EntityIndex, в текстовом порядке
    sample: str  # первое встреченное написание — для отчёта


@dataclass(frozen=True, slots=True)
class Replacement:
    """Одна замена: что, где, на что.

    Поля ``entity`` и ``marker`` — контракт, на который уже написан
    ``eval.py`` (``result.replacements``, ``repl.entity.type``,
    ``repl.entity.text``): переименовывать их нельзя, иначе сломается ещё
    не подключённая метрика.
    """

    ref: str
    entity: Entity
    marker: str
    group_id: str
    profile_id: str
    anchor: Anchor


@dataclass(frozen=True, slots=True)
class SkippedRef:
    """Сущность, не попавшая в план, и почему."""

    ref: str
    type: str  # id из EntityTypeRegistry
    reason: str  # "type_not_requested" | "kept" | "no_anchor"


@dataclass(frozen=True, slots=True)
class MaskPlan:
    """Результат ``PlanAgent``: что и как маскируется во всём документе."""

    replacements: tuple[Replacement, ...]  # в текстовом порядке
    groups: tuple[MaskGroup, ...]  # в порядке номеров
    skipped: tuple[SkippedRef, ...]
    requested_types: tuple[str, ...]  # отсортированные значения


@dataclass(frozen=True, slots=True)
class Leak:
    """Одна найденная утечка исходных данных или их остаточный след.

    Таксономия ``kind`` («detector» | «raw» | «metadata») и разбиение на
    ``ValidationReport.leaked``/``.residual`` — см. раздел «Таксономия
    утечек» плана T1.8.
    """

    kind: str  # "detector" | "raw" | "metadata"
    artifact: str  # имя файла артефакта
    part: str  # "word/document.xml" | "docProps/core.xml" | "page 3" | ""
    entity_type: str
    value: str  # исходная строка или найденный текст
    ref: str = ""
    group_id: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ArtifactLayout:
    """Диагностика сохранности текстового слоя вне замен одного PDF-артефакта
    (план T2.2.2, шаг 4). Только PDF: DOCX не редактируется вырезанием
    глифов по прямоугольнику, там нет геометрии, которую можно перепутать.

    ``removed_chars`` — непробельные символы ожидаемого текста (страница
    минус диапазоны ``Replacement``), которых не нашлось в артефакте: Д10 —
    редакция стёрла что-то за пределами своей замены. ``inserted_chars`` —
    непробельные символы артефакта сверх ожидаемого (не считая вхождений
    маркеров плана). ``pages`` и ``first_diff`` — где смотреть глазами,
    чтобы не гадать по одной цифре.
    """

    artifact: str
    removed_chars: int
    inserted_chars: int
    pages: tuple[int, ...]  # номера страниц (0-based) с расхождением
    first_diff: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Итог проверки обезличенных артефактов ``ValidateAgent``."""

    leaked: tuple[Leak, ...]  # провал прогона
    residual: tuple[Leak, ...]  # найдено, но не провал — см. таксономию
    checked_artifacts: tuple[str, ...]
    checked_parts: tuple[str, ...]
    ok: bool
    #: Сохранность вёрстки PDF вне замен (план T2.2.2, шаг 4) — пусто для
    #: прогонов, где ``source`` не передан ``ValidateAgent.validate`` или
    #: артефакты не PDF.
    layout: tuple[ArtifactLayout, ...] = ()
