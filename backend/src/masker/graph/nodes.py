"""Узлы графа: extract → detect → profile → judge → policy → ask_human/apply.

LLM в ``State`` не кладётся: узлы, которым он нужен, собираются фабриками
(``make_profile_node``, ``make_judge_node``), замыкающими ``RunDeps``. Это
даёт один и тот же провод CLI и веб-серверу — меняется только вызывающий и
чекпойнтер, а не логика узлов (требование заказчика №6, ``AGENTS.md``).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from langgraph.types import interrupt

from masker.detect import (
    AddressDetector,
    DateDetector,
    DetectAgent,
    RuleDetector,
    default_detectors,
)
from masker.detect.base import EntityDetector
from masker.detect.config_detector import ConfigDetector
from masker.detect.contract_params import (
    ContractAmountDetector,
    DeliveryPeriodDetector,
    PaymentTermsDetector,
)
from masker.detect.result import DetectionResult, build_pii_chunks
from masker.entity_types import EntityTypeRegistry
from masker.graph.questions import build_ask_payload, parse_answers
from masker.graph.review import (
    KEEP_ACTION,
    build_review_payload,
    parse_review_edits,
)
from masker.graph.serde import (
    anchor_from_dict,
    decisions_to_dicts,
    entity_from_dict,
    entity_to_dict,
    plan_from_dict,
    plan_to_dict,
    policy_questions_from_dicts,
    policy_questions_to_dicts,
    profiles_from_dicts,
    profiles_to_dicts,
    questions_from_dicts,
    questions_to_dicts,
    verdicts_from_dicts,
    verdicts_to_dicts,
)
from masker.graph.state import State
from masker.highlight import DEFAULT_HIGHLIGHT_BACKGROUND
from masker.highlights import build_regions_by_ref, page_infos_for_report
from masker.ingest.docx_ingest import ingest_docx
from masker.ingest.image_ingest import ingest_image
from masker.ingest.image_meta import SUPPORTED_SUFFIXES as _IMAGE_SUFFIXES
from masker.ingest.pdf_ingest import ingest_pdf
from masker.ingest.xlsx_ingest import ingest_xlsx
from masker.judge import JudgeAgent
from masker.judge.agent import JudgeResult
from masker.llm import FakeProvider, LLMProvider, TracingProvider
from masker.mask import PlanAgent
from masker.mask.select import resolve_requested_types
from masker.model import (
    Action,
    DecisionSource,
    Document,
    Entity,
    Question,
    Segment,
    Source,
)
from masker.ocr.provider import OCRProvider
from masker.policy.agent import CriticalUnmask, GroupAnswer, PolicyAgent
from masker.profile import ProfileAgent
from masker.profile.agent import ProfileResult
from masker.refs import EntityIndex
from masker.render import docx_preview as docx_preview_module
from masker.render import docx_redact as docx_redact_module
from masker.render import pdf_render as pdf_render_module
from masker.render import xlsx_redact as xlsx_redact_module
from masker.report.coverage import (
    detection_coverage,
    docx_coverage,
    image_coverage,
    pdf_coverage,
    xlsx_coverage,
)
from masker.report.payload import (
    _leak_record,
    _validation_record,
    _validation_skipped,
    build_report_payload,
    marker_legend,
    verifier_record,
)
from masker.telemetry import RUNTIME_METRICS_NAME, LLMPricing, MeteringProvider, report_telemetry
from masker.typeconfig import CustomTypeSpec, load_type_config
from masker.validate import ValidateAgent

if TYPE_CHECKING:
    from masker.ingest.image_meta import ImageMetadata

StageObserver = Callable[[str, str, str], None]


@dataclass(frozen=True, slots=True)
class RunDeps:
    """Внешние зависимости узлов графа: провайдер LLM, трейсер, каталог артефактов.

    Не входит в ``State`` (только JSON) — узлы замыкают эти зависимости через
    фабрики (``make_profile_node`` и т.д.), поэтому вызывающий (CLI сегодня,
    веб завтра) сам решает, каким провайдером, чекпойнтером и каталогом
    пользоваться. ``artifact_dir`` не в ``State``: ``Path`` не JSON, каталог
    не входит в идентичность прогона, и ``--resume`` обязан иметь право
    указать другой каталог, не мутируя чекпойнт (раздел 4 плана T1.10).
    """

    llm: LLMProvider | None = None
    tracer: TracingProvider | None = None
    artifact_dir: Path | None = None
    ocr: OCRProvider | None = None
    pricing: LLMPricing | None = None
    stage_observer: StageObserver | None = field(default=None, compare=False, repr=False)
    _meter: MeteringProvider | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.llm is not None:
            object.__setattr__(self, "_meter", MeteringProvider(self.llm, self.pricing))

    @contextmanager
    def llm_for_stage(self, stage: str) -> Iterator[LLMProvider | None]:
        """Передать узлу провайдер с пометкой узла, не зная его реализации."""
        if self._meter is None:
            yield None
            return
        with self._meter.for_stage(stage):
            yield self._meter

    def metering_offset(self) -> int:
        return self._meter.delta_since(0)[0] if self._meter is not None else 0

    def metering_delta(self, offset: int) -> list[dict[str, object]]:
        return self._meter.delta_since(offset)[1] if self._meter is not None else []

    def notify_stage(self, node: str, status: str, message: str = "") -> None:
        """Передать вызывающему ход графа, не добавляя UI-данные в State."""
        if self.stage_observer is not None:
            self.stage_observer(node, status, message)


def _document(state: State) -> Document:
    return Document(
        path=state.get("path", ""),
        fmt=state.get("fmt", "docx"),
        segments=[
            Segment(
                str(item["text"]),
                anchor_from_dict(item["anchor"]),
                int(item["order"]),
                # Старые чекпойнты (до T2.3) не знают об origin — дефолт
                # ``"text"`` совпадает с сегодняшним поведением.
                str(item.get("origin", "text")),
            )
            for item in state["segments"]
        ],
    )


def _registry_and_specs(
    state: State,
) -> tuple[EntityTypeRegistry, list[CustomTypeSpec]]:
    """Собрать иммутабельный реестр из JSON-спеков текущего прогона."""
    raw = state.get("options", {}).get("custom_types", [])
    specs = load_type_config({"version": 1, "types": list(raw)}) if raw else []
    registry = EntityTypeRegistry.builtin().extend(item.spec for item in specs)
    return registry, specs


def _extract(state: State, ocr: OCRProvider | None) -> dict[str, object]:
    """Разобрать документ по ``state["path"]``: формат — по расширению файла.

    DOCX, PDF и XLSX (регистронезависимо); прочие расширения — явный ``ValueError``
    с именем файла, а не тихий разбор мимо формата. Сканированный PDF идёт
    через ``ocr``; без провайдера поведение прежнее.
    """
    path = Path(state["path"])
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        document = ingest_docx(path)
        coverage = docx_coverage(path, document)
    elif suffix == ".pdf":
        document = ingest_pdf(path, ocr=ocr)
        coverage = pdf_coverage(path, document)
    elif suffix == ".xlsx":
        document = ingest_xlsx(path)
        coverage = xlsx_coverage(path, document)
    elif suffix in _IMAGE_SUFFIXES:
        # Одностраничная картинка → одностраничный PDF под капотом (см.
        # `ingest_image`); гейт документа поднимает `NotADocumentError`
        # (подкласс `ValueError`), LangGraph заворачивает её в
        # `RunFailedError` на уровне сервиса прогона.
        document = ingest_image(path, ocr=ocr)
        coverage = image_coverage(path, document)
    else:
        raise ValueError(f"неподдерживаемый формат файла: {path.name}")
    return {
        "fmt": document.fmt,
        "segments": [
            {
                "text": segment.text,
                "anchor": {
                    "fmt": segment.anchor.fmt,
                    "locator": list(segment.anchor.locator),
                    "label": segment.anchor.label,
                },
                "order": segment.order,
                "origin": segment.origin,
            }
            for segment in document.segments
        ],
        "meta": {**document.meta, "name": path.name, "format": document.fmt},
        "coverage": coverage,
    }


def extract_node(state: State) -> dict[str, object]:
    """Разобрать документ по ``state["path"]``: формат — по расширению файла.

    DOCX и PDF (регистронезависимо); прочие расширения — явный ``ValueError``
    с именем файла, а не тихий разбор мимо формата. OCR не используется —
    для OCR-прогонов используйте ``make_extract_node(deps)``.
    """
    return _extract(state, ocr=None)


def make_extract_node(deps: RunDeps) -> Callable[[State], dict[str, object]]:
    """Фабрика extract-узла с OCR из ``deps``.

    Используется в ``build_graph``, чтобы передать ``deps.ocr`` в
    ``ingest_pdf``; если ``deps.ocr is None`` — поведение как у
    ``extract_node``.
    """

    def _node(state: State) -> dict[str, object]:
        return _extract(state, ocr=deps.ocr)

    return _node


def make_detect_node(deps: RunDeps) -> Callable[[State], dict[str, object]]:
    """Собрать ``detect_node``, замыкающий ``LLMProvider`` из ``deps``.

    ``deps.llm`` идёт в детекцию по двум независимым дорожкам: в
    ``default_detectors`` — он нужен только `regex_llm_filter` executor'у
    (шаг 13 T1.13) и без пользовательских спеков не используется, — и в
    сам ``DetectAgent`` — это включает LLM-верификатор на recall (Р7,
    TASKS.md, `masker.detect.verifier.verify_recall`). ``rules_only`` не
    передаёт LLM ни туда, ни туда: «только правила» обязано означать «ни
    одного сетевого вызова», а не «без пользовательских детекторов, но с
    LLM-верификатором». Тем же приёмом, что и ``make_profile_node``,
    замыкание держит зависимость вне ``State`` (только JSON) — раздел 6
    плана T1.5.1.
    """

    def detect_node(state: State) -> dict[str, object]:
        """Трёхслойная детекция без фильтра по ``options.types`` — фильтр применяет план.

        ``options.types`` сужает только ``detection_coverage`` (что реально
        покрыто активными детекторами из запрошенного) и позже — ``PlanAgent``
        (T1.6, шаг 6). Сама детекция ничего не выбрасывает: незапрошенный
        тип обязан остаться среди найденных сущностей, иначе ``ValidateAgent``
        (T1.8) не смог бы искать в готовом артефакте утечки типов, которые
        человек не просил маскировать, но которые всё равно не должны
        читаться.
        """
        document = _document(state)
        options = state.get("options", {})
        registry, specs = _registry_and_specs(state)
        rules_only = bool(options.get("rules_only", False))
        with deps.llm_for_stage("detect") as llm:
            if rules_only:
                # DateDetector — тоже правило (regex + `datetime.date`-валидация),
                # его место в rules-only, чтобы `date`/`birth_date` не оказывались
                # в `requested_without_detector` только из-за --rules-only.
                detectors: list[EntityDetector] = [
                    RuleDetector(),
                    AddressDetector(),
                    DateDetector(),
                    ContractAmountDetector(),
                    DeliveryPeriodDetector(),
                    PaymentTermsDetector(),
                ]
                if specs:
                    detectors.append(ConfigDetector(specs))
            else:
                detectors = default_detectors(specs, llm=llm)
            verifier_llm = None if rules_only else llm
            detector = DetectAgent(detectors, registry, llm=verifier_llm)
            raw_types = options.get("types")
            selected_types = resolve_requested_types(
                tuple(str(value) for value in raw_types) if raw_types else ("all",), registry
            )
            detection = detector.detect(document)
            entities = detection.entities
        result: dict[str, object] = {
            "entities": [entity_to_dict(entity) for entity in entities],
            # Тот же ``detector``, которым только что детектировали — второй
            # DetectAgent() поднял бы Natasha ещё раз ради двух списков строк.
            "detection_coverage": detection_coverage(selected_types, detector),
        }
        # Р7-2: сводка верификатора доезжает до `report.json`. В ``State``
        # кладём уже сериализованную запись, а не ``VerifierReport``:
        # состояние графа обязано быть JSON — оно уходит в чекпойнтер и
        # переживает перезапуск процесса. ``r_filter`` здесь не считается:
        # он требует размеченного корпуса, которого у обычного документа
        # нет, и остаётся `None` — «не измерен», а не «измерен и равен нулю».
        if detection.verifier is not None:
            result["verifier"] = verifier_record(detection.verifier)
        return result

    return detect_node


def make_profile_node(deps: RunDeps) -> Callable[[State], dict[str, object]]:
    """Собрать ``profile_node``, использующий LLM из ``deps`` (не теряется)."""

    def profile_node(state: State) -> dict[str, object]:
        options = state.get("options", {})
        if not bool(options.get("profile", True)):
            # ``options.profile`` ложно (PDF-путь, R5 плана T1.10) — ни один
            # вызов LLM не имеет права произойти, а не «дёшево вернуть пустое
            # после обращения к модели».
            return {
                "profiles": [],
                "unassigned": [],
                "candidates": [],
                "llm_calls": 0,
                "diagnostics": [],
            }
        document = _document(state)
        entities = [entity_from_dict(item) for item in state["entities"]]
        with deps.llm_for_stage("profile") as llm:
            result = ProfileAgent(llm).profile(
                document, DetectionResult(entities, build_pii_chunks(document.segments, entities))
            )
        return {
            "profiles": profiles_to_dicts(result.profiles),
            "unassigned": result.unassigned,
            "candidates": [entity_to_dict(item) for item in result.candidates],
            "llm_calls": result.llm_calls,
            "diagnostics": result.diagnostics,
        }

    return profile_node


def _profile_result(state: State, document: Document) -> ProfileResult:
    return ProfileResult(
        profiles=profiles_from_dicts(state.get("profiles", [])),
        blocks=[],
        unassigned=list(state.get("unassigned", [])),
        candidates=[entity_from_dict(item) for item in state.get("candidates", [])],
        anchors={segment.order: segment.anchor for segment in document.segments},
        llm_calls=int(state.get("llm_calls", 0)),
        diagnostics=list(state.get("diagnostics", [])),
    )


def make_judge_node(deps: RunDeps) -> Callable[[State], dict[str, object]]:
    """Собрать ``judge_node``. ``JudgeAgent`` сегодня LLM не использует,

    но узел — фабрика наравне с ``profile_node``: судья исторически не
    зависел от модели, но провод остаётся однородным для обоих узлов.
    """

    def judge_node(state: State) -> dict[str, object]:
        options = state.get("options", {})
        if not bool(options.get("profile", True)):
            return {"verdicts": [], "questions": []}
        document = _document(state)
        entities = [entity_from_dict(item) for item in state["entities"]]
        registry, _ = _registry_and_specs(state)
        result = JudgeAgent(registry=registry).judge(
            DetectionResult(entities, build_pii_chunks(document.segments, entities)),
            _profile_result(state, document),
        )
        return {
            "verdicts": verdicts_to_dicts(result.verdicts),
            "questions": questions_to_dicts(result.questions),
        }

    return judge_node


def policy_node(state: State) -> dict[str, object]:
    """Построить вопросы политики по фактически найденным типам и профилям."""
    document = _document(state)
    entities = [entity_from_dict(item) for item in state["entities"]]
    detection = DetectionResult(entities, build_pii_chunks(document.segments, entities))
    profiles = _profile_result(state, document)
    allow_unmask_critical = bool(state.get("options", {}).get("unmask_critical", False))
    registry, _ = _registry_and_specs(state)
    questions = PolicyAgent(registry).questions(
        detection, profiles, allow_unmask_critical=allow_unmask_critical
    )
    return {"policy_questions": policy_questions_to_dicts(questions)}


def ask_human_node(state: State) -> dict[str, object]:
    """Ровно один LangGraph interrupt на единый конверт вопросов (раздел 5).

    Без побочных эффектов: LangGraph выполняет этот узел заново при каждом
    возобновлении приостановленного треда (проверено пробоем — раздел 2 плана
    T1.5.1), поэтому узел не пишет файлы и не меняет входной ``state``.

    Значение возобновления — конверт ``{"schema_version": ..., "answers": {...}}``,
    не голый словарь ответов: экспериментально подтверждено (langgraph
    1.2.11), что ``Command(resume={})`` с пустым словарём трактуется как
    отсутствие значения и узел ставится на паузу заново вместо возобновления —
    непустой конверт с ``schema_version`` защищает от этого при любых, в том
    числе пустых, ответах.
    """
    return {"answers": parse_answers(interrupt(build_ask_payload(state)))}


def apply_answers_node(state: State) -> dict[str, object]:
    """Применить ответы человека к вопросам судьи, обновив вердикты."""
    result = JudgeResult(
        verdicts_from_dicts(state.get("verdicts", [])),
        questions_from_dicts(state.get("questions", [])),
    )
    return {
        "verdicts": verdicts_to_dicts(
            JudgeAgent(registry=_registry_and_specs(state)[0]).apply_answers(
                result, state.get("answers", {})
            )
        )
    }


def _group_answer_to_dict(item: GroupAnswer) -> dict[str, object]:
    return {
        "id": item.id,
        "kind": item.kind,
        "target": item.target,
        "answer": item.answer,
        "source": item.source,
    }


def _critical_unmask_to_dict(item: CriticalUnmask) -> dict[str, object]:
    return {
        "question_id": item.question_id,
        "kind": item.kind,
        "target": item.target,
        "count": item.count,
    }


def finalize_node(state: State) -> dict[str, object]:
    """Свести решения судьи и политики в одно действие на каждый ``ref``.

    Алгоритм разрешения конфликтов — ``PolicyAgent.apply`` (раздел 7 плана
    T1.5.1). Запись артефактов остаётся снаружи графа — узлы не пишут файлы.
    """
    document = _document(state)
    entities = [entity_from_dict(item) for item in state["entities"]]
    detection = DetectionResult(entities, build_pii_chunks(document.segments, entities))
    profiles = _profile_result(state, document)
    verdicts = verdicts_from_dicts(state.get("verdicts", []))
    options = state.get("options", {})
    allow_unmask_critical = bool(options.get("unmask_critical", False))
    interactive = bool(options.get("interactive", False))
    # Вопросы политики и судьи строятся узлами безусловно (policy_node не
    # знает про роутер), но никто их не задавал, если прогон неинтерактивный
    # или ответы были известны заранее без прохода через ask_human — тогда
    # групповые/персональные источники не участвуют в решении вовсе, и оно
    # опирается только на уверенность судьи и защиту критичных типов.
    judge_questions = questions_from_dicts(state.get("questions", [])) if interactive else []
    policy_questions = (
        policy_questions_from_dicts(state.get("policy_questions", [])) if interactive else []
    )
    answers = state.get("answers", {})

    registry, _ = _registry_and_specs(state)
    result = PolicyAgent(registry).apply(
        detection,
        profiles,
        verdicts,
        judge_questions,
        policy_questions,
        answers,
        allow_unmask_critical=allow_unmask_critical,
    )

    return {
        "final_actions": decisions_to_dicts(result.decisions, result.overridden),
        "decisions": {
            "mode": "interactive" if options.get("interactive") else "non_interactive",
            "types": [_group_answer_to_dict(item) for item in result.types],
            "profiles": [_group_answer_to_dict(item) for item in result.profiles],
            "critical_unmasked": [
                _critical_unmask_to_dict(item) for item in result.critical_unmasked
            ],
            "unanswered_defaults": result.unanswered_defaults,
            "ignored_answers": result.ignored_answers,
            "invalid_answers": result.invalid_answers,
            "diagnostics": result.diagnostics,
        },
    }


def ask_review_node(state: State) -> dict[str, object]:
    """Второе прерывание графа: показать отчёт и принять правки оператора.

    Как и ``ask_human_node``, узел без побочных эффектов: LangGraph выполняет
    его заново при каждом возобновлении треда, поэтому он ничего не пишет и
    не меняет входной ``state``, кроме поля с правками.
    """
    return {"review_edits": parse_review_edits(interrupt(build_review_payload(state)))}


def apply_review_edits_node(state: State) -> dict[str, object]:
    """Развернуть правки оператора в сущности и решения по ссылкам.

    Три вида правок, все — через тот же путь, что и решения движка:

    1. **Снять/поставить маску** по ссылке. Снятие с критичного типа держит
       ``critical_guard``: без ``unmask_critical`` воля оператора его не
       перебивает — это тот же двойной барьер, что и на первом проходе.
    2. **Сменить тип** у сущности. Тип меняется на самой сущности, поэтому
       новый маркер построит ``PlanAgent`` — второго места, где собирается
       маркер, не появляется.
    3. **Добавить пропущенное значение.** Ищется по всему документу, а не
       только там, где оператор его выделил: одно значение — один маркер во
       всём документе (инвариант согласованности псевдонимов).

    Ссылки ``E1..En`` считаются от порядка сущностей в тексте, поэтому
    добавление сущности их сдвигает. Правки разбираются до вставки, решения
    переносятся на сущности, а не на строки-ссылки, и заново нумеруются
    после — иначе оператор снял бы маску не с того.
    """
    edits = state.get("review_edits", {})
    entities = [entity_from_dict(item) for item in state.get("entities", [])]
    registry, _ = _registry_and_specs(state)
    allow_unmask_critical = bool(state.get("options", {}).get("unmask_critical", False))

    index = EntityIndex(entities)
    by_ref = {ref: index.entity(ref) for ref in index.refs()}

    for ref, type_id in edits.get("type_overrides", {}).items():
        entity = by_ref.get(ref)
        if entity is None or type_id not in registry:
            continue
        entity.type = type_id

    # Решения переносятся с ссылок на сами объекты сущностей: после вставки
    # ручных значений те же сущности получат другие номера ссылок.
    decisions_by_entity: dict[int, dict[str, object]] = {}
    for item in state.get("final_actions", []):
        entity = by_ref.get(str(item["ref"]))
        if entity is not None:
            decisions_by_entity[id(entity)] = dict(item)

    diagnostics: list[str] = []
    for ref, action in edits.get("decisions", {}).items():
        entity = by_ref.get(ref)
        if entity is None:
            continue
        guarded = registry.is_critical(entity.type) and not allow_unmask_critical
        if action == KEEP_ACTION and guarded:
            diagnostics.append(
                f"{ref}: снятие маски с критичного типа {entity.type!r} отклонено "
                "(прогон без unmask_critical)"
            )
            decisions_by_entity[id(entity)] = {
                "ref": ref,
                "action": Action.MASK.value,
                "decided_by": DecisionSource.CRITICAL_GUARD,
                "question_id": "",
                "reason": "критичный тип: снятие маски требует явного разрешения прогона",
                "overridden": [],
            }
            continue
        decisions_by_entity[id(entity)] = {
            "ref": ref,
            "action": action,
            "decided_by": DecisionSource.ENTITY,
            "question_id": "",
            "reason": "решение оператора на экране проверки",
            "overridden": [],
        }

    document = _document(state)
    added = _manual_entities(edits.get("manual", []), document, registry)
    for entity in added:
        decisions_by_entity[id(entity)] = {
            "ref": "",
            "action": Action.MASK.value,
            "decided_by": DecisionSource.ENTITY,
            "question_id": "",
            "reason": "значение добавлено оператором на экране проверки",
            "overridden": [],
        }
    entities.extend(added)

    reindexed = EntityIndex(entities)
    final_actions: list[dict[str, object]] = []
    for ref in reindexed.refs():
        entity = reindexed.entity(ref)
        decision = decisions_by_entity.get(id(entity))
        if decision is None:
            continue
        final_actions.append({**decision, "ref": ref})

    review = dict(state.get("decisions", {}))
    review["review_diagnostics"] = diagnostics
    review["review_manual_added"] = len(added)

    return {
        "entities": [entity_to_dict(entity) for entity in entities],
        "final_actions": final_actions,
        "decisions": review,
        "options": _options_with_manual_types(state, added),
        "review_round": int(state.get("review_round", 0)) + 1,
    }


def _options_with_manual_types(state: State, added: list[Entity]) -> dict[str, object]:
    """Дописать типы добавленных вручную значений в запрошенные типы прогона.

    ``PlanAgent`` пропускает сущность, тип которой не запрошен. Без этой
    дописки значение, добавленное оператором типом вне отбора прогона, молча
    не попало бы ни в документ, ни в отчёт — оператор увидел бы, что его
    правка исчезла без объяснений.
    """
    options = dict(state.get("options", {}))
    requested = options.get("types")
    if not requested or not added:
        return options
    options["types"] = sorted({*(str(item) for item in requested), *(e.type for e in added)})
    return options


def _manual_entities(
    manual: list[dict[str, str]], document: Document, registry: EntityTypeRegistry
) -> list[Entity]:
    """Сущности для значений, добавленных оператором, — по всем вхождениям.

    Пустой результат на неизвестный тип и на значение, которого в документе
    нет: молча добавить сущность без места в тексте нельзя — рендер не найдёт,
    что заменять, а отчёт покажет замену, которой не было.
    """
    added: list[Entity] = []
    for item in manual:
        type_id = item["type"]
        text = item["text"]
        if type_id not in registry:
            continue
        for segment in document.segments:
            start = segment.text.find(text)
            while start != -1:
                added.append(
                    Entity(
                        type=type_id,
                        text=text,
                        segment_order=segment.order,
                        start=start,
                        end=start + len(text),
                        source=Source.USER,
                        confidence=1.0,
                    )
                )
                start = segment.text.find(text, start + len(text))
    return added


def needs_review(state: State) -> str:
    """Нужен ли раунд правок оператора после отчёта.

    Ровно один раунд на прогон: второй заход ведёт в конец. Иначе граф
    зациклился бы на паре ``ask_review → report``, а прогон никогда бы не
    завершился — и `resume` на нём всегда возвращал бы «жду правок».
    """
    options = state.get("options", {})
    if not bool(options.get("review", False)):
        return "end"
    if int(state.get("review_round", 0)) > 0:
        return "end"
    return "ask_review"


def needs_human(state: State) -> str:
    """Направить на ``ask_human`` только если это действительно нужно.

    Единственная защита ворот от зависания (раздел 6 плана T1.5.1):
    неинтерактивный прогон (``options.interactive`` ложно) и прогон, для
    которого ответы уже заданы заранее, идут сразу на ``apply_answers``.
    """
    options = state.get("options", {})
    interactive = bool(options.get("interactive", False))
    has_questions = bool(state.get("policy_questions")) or bool(state.get("questions"))
    already_answered = bool(state.get("answers"))
    if interactive and has_questions and not already_answered:
        return "ask_human"
    return "apply_answers"


def plan_node(state: State) -> dict[str, object]:
    """Построить план масок из решений ``finalize`` — единый источник маркеров.

    ``actions`` строится из ``final_actions`` (одна запись на ``ref`` после
    разрешения конфликтов политики и судьи, раздел 4 плана T1.5.1) — тем же
    способом, каким это делал ``cli.py::_write_graph_report`` до T1.10.
    ``requested_types`` берётся из ``options.types``: пусто — все типы, как
    и в ``PlanAgent.plan`` по умолчанию.
    """
    document = _document(state)
    entities = [entity_from_dict(item) for item in state["entities"]]
    profiles = profiles_from_dicts(state.get("profiles", []))
    options = state.get("options", {})
    registry, _ = _registry_and_specs(state)
    raw_types = options.get("types")
    requested_types = (
        resolve_requested_types(tuple(str(value) for value in raw_types), registry)
        if raw_types
        else None
    )
    actions = {
        str(item["ref"]): Action(str(item["action"])) for item in state.get("final_actions", [])
    }
    plan = PlanAgent(registry).plan(
        document,
        entities,
        profiles=profiles,
        requested_types=requested_types,
        actions=actions,
    )
    return {"plan": plan_to_dict(plan)}


def summary_node(state: State) -> dict[str, object]:
    """Совместимый офлайн-узел: поля правил без вызова LLM."""
    return _summary_node(state, llm=None)


def make_summary_node(deps: RunDeps) -> Callable[[State], dict[str, object]]:
    """Собрать summary-узел с LLM вне JSON-состояния LangGraph."""

    if isinstance(deps.llm, FakeProvider):
        # ``MASKER_LLM=fake`` — офлайн-ворота: нет ни придуманного жанра,
        # ни синтетического пересказа, и ответ-заглушка не расходуется.
        return summary_node

    def _node(state: State) -> dict[str, object]:
        with deps.llm_for_stage("summary") as llm:
            return _summary_node(state, llm=llm)

    return _node


def _summary_node(state: State, llm: LLMProvider | None) -> dict[str, object]:
    """Собрать части карточки и не дать полям договора попасть в не-договор."""
    from masker.summary import build_document_card, export_summary

    entities = [entity_from_dict(item) for item in state.get("entities", [])]
    profiles = profiles_from_dicts(state.get("profiles", []))
    llm_calls = int(state.get("llm_calls", 0))
    document = _document(state)
    # generated_at фиксируется пустой строкой: отчёт должен быть детерминированным
    # (AGENTS.md: «два прогона на одном файле дают побайтово одинаковый отчёт»).
    # Временная метка сборки хранится в артефактах файловой системы, не в отчёте.
    # Пустая строка (не None) → детерминированный вывод без datetime.now().
    # Замерено 11.09.2026 на eat-654000009321.pdf: короткий путь записи
    # кассет и граф собирали карточку разными последовательностями, из-за
    # чего полученный пересказ мог не доехать в отчёт. Один конструктор
    # сохраняет тип, пересказ и поля как единый контракт Д3.
    summary = build_document_card(
        document,
        entities,
        profiles,
        llm,
        llm_calls=llm_calls,
    )
    return {
        "contract_summary": export_summary(summary, plan_from_dict(state.get("plan", {}))),
        "summary_llm_calls": summary.llm_calls - llm_calls,
    }


#: Порядок ролей артефактов — фиксированный, не по обходу множества стилей
#: (раздел 6 плана T1.10, пункт 2): детерминизм отчёта не должен зависеть от
#: порядка, в котором вызывающий перечислил ``options.styles``.
_ARTIFACT_ROLE_ORDER: tuple[str, ...] = ("preview", "masked_highlight", "masked_black")
#: Стиль редактирующего рендера для каждой немаскировочной роли.
_STYLE_BY_ROLE: dict[str, str] = {"masked_highlight": "marker", "masked_black": "blackbox"}


def make_render_node(deps: RunDeps) -> Callable[[State], dict[str, object]]:
    """Собрать ``render_node``, пишущий файлы в ``deps.artifact_dir``.

    Рендер вызывается через модуль (``docx_redact_module.render_docx_redacted``,
    а не голое имя функции), а не напрямую импортированным именем: тест на
    утечку (шаг 6) подменяет функцию рендера через ``monkeypatch.setattr`` на
    самом модуле — при импорте по имени (``from ... import
    render_docx_redacted``) патч перестал бы попадать в цель (риск R2 плана
    T1.10, раздел 10).
    """

    def render_node(state: State) -> dict[str, object]:
        if deps.artifact_dir is None:
            # Явный провал, не тихий пропуск — «граф отработал, файлов нет, а
            # никто не заметил» (риск R6 плана T1.10) хуже, чем падение узла.
            raise ValueError("render_node: RunDeps.artifact_dir не задан")
        artifact_dir = deps.artifact_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Прогон, начавшийся с картинки, идёт через промежуточный PDF (см.
        # `ingest_image` → `meta["image_intermediate_pdf"]`); рендер PDF
        # не умеет открывать .jpg/.png, поэтому source подменяем на PDF.
        state_meta = state.get("meta", {})
        intermediate_pdf = (
            state_meta.get("image_intermediate_pdf") if isinstance(state_meta, dict) else None
        )
        source = Path(str(intermediate_pdf)) if intermediate_pdf else Path(state["path"])
        document = _document(state)
        plan = plan_from_dict(state.get("plan", {}))
        # Preview подсвечивает то же, что попало бы в маску — сущности из
        # плана, а не всё найденное детектором (сегодняшнее поведение обоих
        # путей CLI, см. раздел 5 плана T1.10).
        masked_entities = [replacement.entity for replacement in plan.replacements]
        fmt = state.get("fmt", "docx")
        suffix = {"docx": ".docx", "pdf": ".pdf", "xlsx": ".xlsx"}.get(fmt)
        if suffix is None:
            raise ValueError(f"render_node: неподдерживаемый формат {fmt!r}")
        options = state.get("options", {})
        preview_enabled = bool(options.get("preview", True))
        styles = set(options.get("styles") or ())
        highlight_background = options.get("highlight_background", DEFAULT_HIGHLIGHT_BACKGROUND)

        artifacts: list[dict[str, object]] = []
        # Спуски по лестнице отступления маркера (план T2.2.1, пачка 5,
        # решение заказчика) — не падение, факт для отчёта человеку: где
        # узкое поле не вместило полный маркер и чем реально закрыт текст.
        render_degradations: list[dict[str, object]] = []
        # План feat/highlight-coords-edits: план, обогащённый геометрией
        # ``paint_regions`` после PDF-рендера. Нужен ``_build_report_dict``
        # для секции ``entities[].regions``. Обновляем от первого
        # PDF-рендера (``masked_highlight`` идёт раньше ``masked_black`` в
        # ``_ARTIFACT_ROLE_ORDER``); повторное затирание другой ролью
        # запрещено — геометрия обеих одинакова.
        plan_with_geometry = plan
        for role in _ARTIFACT_ROLE_ORDER:
            if role == "preview":
                if not preview_enabled:
                    continue
                destination = artifact_dir / f"preview{suffix}"
                if fmt == "pdf":
                    pdf_render_module.render_pdf_preview(
                        source, destination, document, masked_entities
                    )
                elif fmt == "xlsx":
                    # XLSX-preview пока не реализован. Нельзя молча копировать
                    # источник: такой файл не подсвечен, но внешне выглядел бы
                    # как preview. Редактирующие артефакты ниже строятся всегда.
                    continue
                else:
                    docx_preview_module.render_docx_preview(
                        source, destination, document, masked_entities
                    )
                redacting = False
            else:
                style = _STYLE_BY_ROLE[role]
                if style not in styles:
                    continue
                destination = artifact_dir / f"{role}{suffix}"
                if fmt == "pdf":
                    outcome = pdf_render_module.render_pdf_redacted(
                        source,
                        destination,
                        document,
                        plan,
                        style=style,
                        highlight_background=highlight_background,
                    )
                    if plan_with_geometry is plan:
                        plan_with_geometry = dataclasses.replace(
                            plan, replacements=outcome.replacements
                        )
                    groups_by_id = {group.id: group for group in plan.groups}
                    # Только реальные спуски по лестнице отступления (план
                    # М1) — пустой ``fallback_reason`` означает «показан
                    # канонический маркер без сокращений», это не факт для
                    # отчёта человеку, а норма.
                    render_degradations.extend(
                        {
                            "artifact": destination.name,
                            "role": role,
                            "page": item.page,
                            "group_id": item.group_id,
                            "entity_type": groups_by_id[item.group_id].type
                            if item.group_id in groups_by_id
                            else "",
                            "canonical_label": groups_by_id[item.group_id].canonical_label
                            if item.group_id in groups_by_id
                            else "",
                            "shown_label": item.shown_label,
                            "font_size": item.font_size,
                            "fallback_reason": item.fallback_reason,
                        }
                        for item in outcome.markers
                        if item.fallback_reason
                    )
                elif fmt == "xlsx":
                    xlsx_redact_module.render_xlsx_redacted(
                        source, destination, document, plan, style=style
                    )
                else:
                    docx_redact_module.render_docx_redacted(
                        source,
                        destination,
                        document,
                        plan,
                        style=style,
                        highlight_background=highlight_background,
                    )
                redacting = True
            artifacts.append(
                {
                    "role": role,
                    "name": destination.name,
                    "path": str(destination),
                    "redacting": redacting,
                }
            )
        result: dict[str, object] = {
            "artifacts": artifacts,
            "render_degradations": render_degradations,
        }
        # Обновлённый план в state — только если рендер PDF действительно
        # шёл (иначе ``plan_with_geometry is plan``, обновлять нечего).
        if plan_with_geometry is not plan:
            result["plan"] = plan_to_dict(plan_with_geometry)
        return result

    return render_node


def _image_meta_from_state(state: State) -> ImageMetadata | None:
    """Восстановить `ImageMetadata` из `state["meta"]`, если исходник — картинка.

    Возвращает `None`, если ключа `image_source` нет (исходник — не картинка,
    ветка конвертации выключена). Не поднимает исключений при частично
    отсутствующих полях: если картинку прогоняли не через ingest_image
    (руками собранное state), возвращаем None и молча пропускаем экспорт.
    """
    meta = state.get("meta", {})
    if not isinstance(meta, dict) or "image_source" not in meta:
        return None
    from masker.ingest.image_meta import DEFAULT_DPI, ImageMetadata

    try:
        return ImageMetadata(
            name=str(meta["image_source"]),
            suffix=str(meta.get("image_suffix", "")),
            width=int(meta.get("image_width", 0)),
            height=int(meta.get("image_height", 0)),
            format=str(meta.get("image_format", "")),
            mode=str(meta.get("image_mode", "RGB")),
            channels=3,
            bit_depth=24,
            dpi_x=int(meta.get("image_dpi_x", DEFAULT_DPI)),
            dpi_y=int(meta.get("image_dpi_y", DEFAULT_DPI)),
            orientation=int(meta.get("image_orientation", 1)),
        )
    except (TypeError, ValueError):
        return None


def image_export_node(state: State) -> dict[str, object]:
    """Экспорт PDF-артефактов обратно в исходный формат картинки.

    Идёт после `validate_node`: валидация побайтового отсутствия исходной
    строки уже прошла на PDF-артефактах (инвариант 2 плана). Если исходник
    не картинка либо `options.image_output_format == "pdf"` — узел ничего
    не делает и не меняет `artifacts`. Иначе для каждого артефакта
    `.pdf` строится картинка тем же расширением, что у исходника, PDF
    удаляется, путь и имя в `state["artifacts"]` обновляются.
    """
    meta_image = _image_meta_from_state(state)
    if meta_image is None:
        return {}
    options = state.get("options", {})
    output_format = str(options.get("image_output_format", "original"))
    state_meta = state.get("meta", {})
    intermediate_pdf = (
        state_meta.get("image_intermediate_pdf") if isinstance(state_meta, dict) else None
    )
    if output_format != "original":
        # Пользователь попросил PDF — артефакты уже PDF, ничего не делаем;
        # промежуточный (входной) PDF тоже удаляем: он больше не нужен, и
        # оставлять его в системном tmp плодит мусор между прогонами.
        if intermediate_pdf:
            Path(str(intermediate_pdf)).unlink(missing_ok=True)
        return {}

    from masker.render.image_export import pdf_to_image

    artifacts = list(state.get("artifacts", []))
    updated: list[dict[str, object]] = []
    for item in artifacts:
        pdf_path = Path(str(item["path"]))
        if pdf_path.suffix.lower() != ".pdf":
            updated.append(dict(item))
            continue
        target = pdf_path.with_suffix(meta_image.suffix)
        pdf_to_image(pdf_path, meta_image, target)
        # PDF-артефакт не удаляем: `pipeline.mask_and_validate` вызывает
        # ValidateAgent повторно вне графа, а `ValidateAgent` не умеет
        # открывать .jpg/.png. Оставляем PDF рядом, чтобы сторонний
        # потребитель мог перепроверить прогон на «настоящем» артефакте.
        # Итоговый пользователь видит картинку по обновлённому `path`.
        updated.append(
            {
                **item,
                "name": target.name,
                "path": str(target),
            }
        )
    # Промежуточный PDF (из ingest'а) не удаляем: `mask_and_validate`
    # вызывает `ValidateAgent().validate(..., source=path)` вне графа, и
    # если source-путь — .jpg, `ValidateAgent` не умеет его открыть. Держим
    # промежуточный PDF живым до конца прогона; его удалит вызывающий,
    # когда закончит с MaskResult (см. `pipeline.mask_and_validate`).
    return {"artifacts": updated}


def validate_node(state: State) -> dict[str, object]:
    """Проверить редактирующие артефакты на утечки — утечка это данные, не исключение.

    ``preview`` не проверяется никогда: он по замыслу содержит исходный
    текст (противоречие П2 плана T1.6/T1.8). Найденная утечка кладётся в
    ``state["leaked"]`` и не прерывает граф — провалом прогона это
    становится на уровне вызывающего (раздел 5 плана T1.10).
    """
    artifacts = state.get("artifacts", [])
    redacting_paths = [Path(str(item["path"])) for item in artifacts if item.get("redacting")]
    if not redacting_paths:
        return {
            "validation": _validation_skipped("preview_only: --redact-style не задан"),
            "leaked": [],
        }
    plan = plan_from_dict(state.get("plan", {}))
    # source для layout-проверки — тот же PDF, что видел рендер: у картинки
    # `state["path"]` это .jpg/.png, а `meta["image_intermediate_pdf"]` — PDF.
    state_meta = state.get("meta", {})
    intermediate_pdf = (
        state_meta.get("image_intermediate_pdf") if isinstance(state_meta, dict) else None
    )
    source_path = Path(str(intermediate_pdf)) if intermediate_pdf else Path(state["path"])
    validation_report = ValidateAgent().validate(plan, redacting_paths, source=source_path)
    return {
        "validation": _validation_record(validation_report),
        "leaked": [_leak_record(leak) for leak in validation_report.leaked],
    }


def _pick_pdf_artifact(artifacts: list[dict[str, object]]) -> Path | None:
    """Первый попавшийся редактирующий PDF-артефакт для нормализации bbox.

    План feat/highlight-coords-edits: координаты в отчёте и координаты
    правок оператора нормализуются к размерам страниц одного и того же
    файла. Порядок ролей фиксирован (``_ARTIFACT_ROLE_ORDER``), поэтому
    ``masked_highlight.pdf`` встречается раньше ``masked_black.pdf`` — при
    любом стиле рендера победит именно тот файл, что уходит фронту.
    ``None`` — валидный ответ, если PDF-артефактов нет вовсе (docx/xlsx).
    """
    for item in artifacts:
        if not item.get("redacting"):
            continue
        raw_path = item.get("path")
        if not isinstance(raw_path, str):
            continue
        path = Path(raw_path)
        if path.suffix.lower() != ".pdf":
            continue
        return path
    return None


def _entity_questions_summary(
    questions: list[Question], answers: dict[str, str]
) -> list[dict[str, object]]:
    """Итог каждого вопроса судьи: ответ человека либо вариант по умолчанию.

    Перенесено из ``cli.py`` без изменения поведения (T1.10, шаг 7).
    """
    result: list[dict[str, object]] = []
    for question in questions:
        raw = answers.get(question.id)
        valid = raw in question.options
        result.append(
            {
                "id": question.id,
                "prompt": question.prompt,
                "answer": raw if valid else question.default,
                "source": "human" if valid else "default",
            }
        )
    return result


def make_report_node(deps: RunDeps) -> Callable[[State], dict[str, object]]:
    """Собрать ``report_node`` — структуру ``report.json`` из ``State``.

    HTML не строится здесь: ``report.html`` остаётся на стороне вызывающего
    (раздел 0 плана T1.10) — React возьмёт эту структуру из ``State``
    напрямую, минуя файл. Абсолютных путей в отчёте быть не должно: ``coverage``/
    ``detection_coverage``/``plan`` уже без путей, ``artifacts[].path`` сюда
    не копируется — только производный от него булев ``preview_only``.
    Фабрика, а не голая функция: только через ``deps.tracer`` узел узнаёт,
    шёл ли обмен с LLM через ``TracingProvider`` — от этого зависит
    предупреждение "llm-trace.*" в ``report["limitations"]``.
    """

    def report_node(state: State) -> dict[str, object]:
        result = _build_report_dict(
            state,
            llm_trace=deps.tracer is not None,
            runtime_available=deps.artifact_dir is not None,
        )
        if deps.artifact_dir is None:
            return result
        artifacts = list(state.get("artifacts", []))
        if not any(item.get("role") == "runtime_metrics" for item in artifacts):
            artifacts.append(
                {
                    "role": "runtime_metrics",
                    "name": RUNTIME_METRICS_NAME,
                    "path": str(deps.artifact_dir / RUNTIME_METRICS_NAME),
                    "redacting": False,
                }
            )
        return {**result, "artifacts": artifacts}

    return report_node


def _build_report_dict(
    state: State, *, llm_trace: bool, runtime_available: bool = False
) -> dict[str, object]:
    document = _document(state)
    entities = [entity_from_dict(item) for item in state.get("entities", [])]
    chunks = build_pii_chunks(document.segments, entities)
    options = state.get("options", {})
    registry, _ = _registry_and_specs(state)
    raw_types = options.get("types")
    selected_types = resolve_requested_types(
        tuple(str(value) for value in raw_types) if raw_types else ("all",), registry
    )

    profile_enabled = bool(options.get("profile", True))
    profile_result = _profile_result(state, document) if profile_enabled else None
    judge_result = (
        JudgeResult(
            verdicts_from_dicts(state.get("verdicts", [])),
            questions_from_dicts(state.get("questions", [])),
        )
        if profile_enabled
        else None
    )

    index = EntityIndex(entities)
    ref_by_entity_id = {id(entity): index.ref(entity) for entity in entities}

    raw_decisions = state.get("decisions", {})
    judge_questions = questions_from_dicts(state.get("questions", []))
    decisions: dict[str, object] = {
        "mode": raw_decisions.get("mode", "unknown"),
        "thread_id": str(options.get("thread_id", "")),
        "by_ref": state.get("final_actions", []),
        "types": raw_decisions.get("types", []),
        "profiles": raw_decisions.get("profiles", []),
        "entity_questions": _entity_questions_summary(
            judge_questions, dict(state.get("answers", {}))
        ),
        "critical_unmasked": raw_decisions.get("critical_unmasked", []),
        "unanswered_defaults": raw_decisions.get("unanswered_defaults", []),
        "ignored_answers": raw_decisions.get("ignored_answers", []),
        "invalid_answers": raw_decisions.get("invalid_answers", []),
        "diagnostics": raw_decisions.get("diagnostics", []),
    }

    plan = plan_from_dict(state.get("plan", {}))
    artifacts = state.get("artifacts", [])
    preview_only = not any(bool(item.get("redacting")) for item in artifacts)

    report = build_report_payload(
        Path(state["path"]),
        document,
        entities,
        chunks,
        selected_types,
        state.get("coverage", {}),
        state.get("detection_coverage", {}),
        profile_result,
        judge_result,
        llm_trace=llm_trace,
        decisions=decisions,
        ref_by_entity_id=ref_by_entity_id,
        plan=plan,
        registry=registry,
    )
    # Секция верификатора приезжает из ``detect_node`` тем же приёмом, что
    # ``validation``/``leaked`` ниже: узел, который знает факт, кладёт его в
    # состояние, а отчёт собирает готовое.
    verifier = state.get("verifier")
    if verifier:
        report["verifier"] = verifier
    report["preview_only"] = preview_only
    # План feat/highlight-coords-edits (К1): координаты сущностей и размеры
    # страниц PDF-артефакта для отрисовки на канвасе фронта. Артефакт —
    # первый попавшийся PDF из ``state["artifacts"]`` с ``redacting=True``
    # (обычно ``masked_highlight.pdf``, а если стиль ``blackbox`` — то
    # ``masked_black.pdf``). Для docx/xlsx PDF-артефакта нет и оба поля
    # пусты; ``pages: []`` и ``regions: []`` — валидный ответ, не выдумываем
    # геометрию, которой не существует.
    artifact_pdf_path = _pick_pdf_artifact(artifacts)
    regions_by_ref = build_regions_by_ref(plan, artifact_pdf_path) if plan else {}
    if regions_by_ref:
        for entity_record in report.get("entities", []):
            ref = entity_record.get("ref")
            if isinstance(ref, str) and ref in regions_by_ref:
                entity_record["regions"] = [
                    {
                        "page": bbox.page,
                        "x0": bbox.x0,
                        "y0": bbox.y0,
                        "x1": bbox.x1,
                        "y1": bbox.y1,
                    }
                    for bbox in regions_by_ref[ref]
                ]
        for chunk_record in report.get("chunks", []):
            for pii_record in chunk_record.get("pii", []):
                ref = pii_record.get("ref")
                if isinstance(ref, str) and ref in regions_by_ref:
                    pii_record["regions"] = [
                        {
                            "page": bbox.page,
                            "x0": bbox.x0,
                            "y0": bbox.y0,
                            "x1": bbox.x1,
                            "y1": bbox.y1,
                        }
                        for bbox in regions_by_ref[ref]
                    ]
    report["pages"] = page_infos_for_report(artifact_pdf_path)
    report["validation"] = state.get(
        "validation", _validation_skipped("preview_only: --redact-style не задан")
    )
    report["leaked"] = state.get("leaked", [])
    report["render_degradations"] = state.get("render_degradations", [])
    # План М1, правило 6: любое сокращение маркера — строка легенды
    # («[Ф1] = [ПОСТАВЩИК-ФИО-1], стр. 3»), а не молчаливая деградация.
    report["marker_legend"] = marker_legend(report["render_degradations"])
    # Дубль report["validation"]["layout"] на верхнем уровне — план T2.2.2,
    # шаг 5: сохранность вёрстки PDF читается тем же взглядом, что и
    # leaked/render_degradations, а не через вложенный validation.layout.
    report["layout"] = report["validation"].get("layout", [])
    # Дубль report["validation"]["certificate"] на верхнем уровне — план М3:
    # сертификат обезличивания читается одним взглядом, не через вложенный
    # validation.certificate (тот же приём, что и layout строкой выше).
    report["certificate"] = report["validation"].get("certificate")
    report["telemetry"] = report_telemetry(
        state.get("telemetry"), runtime_available=runtime_available
    )
    contract_summary = state.get("contract_summary")
    if contract_summary:
        report["contract_summary"] = contract_summary
    return {"report": report}
