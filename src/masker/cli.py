"""CLI для локальной проверки слоя детекции на DOCX."""

from __future__ import annotations

import argparse
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from docx import Document as open_docx

from masker.detect import AddressDetector, DetectAgent, RuleDetector
from masker.detect.ner import NatashaDetector
from masker.detect.result import DetectionResult, PiiChunk, build_pii_chunks
from masker.graph.nodes import RunDeps
from masker.graph.questions import parse_answers
from masker.graph.serde import (
    entity_from_dict,
    judge_to_dicts,
    profiles_from_dicts,
    profiles_to_dicts,
    questions_from_dicts,
    verdicts_from_dicts,
)
from masker.ingest.docx_ingest import (
    count_nested_tables,
    count_skipped_body_blocks,
    ingest_docx,
    iter_body_blocks,
)
from masker.judge import JudgeAgent
from masker.judge.agent import JudgeResult
from masker.llm import (
    LLMError,
    LLMProvider,
    TracingProvider,
    get_provider,
    load_llm_config,
    write_trace,
)
from masker.model import Document, Entity, EntityType, Question
from masker.profile import ProfileAgent
from masker.profile.agent import ProfileResult
from masker.refs import EntityIndex
from masker.render.docx_preview import render_docx_preview
from masker.report.html import render_html_report
from masker.run import (
    AlreadyFinishedError,
    RunOptions,
    RunOutcome,
    ThreadExistsError,
    UnknownThreadError,
    resume_run,
    sqlite_checkpointer_factory,
    start_run,
)

DEFAULT_OUTPUT = Path("out") / "inspect"
REPORT_VERSION = 3
WORD_TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"


def _entity_record(
    document: Document,
    entity: Entity,
    *,
    ref_by_entity_id: dict[int, str] | None = None,
    decision_by_ref: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    segment = document.segments[entity.segment_order]
    record: dict[str, Any] = {
        "type": entity.type.value,
        "text": entity.text,
        "normalized": entity.normalized,
        "source": entity.source.value,
        "confidence": entity.confidence,
        "segment_order": entity.segment_order,
        "start": entity.start,
        "end": entity.end,
        "anchor": {
            "format": segment.anchor.fmt,
            "locator": list(segment.anchor.locator),
            "label": segment.anchor.label,
        },
    }
    if ref_by_entity_id is not None:
        ref = ref_by_entity_id.get(id(entity))
        if ref is not None:
            record["ref"] = ref
            decision = (decision_by_ref or {}).get(ref)
            if decision is not None:
                record["decision"] = decision["action"]
                record["decided_by"] = decision["decided_by"]
                record["reason"] = decision["reason"]
    return record


def _chunk_record(document: Document, chunk: PiiChunk, index: int) -> dict[str, Any]:
    segment = document.segments[chunk.segment_order]
    pii: list[dict[str, Any]] = []
    for entity in chunk.entities:
        record = _entity_record(document, entity)
        record["chunk_start"] = entity.start - chunk.start
        record["chunk_end"] = entity.end - chunk.start
        pii.append(record)
    return {
        "id": f"chunk-{index:03d}",
        "segment_order": chunk.segment_order,
        "start": chunk.start,
        "end": chunk.end,
        "text": segment.text[chunk.start : chunk.end],
        "annotated_text": _annotate_chunk(segment.text, chunk),
        "pii_count": len(pii),
        "pii": pii,
        "anchor": {
            "format": segment.anchor.fmt,
            "locator": list(segment.anchor.locator),
            "label": segment.anchor.label,
        },
    }


def _annotate_chunk(text: str, chunk: PiiChunk) -> str:
    value = text[chunk.start : chunk.end]
    for entity in sorted(chunk.entities, key=lambda item: item.start, reverse=True):
        start = entity.start - chunk.start
        end = entity.end - chunk.start
        replacement = f"⟦{entity.type.value.upper()}:{value[start:end]}⟧"
        value = value[:start] + replacement + value[end:]
    return value


def _summary(entities: list[Entity]) -> dict[str, Any]:
    by_type = Counter(entity.type.value for entity in entities)
    by_source = Counter(entity.source.value for entity in entities)
    return {
        "entities_total": len(entities),
        "by_type": dict(sorted(by_type.items())),
        "by_source": dict(sorted(by_source.items())),
        "minimum_confidence": min((entity.confidence for entity in entities), default=None),
    }


def _document_coverage(source: Path, document: Document) -> dict[str, Any]:
    source_docx = open_docx(str(source))
    nonempty_blocks = [
        (locator, paragraph.text)
        for locator, paragraph in iter_body_blocks(source_docx)
        if paragraph.text.strip()
    ]
    body_paragraphs = [text for locator, text in nonempty_blocks if locator[0] == "body"]
    table_paragraphs = [text for locator, text in nonempty_blocks if locator[0] == "table"]
    nested_tables = count_nested_tables(source_docx)
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        header_names = [
            name for name in names if name.startswith("word/header") and name.endswith(".xml")
        ]
        footer_names = [
            name for name in names if name.startswith("word/footer") and name.endswith(".xml")
        ]
        header_text_parts = sum(_xml_part_has_text(archive, name) for name in header_names)
        footer_text_parts = sum(_xml_part_has_text(archive, name) for name in footer_names)
        footnotes_name = "word/footnotes.xml"
        has_footnotes_part = footnotes_name in names
        footnotes_have_text = has_footnotes_part and _xml_part_has_text(archive, footnotes_name)
    return {
        "safe_to_export": False,
        "body": {
            "processed": True,
            "nonempty_paragraphs": len(body_paragraphs),
            "skipped_blocks": count_skipped_body_blocks(source_docx),
        },
        "tables": {
            "processed": True,
            "count": len(source_docx.tables),
            "nonempty_paragraphs": len(table_paragraphs),
            "nested_count": nested_tables,
        },
        "headers": {
            "processed": False,
            "parts": len(header_names),
            "parts_with_text": header_text_parts,
        },
        "footers": {
            "processed": False,
            "parts": len(footer_names),
            "parts_with_text": footer_text_parts,
        },
        "footnotes": {
            "processed": False,
            "part_present": has_footnotes_part,
            "has_text": footnotes_have_text,
        },
        "metadata": {
            "processed": False,
            "present_fields": sorted(document.meta),
        },
    }


def _limitations(
    coverage: dict[str, Any], *, llm_trace: bool = False, critical_unmasked: bool = False
) -> list[str]:
    limitations = [
        "Проверяются непустые абзацы основного текста и верхнеуровневых таблиц DOCX.",
        "Колонтитулы, сноски и метаданные пока не обезличиваются.",
        "Адрес собирается в пределах одного абзаца.",
        "Место рождения не покрыто (T1.16).",
        "Preview содержит исходный текст и не предназначен для передачи наружу.",
    ]
    if int(coverage["tables"]["nested_count"]) > 0:
        limitations.append(
            "Вложенные таблицы пока не разбираются; документ нельзя считать покрытым полностью."
        )
    if llm_trace:
        limitations.append(
            "llm-trace.jsonl и llm-trace.md содержат исходные PII в открытом виде "
            "и не предназначены для передачи наружу."
        )
    if critical_unmasked:
        limitations.append(
            "С части критичных реквизитов маска снята осознанным решением человека "
            "(--unmask-critical); список — decisions.critical_unmasked в report.json."
        )
    return limitations


def _xml_part_has_text(archive: zipfile.ZipFile, name: str) -> bool:
    root = ElementTree.fromstring(archive.read(name))
    return any((element.text or "").strip() for element in root.iter(WORD_TEXT_TAG))


def _detection_coverage(
    selected_types: frozenset[EntityType], detector: DetectAgent
) -> dict[str, list[str]]:
    active_types = {entity_type for item in detector.detectors for entity_type in item.types}
    available_types = active_types | NatashaDetector.types
    return {
        "requested_types": sorted(entity_type.value for entity_type in selected_types),
        "active_detector_types": sorted(entity_type.value for entity_type in active_types),
        "requested_without_detector": sorted(
            entity_type.value for entity_type in selected_types - available_types
        ),
    }


def _parse_types(value: str) -> frozenset[EntityType]:
    if value.casefold() == "all":
        return frozenset(EntityType)
    names = [name.strip().casefold() for name in value.split(",") if name.strip()]
    if not names:
        raise ValueError("список типов пуст")
    try:
        return frozenset(EntityType(name) for name in names)
    except ValueError as error:
        allowed = ", ".join(entity_type.value for entity_type in EntityType)
        raise ValueError(f"неизвестный тип {error.args[0]!r}; допустимы: all, {allowed}") from error


def _build_report(
    source: Path,
    document: Document,
    entities: list[Entity],
    chunks: list[PiiChunk],
    selected_types: frozenset[EntityType],
    detector: DetectAgent,
    profile_result: ProfileResult | None = None,
    judge_result: JudgeResult | None = None,
    llm_trace: bool = False,
    decisions: dict[str, Any] | None = None,
    ref_by_entity_id: dict[int, str] | None = None,
) -> dict[str, Any]:
    coverage = _document_coverage(source, document)
    decision_by_ref = (
        {item["ref"]: item for item in decisions["by_ref"]} if decisions is not None else None
    )
    critical_unmasked = bool(decisions and decisions.get("critical_unmasked"))
    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "input": source.name,
        "format": document.fmt,
        "preview_only": True,
        "selected_types": sorted(entity_type.value for entity_type in selected_types),
        "entity_count": len(entities),
        "chunk_count": len(chunks),
        "summary": _summary(entities),
        "detection_coverage": _detection_coverage(selected_types, detector),
        "document_coverage": coverage,
        "entities": [
            _entity_record(
                document, entity, ref_by_entity_id=ref_by_entity_id, decision_by_ref=decision_by_ref
            )
            for entity in entities
        ],
        "chunks": [
            _chunk_record(document, chunk, index) for index, chunk in enumerate(chunks, start=1)
        ],
        "limitations": _limitations(
            coverage, llm_trace=llm_trace, critical_unmasked=critical_unmasked
        ),
    }
    if profile_result is not None and judge_result is not None:
        # Сериализаторы графа задают единый публичный JSON-формат для CLI и State.
        report["profile_judge"] = {
            "profiles": profiles_to_dicts(profile_result.profiles),
            "unassigned": profile_result.unassigned,
            "candidates": [_entity_record(document, item) for item in profile_result.candidates],
            "llm_calls": profile_result.llm_calls,
            "diagnostics": profile_result.diagnostics,
            **judge_to_dicts(judge_result),
        }
    if decisions is not None:
        report["decisions"] = decisions
    return report


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def inspect_docx(
    source: Path,
    output_dir: Path,
    selected_types: frozenset[EntityType],
    *,
    rules_only: bool,
    html: bool,
    profile: bool = False,
    llm: LLMProvider | None = None,
    tracer: TracingProvider | None = None,
) -> tuple[Path, Path, Path | None, list[Entity], tuple[Path, Path] | None]:
    """Проверить один DOCX и записать JSON плюс подсвеченную копию.

    Если передан ``tracer``, ``llm`` обязан быть тем же объектом (или
    оборачивать его): рядом с отчётом появятся ``llm-trace.jsonl`` и
    ``llm-trace.md`` с дословным обменом с моделью.
    """
    document = ingest_docx(source)
    detector = DetectAgent([RuleDetector(), AddressDetector()]) if rules_only else DetectAgent()
    entities = [
        entity for entity in detector.detect(document).entities if entity.type in selected_types
    ]
    chunks = build_pii_chunks(document.segments, entities)
    detection = DetectionResult(entities=entities, chunks=chunks)
    profile_result = ProfileAgent(llm).profile(document, detection) if profile else None
    judge_result = (
        JudgeAgent().judge(detection, profile_result) if profile_result is not None else None
    )

    artifact_dir = output_dir / source.stem
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifact_dir / "report.json"
    preview_path = artifact_dir / "preview.docx"
    report = _build_report(
        source,
        document,
        detection.entities,
        chunks,
        selected_types,
        detector,
        profile_result,
        judge_result,
        llm_trace=tracer is not None,
    )
    _write_report(report_path, report)
    render_docx_preview(source, preview_path, document, entities)
    html_path = artifact_dir / "report.html" if html else None
    if html_path is not None:
        render_html_report(report, source, html_path)
    trace_paths = write_trace(artifact_dir, tracer) if tracer is not None else None
    return report_path, preview_path, html_path, entities, trace_paths


def _run_options_from_args(
    args: argparse.Namespace, selected_types: frozenset[EntityType]
) -> RunOptions:
    """Опции графа из аргументов CLI — то, из чего считается ``thread_id``."""
    types_tuple = (
        None
        if selected_types == frozenset(EntityType)
        else tuple(sorted(entity_type.value for entity_type in selected_types))
    )
    return RunOptions(
        types=types_tuple,
        rules_only=args.rules_only,
        profile=True,
        unmask_critical=args.unmask_critical,
        llm_config_id=str(args.llm_config) if args.llm_config is not None else "",
        interactive=True,
    )


def _types_from_state_options(options: dict[str, Any]) -> frozenset[EntityType]:
    """Типы, реально выбранные при прогоне — из состояния треда, а не из CLI.

    ``--resume`` не обязан повторять ``--types``/``--rules-only``: отчёт
    строится по тому, что реально было выбрано в первой фазе.
    """
    types = options.get("types")
    if not types:
        return frozenset(EntityType)
    return frozenset(EntityType(str(value)) for value in types)


def _state_db_path(args: argparse.Namespace) -> Path:
    state_db: Path | None = args.state_db
    out: Path = args.out
    return state_db if state_db is not None else out / "state.sqlite"


def _write_questions(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _print_questions(outcome: RunOutcome, questions_path: Path) -> None:
    assert outcome.payload is not None
    print(f"thread_id: {outcome.thread_id}")
    print(f"вопросов: {len(outcome.payload['questions'])}")
    for question in outcome.payload["questions"]:
        options_text = ", ".join(question["options"])
        print(f"  [{question['id']}] {question['prompt']} — варианты: {options_text}")
    print(f"  файл вопросов: {questions_path}")
    print(
        "  для ответа: masker --resume "
        f"{outcome.thread_id} --answers <файл> --out <тот же --out> --profile"
    )


def _load_answers(path: Path, parser: argparse.ArgumentParser) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        parser.error(f"не удалось прочитать --answers {path}: {error}")
        raise AssertionError("unreachable") from error
    except json.JSONDecodeError as error:
        parser.error(f"--answers {path} не является корректным JSON: {error}")
        raise AssertionError("unreachable") from error
    try:
        return parse_answers(raw)
    except ValueError as error:
        parser.error(str(error))
        raise AssertionError("unreachable") from error


def _entity_questions_summary(
    questions: list[Question], answers: dict[str, str]
) -> list[dict[str, Any]]:
    """Итог каждого вопроса судьи: ответ человека либо вариант по умолчанию."""
    result: list[dict[str, Any]] = []
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


def _write_graph_report(
    source: Path, artifact_dir: Path, outcome: RunOutcome, *, html: bool
) -> tuple[Path, Path, Path | None]:
    """Собрать report.json/preview.docx из состояния графа после ``finalize``.

    ``preview.docx`` подсвечивает только сущности, чьё итоговое действие —
    маскировать: оставленные человеком видны в отчёте (``decisions.by_ref``),
    но не в preview — раздел 10 плана T1.5.1.
    """
    document = ingest_docx(source)
    state = outcome.state
    entities = [entity_from_dict(item) for item in state.get("entities", [])]
    chunks = build_pii_chunks(document.segments, entities)
    options = state.get("options", {})
    selected_types = _types_from_state_options(options)
    rules_only = bool(options.get("rules_only", False))
    detector = DetectAgent([RuleDetector(), AddressDetector()]) if rules_only else DetectAgent()
    profile_result = ProfileResult(
        profiles=profiles_from_dicts(state.get("profiles", [])),
        blocks=[],
        unassigned=list(state.get("unassigned", [])),
        candidates=[entity_from_dict(item) for item in state.get("candidates", [])],
        anchors={segment.order: segment.anchor for segment in document.segments},
        llm_calls=int(state.get("llm_calls", 0)),
        diagnostics=list(state.get("diagnostics", [])),
    )
    judge_result = JudgeResult(
        verdicts_from_dicts(state.get("verdicts", [])),
        questions_from_dicts(state.get("questions", [])),
    )

    index = EntityIndex(entities)
    ref_by_entity_id = {id(entity): index.ref(entity) for entity in entities}
    raw_decisions = state.get("decisions", {})
    decisions: dict[str, Any] = {
        "mode": raw_decisions.get("mode", "unknown"),
        "thread_id": outcome.thread_id,
        "by_ref": state.get("final_actions", []),
        "types": raw_decisions.get("types", []),
        "profiles": raw_decisions.get("profiles", []),
        "entity_questions": _entity_questions_summary(
            judge_result.questions, dict(state.get("answers", {}))
        ),
        "critical_unmasked": raw_decisions.get("critical_unmasked", []),
        "unanswered_defaults": raw_decisions.get("unanswered_defaults", []),
        "ignored_answers": raw_decisions.get("ignored_answers", []),
        "invalid_answers": raw_decisions.get("invalid_answers", []),
        "diagnostics": raw_decisions.get("diagnostics", []),
    }
    decision_by_ref = {item["ref"]: item for item in decisions["by_ref"]}
    masked_entities = [
        entity
        for entity in entities
        if decision_by_ref.get(ref_by_entity_id.get(id(entity), ""), {}).get("action") == "mask"
    ]

    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifact_dir / "report.json"
    preview_path = artifact_dir / "preview.docx"
    report = _build_report(
        source,
        document,
        entities,
        chunks,
        selected_types,
        detector,
        profile_result,
        judge_result,
        llm_trace=False,
        decisions=decisions,
        ref_by_entity_id=ref_by_entity_id,
    )
    _write_report(report_path, report)
    render_docx_preview(source, preview_path, document, masked_entities)
    html_path = artifact_dir / "report.html" if html else None
    if html_path is not None:
        render_html_report(report, source, html_path)
    return report_path, preview_path, html_path


def _print_graph_report(
    outcome: RunOutcome, report_path: Path, preview_path: Path, html_path: Path | None
) -> None:
    print(f"прогон завершён, thread_id {outcome.thread_id}")
    print(f"  отчёт:   {report_path}")
    print(f"  preview: {preview_path}")
    if html_path is not None:
        print(f"  HTML:    {html_path}")
    print("ВАЖНО: preview содержит исходный текст и служит только для проверки детектора.")


def _start_interactive(
    source: Path,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    selected_types: frozenset[EntityType],
    llm: LLMProvider | None,
) -> int:
    """Первая фаза: начать прогон через граф, приостановиться или завершить.

    ``--answers`` без ``--ask`` — тоже первая фаза, просто с ответами,
    известными заранее: если их достаточно, прерывания не возникает.
    """
    artifact_dir = args.out / source.stem
    factory = sqlite_checkpointer_factory(_state_db_path(args))
    options = _run_options_from_args(args, selected_types)
    deps = RunDeps(llm=llm)
    pre_answers = _load_answers(args.answers, parser) if args.answers is not None else None

    try:
        outcome = start_run(
            source,
            options,
            checkpointer_factory=factory,
            deps=deps,
            thread_id=args.thread_id,
            fresh=args.fresh,
            answers=pre_answers,
        )
    except (UnknownThreadError, AlreadyFinishedError, ThreadExistsError) as error:
        print(str(error))
        return 3

    if outcome.status == "waiting":
        questions_path = artifact_dir / "questions.json"
        assert outcome.payload is not None
        _write_questions(questions_path, outcome.payload)
        _print_questions(outcome, questions_path)
        return 10

    report_path, preview_path, html_path = _write_graph_report(
        source, artifact_dir, outcome, html=args.html
    )
    _print_graph_report(outcome, report_path, preview_path, html_path)
    return 0


def _resume(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Вторая фаза: прислать ответы на приостановленный прогон."""
    if args.answers is None:
        parser.error("--resume требует --answers")
    answers = _load_answers(args.answers, parser)
    factory = sqlite_checkpointer_factory(_state_db_path(args))

    try:
        outcome = resume_run(args.resume, answers, checkpointer_factory=factory, deps=RunDeps())
    except (UnknownThreadError, AlreadyFinishedError) as error:
        print(str(error))
        return 3

    name = str(outcome.state.get("meta", {}).get("name") or "")
    stem = Path(name).stem if name else args.resume
    artifact_dir = args.out / stem

    if outcome.status == "waiting":
        questions_path = artifact_dir / "questions.json"
        assert outcome.payload is not None
        _write_questions(questions_path, outcome.payload)
        _print_questions(outcome, questions_path)
        return 10

    source = Path(str(outcome.state["path"]))
    report_path, preview_path, html_path = _write_graph_report(
        source, artifact_dir, outcome, html=args.html
    )
    _print_graph_report(outcome, report_path, preview_path, html_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="masker",
        description="Найти PII в DOCX и создать JSON-отчёт с подсвеченной preview-копией.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="один или несколько файлов .docx; не нужны вместе с --resume",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"каталог результатов (по умолчанию: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--types",
        default="all",
        help="all или типы через запятую, например: inn,person,org_name",
    )
    parser.add_argument(
        "--rules-only",
        action="store_true",
        help="не загружать Natasha, проверить только регулярки и контрольные суммы",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="создать цветной HTML-отчёт по чанкам и найденным PII",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="сгруппировать сущности в профили и добавить вердикты JudgeAgent в JSON-отчёт",
    )
    parser.add_argument(
        "--llm-config",
        type=Path,
        help="YAML-конфиг LLM; требует --profile",
    )
    parser.add_argument(
        "--allow-remote-pii",
        action="store_true",
        help="явно разрешить отправку исходных PII и контекста в удалённую LLM",
    )
    parser.add_argument(
        "--llm-trace",
        action="store_true",
        help=(
            "записать llm-trace.jsonl и llm-trace.md рядом с report.json "
            "(дословный обмен с LLM и разбор её ответа); требует --profile"
        ),
    )
    parser.add_argument(
        "--ask",
        action="store_true",
        help=(
            "остановиться на вопросах человеку, записать questions.json и выйти "
            "с кодом 10; требует --profile"
        ),
    )
    parser.add_argument(
        "--answers",
        type=Path,
        help=(
            "файл ответов (JSON); допустим и в первой фазе без --ask "
            "(тогда прерывания не возникает), и вместе с --resume"
        ),
    )
    parser.add_argument(
        "--resume",
        metavar="THREAD_ID",
        help="продолжить приостановленный прогон по идентификатору; файлы не нужны",
    )
    parser.add_argument(
        "--thread-id",
        dest="thread_id",
        help="задать идентификатор прогона вручную вместо детерминированного вычисления",
    )
    parser.add_argument(
        "--state-db",
        type=Path,
        help="файл чекпойнтера LangGraph (по умолчанию <--out>/state.sqlite)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="удалить тред перед прогоном и начать заново",
    )
    parser.add_argument(
        "--unmask-critical",
        action="store_true",
        help=(
            "разрешить снятие маски с критичных типов/профилей — первое из двух "
            "обязательных подтверждений (второе — ответ «оставить (осознанное решение)»)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.files and args.resume is None:
        parser.error("нужны файлы или --resume THREAD_ID")
    if args.files and args.resume is not None:
        parser.error("--resume не принимает позиционные файлы")
    if args.ask and not args.profile:
        parser.error("--ask требует --profile")
    if args.answers is not None and args.resume is None and not args.profile:
        parser.error("--answers без --resume требует --profile")
    if args.unmask_critical and args.resume is None and not args.profile:
        parser.error("--unmask-critical требует --profile (или используйте вместе с --resume)")
    if args.thread_id is not None and args.resume is not None:
        parser.error("--thread-id не сочетается с --resume: идентификатор уже задан позиционно")

    try:
        selected_types = _parse_types(args.types)
    except ValueError as error:
        parser.error(str(error))

    if args.resume is not None:
        return _resume(args, parser)

    invalid = [
        path for path in args.files if not path.is_file() or path.suffix.casefold() != ".docx"
    ]
    if invalid:
        parser.error("ожидались существующие DOCX: " + ", ".join(str(path) for path in invalid))
    if args.llm_config is not None and not args.profile:
        parser.error("--llm-config требует --profile")
    if args.allow_remote_pii and args.llm_config is None:
        parser.error("--allow-remote-pii требует --llm-config")
    if args.llm_trace and not args.profile:
        parser.error("--llm-trace требует --profile")
    if (args.ask or args.answers is not None) and len(args.files) != 1:
        parser.error("--ask/--answers без --resume работают ровно с одним файлом")

    llm: LLMProvider | None = None
    if args.llm_config is not None:
        try:
            config = load_llm_config(args.llm_config)
            if config.provider != "fake" and not args.allow_remote_pii:
                parser.error(
                    "OpenRouter получит исходные PII и контекст; добавьте --allow-remote-pii"
                )
            llm = get_provider(config)
        except LLMError as error:
            parser.error(str(error))
        except ValueError as error:
            parser.error(str(error))

    if args.llm_trace and llm is None:
        print("--llm-trace: LLM не подключена (--llm-config не задан), трейс не будет записан.")

    if args.ask or args.answers is not None:
        # Единственный файл (проверено выше) — человек в цикле смотрит на
        # один документ за раз, раздел 9 плана T1.5.1.
        return _start_interactive(args.files[0], args, parser, selected_types, llm)

    for source in args.files:
        tracer: TracingProvider | None = None
        run_llm = llm
        if args.llm_trace and llm is not None:
            # Новый трейсер на каждый файл: артефакт рядом с report.json
            # не должен смешивать обмен с LLM по разным документам.
            tracer = TracingProvider(llm)
            run_llm = tracer
        report_path, preview_path, html_path, entities, trace_paths = inspect_docx(
            source,
            args.out,
            selected_types,
            rules_only=args.rules_only,
            html=args.html,
            profile=args.profile,
            llm=run_llm,
            tracer=tracer,
        )
        print(f"{source}: найдено сущностей — {len(entities)}")
        print(f"  отчёт:  {report_path}")
        print(f"  preview: {preview_path}")
        if html_path is not None:
            print(f"  HTML:    {html_path}")
        if args.profile:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            profile_judge = report["profile_judge"]
            print(
                "  профили: "
                f"{len(profile_judge['profiles'])}; LLM-вызовы: {profile_judge['llm_calls']}; "
                f"вопросы: {len(profile_judge['questions'])}"
            )
            for diagnostic in profile_judge["diagnostics"]:
                print(f"  диагностика LLM: {diagnostic}")
        if trace_paths is not None:
            trace_jsonl, trace_markdown = trace_paths
            print(f"  LLM-трейс:  {trace_jsonl}")
            print(f"  LLM-трейс (человекочитаемый): {trace_markdown}")
            print(
                "  ВНИМАНИЕ: файлы llm-trace содержат исходные PII в открытом виде "
                "и не предназначены для передачи наружу."
            )
    print("ВАЖНО: preview содержит исходный текст и служит только для проверки детектора.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
