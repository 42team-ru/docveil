"""Схемы `report.json`/конвертов паузы графа — веб-слой поверх `masker.report`.

Модели здесь не строят отчёт и не имеют предметной логики — это только форма
того, что уже собирают `masker.report.payload.build_report_payload` и узлы
графа (`masker.graph.nodes._build_report_dict`, `questions.py`,
`review.py`). Одна и та же структура обслуживает три ручки:
`GET /runs/{id}/report` (`ReportOut` целиком), `GET /runs/{id}/questions`
(`AskEnvelopeOut`) и `GET /runs/{id}/review` (`ReviewEnvelopeOut`, где
`report` — тот же `ReportOut`).

Раздел, чья форма ещё не устоялась и различается по формату документа
(`document_coverage`) или зависит от деталей другого агента, не
типизированного здесь (`render_degradations`, группы ответов в `decisions`),
оставлен как `dict`/`list[dict]` — типизировать угадыванием хуже, чем
признать словарём: несовпадение формы `response_model` тише проглотит
незнакомое поле, чем ошибку в придуманном типе.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from masker.model import Action, ConfidenceLevel


class AnchorOut(BaseModel):
    """Адресация фрагмента в документ — `entities[]`/`chunks[]`."""

    format: str
    label: str
    locator: list[str | int]


class ProfileAnchorOut(BaseModel):
    """Тот же якорь, но с именем поля `fmt` — так его кладёт `graph/serde.py`
    внутри `profile_judge` (историческое расхождение, не переименовывать
    без синхронной правки обеих сторон)."""

    fmt: str
    label: str
    locator: list[str | int]


class EntityBareOut(BaseModel):
    """Сущность без адресации в план — `profile_judge.candidates[]`."""

    type: str
    text: str
    normalized: str
    source: str
    confidence: float
    level: ConfidenceLevel
    segment_order: int
    start: int
    end: int
    anchor: AnchorOut


class EntityRecordOut(EntityBareOut):
    """Сущность, уже размеченная планом — `report.entities[]`."""

    ref: str
    marker: str
    group_id: str
    decision: Action | None = None
    decided_by: str | None = None
    reason: str | None = None


class PiiEntryOut(EntityRecordOut):
    """То же самое, но внутри `chunks[].pii[]` — со смещениями в тексте чанка."""

    chunk_start: int
    chunk_end: int


class ChunkOut(BaseModel):
    """Абзац/сегмент документа — `report.chunks[]`."""

    id: str
    segment_order: int
    start: int
    end: int
    text: str
    annotated_text: str
    pii_count: int
    pii: list[PiiEntryOut]
    anchor: AnchorOut


class SummaryOut(BaseModel):
    """Сводка по документу — `report.summary`."""

    entities_total: int
    by_type: dict[str, int]
    by_source: dict[str, int]
    #: Р8 — сколько сущностей на каждом уровне уверенности.
    by_level: dict[str, int]
    minimum_confidence: float | None


class DetectionCoverageOut(BaseModel):
    """Какие запрошенные типы движок умеет искать — `report.detection_coverage`."""

    requested_types: list[str]
    active_detector_types: list[str]
    requested_without_detector: list[str]


class PlanGroupOut(BaseModel):
    """Группа замен — `report.plan.groups[]` и `report.review_possible[]`."""

    id: str
    marker: str
    type: str
    type_title: str
    profile_id: str
    ref_count: int
    sample: str
    #: Р8 — лучший уровень среди ссылок группы; "" — уровень неизвестен.
    level: Literal["", "confirmed", "probable", "possible"]


class MaskPlanSkippedOut(BaseModel):
    count: int
    by_reason: dict[str, int]


class MaskPlanOut(BaseModel):
    """План замен — `report.plan`."""

    requested_types: list[str]
    groups: list[PlanGroupOut]
    skipped: MaskPlanSkippedOut


class ProfileMemberEntityOut(BaseModel):
    """Сущность внутри `profile_judge.profiles[].members[].entity`."""

    type: str
    text: str
    normalized: str
    confidence: float
    source: str
    level: ConfidenceLevel
    segment_order: int
    start: int
    end: int


class ProfileMemberOut(BaseModel):
    ref: str
    anchor: ProfileAnchorOut
    entity: ProfileMemberEntityOut


class ProfileOut(BaseModel):
    """Профиль стороны — `report.profile_judge.profiles[]`."""

    id: str
    role_id: str
    role_title: str
    marker_label: str
    confidence: float
    role_confidence: float
    source: str
    evidence: list[str]
    members: list[ProfileMemberOut]


class VerdictOut(BaseModel):
    """Решение судьи по одной сущности — `profile_judge.verdicts[]`."""

    ref: str
    action: Action
    confidence: float
    reason: str
    profile_id: str
    question_id: str


class JudgeQuestionOut(BaseModel):
    """Вопрос судьи о повторяющемся значении — `profile_judge.questions[]`."""

    id: str
    kind: str
    key: str
    prompt: str
    options: list[str]
    default: str
    refs: list[str]
    anchors: list[ProfileAnchorOut]


class ProfileJudgeOut(BaseModel):
    """Профили сторон и вердикты судьи — `report.profile_judge`."""

    profiles: list[ProfileOut]
    #: Ссылки на сущности вне всех профилей.
    unassigned: list[str]
    candidates: list[EntityBareOut]
    llm_calls: int
    diagnostics: list[str]
    verdicts: list[VerdictOut]
    questions: list[JudgeQuestionOut]


class ContractPartyOut(BaseModel):
    """Сторона в карточке договора — `contract_summary.customer`/`.supplier`."""

    name: str | None
    role_title: str | None
    inn: str | None
    ogrn: str | None


class ContractSummaryOut(BaseModel):
    """Карточка договора — `report.contract_summary`."""

    customer: ContractPartyOut | None
    supplier: ContractPartyOut | None
    federal_law: list[str]
    contract_amount: str | None
    delivery_periods: list[str]
    payment_terms: str | None
    contract_number: str | None
    generated_at: str
    llm_calls: int


class DecisionOverriddenOut(BaseModel):
    """Проигравшее решение, перекрытое итоговым — `decisions.by_ref[].overridden[]`."""

    action: Action
    decided_by: str
    question_id: str
    reason: str


class RefDecisionOut(BaseModel):
    """Итоговое решение по одной ссылке — `report.decisions.by_ref[]`."""

    ref: str
    action: Action
    decided_by: str
    question_id: str
    reason: str
    overridden: list[DecisionOverriddenOut] = Field(default_factory=list)


class CriticalUnmaskedOut(BaseModel):
    """Снятие маски с критичного типа/профиля — `decisions.critical_unmasked[]`."""

    question_id: str
    kind: str
    target: str
    count: int


class GroupAnswerOut(BaseModel):
    """Итог группового вопроса (по типу/профилю) — `decisions.types[]`/`.profiles[]`."""

    id: str
    kind: str
    target: str
    answer: str
    source: Literal["human", "default"]


class EntityQuestionSummaryOut(BaseModel):
    """Итог вопроса судьи — `decisions.entity_questions[]`."""

    id: str
    prompt: str
    answer: str
    source: Literal["human", "default"]


class DecisionsOut(BaseModel):
    """Решения движка по документу — `report.decisions`."""

    mode: Literal["interactive", "non_interactive", "unknown"]
    thread_id: str
    by_ref: list[RefDecisionOut]
    types: list[GroupAnswerOut] = Field(default_factory=list)
    profiles: list[GroupAnswerOut] = Field(default_factory=list)
    entity_questions: list[EntityQuestionSummaryOut] = Field(default_factory=list)
    critical_unmasked: list[CriticalUnmaskedOut] = Field(default_factory=list)
    #: Идентификаторы вопросов — см. `masker.policy.agent.PolicyResult`.
    unanswered_defaults: list[str] = Field(default_factory=list)
    ignored_answers: list[str] = Field(default_factory=list)
    invalid_answers: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class CertificateCheckOut(BaseModel):
    """Один пункт сертификата обезличивания — `certificate.checks[]`."""

    name: str
    ok: bool
    detail: str


class CertificateOut(BaseModel):
    """Сертификат обезличивания (план М3) — `report.certificate` и
    `report.validation.certificate` (тот же объект, продублирован для
    доступа одним взглядом, см. `graph/nodes.py::_build_report_dict`)."""

    ok: bool
    checks: list[CertificateCheckOut]


class LayoutOut(BaseModel):
    """Сохранность текстового слоя PDF вне замен — `validation.layout[]`."""

    artifact: str
    removed_chars: int
    inserted_chars: int
    pages: list[int]
    first_diff: str


class ValidationSkippedOut(BaseModel):
    """`validation`, когда проверять было нечего (`preview_only`)."""

    status: Literal["skipped"]
    reason: str


class ValidationCheckedOut(BaseModel):
    """`validation` после прогона `ValidateAgent`."""

    status: Literal["checked"]
    ok: bool
    checked_artifacts: list[str]
    checked_parts: list[str]
    leaked_count: int
    residual_count: int
    layout: list[LayoutOut]
    certificate: CertificateOut | None


ValidationOut = Annotated[
    ValidationSkippedOut | ValidationCheckedOut, Field(discriminator="status")
]


class MarkerLegendItemOut(BaseModel):
    """Строка легенды сокращений маркера — `report.marker_legend[]`."""

    shown_label: str
    canonical_label: str
    pages: list[int]


class ReportOut(BaseModel):
    """`report.json` целиком — то, что отдаёт узел `report` (`masker.graph.nodes`)."""

    report_version: int
    input: str
    format: str
    preview_only: bool
    selected_types: list[str]
    entity_count: int
    chunk_count: int
    summary: SummaryOut
    detection_coverage: DetectionCoverageOut
    #: Форма зависит от формата документа (docx/pdf/xlsx) — см. `report/coverage.py`.
    document_coverage: dict[str, Any]
    entities: list[EntityRecordOut]
    chunks: list[ChunkOut]
    limitations: list[str]
    #: Р8, «снять одним кликом» — группы уровня `possible`; пусто без плана.
    review_possible: list[PlanGroupOut]
    plan: MaskPlanOut | None = None
    profile_judge: ProfileJudgeOut | None = None
    contract_summary: ContractSummaryOut | None = None
    decisions: DecisionsOut | None = None
    validation: ValidationOut
    #: Дубль `report["leaked"]` — `TASKS.md`/Т1.9 ссылаются на него по имени.
    leaked: list[dict[str, Any]]
    #: Один элемент на замену, где лестница отступления реально сработала;
    #: сырой вход для `marker_legend` — форма зависит от рендера (Р7/М1).
    render_degradations: list[dict[str, Any]]
    marker_legend: list[MarkerLegendItemOut]
    #: Дубль `validation.layout` на верхнем уровне (план T2.2.2, шаг 5).
    layout: list[LayoutOut]
    #: Дубль `validation.certificate` на верхнем уровне (план М3).
    certificate: CertificateOut | None = None


class AskDocumentOut(BaseModel):
    name: str
    format: str


class QuestionOut(BaseModel):
    """Один вопрос оператору — `questions.json`/`AskEnvelopeOut.questions[]`."""

    id: str
    kind: Literal["type", "profile", "entity"]
    target: str
    title: str
    prompt: str
    options: list[str]
    default: str
    critical: bool
    found: int
    samples: list[str]
    anchors: list[str]


class AskEnvelopeOut(BaseModel):
    """Конверт паузы `ask_human` — `GET /runs/{id}/questions`."""

    schema_version: int
    thread_id: str
    document: AskDocumentOut
    questions: list[QuestionOut]


class ReviewEnvelopeOut(BaseModel):
    """Конверт паузы раунда правок — `GET /runs/{id}/review`."""

    schema_version: int
    thread_id: str
    document: AskDocumentOut
    report: ReportOut
