"""Узлы графа: extract → detect → profile → judge → policy → ask_human/apply.

LLM в ``State`` не кладётся: узлы, которым он нужен, собираются фабриками
(``make_profile_node``, ``make_judge_node``), замыкающими ``RunDeps``. Это
даёт один и тот же провод CLI и веб-серверу — меняется только вызывающий и
чекпойнтер, а не логика узлов (требование заказчика №6, ``AGENTS.md``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
from masker.detect.contract_params import ContractAmountDetector, DeliveryPeriodDetector
from masker.detect.result import DetectionResult, build_pii_chunks
from masker.entity_types import EntityTypeRegistry
from masker.graph.questions import build_ask_payload, parse_answers
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
from masker.ingest.docx_ingest import ingest_docx
from masker.ingest.pdf_ingest import ingest_pdf
from masker.judge import JudgeAgent
from masker.judge.agent import JudgeResult
from masker.llm import LLMProvider, TracingProvider
from masker.mask import PlanAgent
from masker.mask.select import resolve_requested_types
from masker.model import Action, Document, Question, Segment
from masker.policy.agent import CriticalUnmask, GroupAnswer, PolicyAgent
from masker.profile import ProfileAgent
from masker.profile.agent import ProfileResult
from masker.refs import EntityIndex
from masker.render import docx_preview as docx_preview_module
from masker.render import docx_redact as docx_redact_module
from masker.render import pdf_render as pdf_render_module
from masker.report.coverage import detection_coverage, docx_coverage, pdf_coverage
from masker.report.payload import (
    _leak_record,
    _validation_record,
    _validation_skipped,
    build_report_payload,
)
from masker.typeconfig import CustomTypeSpec, load_type_config
from masker.validate import ValidateAgent


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


def _document(state: State) -> Document:
    return Document(
        path=state.get("path", ""),
        fmt=state.get("fmt", "docx"),
        segments=[
            Segment(str(item["text"]), anchor_from_dict(item["anchor"]), int(item["order"]))
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


def extract_node(state: State) -> dict[str, object]:
    """Разобрать документ по ``state["path"]``: формат — по расширению файла.

    DOCX и PDF (регистронезависимо); прочие расширения — явный ``ValueError``
    с именем файла, а не тихий разбор мимо формата.
    """
    path = Path(state["path"])
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        document = ingest_docx(path)
        coverage = docx_coverage(path, document)
    elif suffix == ".pdf":
        document = ingest_pdf(path)
        coverage = pdf_coverage(path, document)
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
            }
            for segment in document.segments
        ],
        "meta": {**document.meta, "name": path.name, "format": document.fmt},
        "coverage": coverage,
    }


def make_detect_node(deps: RunDeps) -> Callable[[State], dict[str, object]]:
    """Собрать ``detect_node``, замыкающий ``LLMProvider`` из ``deps``.

    LLM нужен только `regex_llm_filter` executor'у (шаг 13 T1.13), поэтому
    в ``rules_only`` пути и в детекции без пользовательских спеков он не
    используется. Тем же приёмом, что и ``make_profile_node``, замыкание
    держит зависимость вне ``State`` (только JSON) — раздел 6 плана T1.5.1.
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
            ]
            if specs:
                detectors.append(ConfigDetector(specs))
        else:
            detectors = default_detectors(specs, llm=deps.llm)
        detector = DetectAgent(detectors, registry)
        raw_types = options.get("types")
        selected_types = resolve_requested_types(
            tuple(str(value) for value in raw_types) if raw_types else ("all",), registry
        )
        entities = detector.detect(document).entities
        return {
            "entities": [entity_to_dict(entity) for entity in entities],
            # Тот же ``detector``, которым только что детектировали — второй
            # DetectAgent() поднял бы Natasha ещё раз ради двух списков строк.
            "detection_coverage": detection_coverage(selected_types, detector),
        }

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
        result = ProfileAgent(deps.llm).profile(
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
    """Собрать карточку договора из entities + profiles — детерминированно, без LLM."""
    from masker.summary import build_summary

    entities = [entity_from_dict(item) for item in state.get("entities", [])]
    profiles = profiles_from_dicts(state.get("profiles", []))
    llm_calls = int(state.get("llm_calls", 0))
    # generated_at фиксируется пустой строкой: отчёт должен быть детерминированным
    # (AGENTS.md: «два прогона на одном файле дают побайтово одинаковый отчёт»).
    # Временная метка сборки хранится в артефактах файловой системы, не в отчёте.
    # Пустая строка (не None) → детерминированный вывод без datetime.now().
    summary = build_summary(entities, profiles, llm_calls=llm_calls, generated_at="")
    return {"contract_summary": summary.model_dump()}


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

        source = Path(state["path"])
        document = _document(state)
        plan = plan_from_dict(state.get("plan", {}))
        # Preview подсвечивает то же, что попало бы в маску — сущности из
        # плана, а не всё найденное детектором (сегодняшнее поведение обоих
        # путей CLI, см. раздел 5 плана T1.10).
        masked_entities = [replacement.entity for replacement in plan.replacements]
        fmt = state.get("fmt", "docx")
        suffix = ".pdf" if fmt == "pdf" else ".docx"
        options = state.get("options", {})
        preview_enabled = bool(options.get("preview", True))
        styles = set(options.get("styles") or ())

        artifacts: list[dict[str, object]] = []
        # Спуски по лестнице отступления маркера (план T2.2.1, пачка 5,
        # решение заказчика) — не падение, факт для отчёта человеку: где
        # узкое поле не вместило полный маркер и чем реально закрыт текст.
        render_degradations: list[dict[str, object]] = []
        for role in _ARTIFACT_ROLE_ORDER:
            if role == "preview":
                if not preview_enabled:
                    continue
                destination = artifact_dir / f"preview{suffix}"
                if fmt == "pdf":
                    pdf_render_module.render_pdf_preview(
                        source, destination, document, masked_entities
                    )
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
                        source, destination, document, plan, style=style
                    )
                    render_degradations.extend(
                        {
                            "artifact": destination.name,
                            "role": role,
                            "page": item.page,
                            "entity_type": item.entity_type,
                            "marker": item.marker,
                            "shown_as": item.shown_as,
                        }
                        for item in outcome.degradations
                    )
                else:
                    docx_redact_module.render_docx_redacted(
                        source, destination, document, plan, style=style
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
        return {"artifacts": artifacts, "render_degradations": render_degradations}

    return render_node


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
    validation_report = ValidateAgent().validate(plan, redacting_paths, source=Path(state["path"]))
    return {
        "validation": _validation_record(validation_report),
        "leaked": [_leak_record(leak) for leak in validation_report.leaked],
    }


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
        return _build_report_dict(state, llm_trace=deps.tracer is not None)

    return report_node


def _build_report_dict(state: State, *, llm_trace: bool) -> dict[str, object]:
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
    report["preview_only"] = preview_only
    report["validation"] = state.get(
        "validation", _validation_skipped("preview_only: --redact-style не задан")
    )
    report["leaked"] = state.get("leaked", [])
    report["render_degradations"] = state.get("render_degradations", [])
    # Дубль report["validation"]["layout"] на верхнем уровне — план T2.2.2,
    # шаг 5: сохранность вёрстки PDF читается тем же взглядом, что и
    # leaked/render_degradations, а не через вложенный validation.layout.
    report["layout"] = report["validation"].get("layout", [])
    contract_summary = state.get("contract_summary")
    if contract_summary:
        report["contract_summary"] = contract_summary
    return {"report": report}
