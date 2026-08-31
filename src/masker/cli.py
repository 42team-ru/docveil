"""CLI для локальной проверки слоя детекции на DOCX и PDF."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pymupdf
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
from masker.ingest.pdf_ingest import ingest_pdf
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
from masker.mask import PlanAgent
from masker.model import (
    Action,
    Document,
    Entity,
    EntityType,
    Leak,
    MaskPlan,
    Question,
    ValidationReport,
)
from masker.profile import ProfileAgent
from masker.profile.agent import ProfileResult
from masker.refs import EntityIndex
from masker.render.docx_preview import render_docx_preview
from masker.render.docx_redact import render_docx_redacted
from masker.render.pdf_render import render_pdf_preview, render_pdf_redacted
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
from masker.validate import ValidateAgent

DEFAULT_OUTPUT = Path("out") / "inspect"
REPORT_VERSION = 3
WORD_TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"

#: Коды возврата CLI. 0 — успех, 3 — ошибка треда графа (см. ``_resume``/
#: ``_start_interactive``), 10 — прогон приостановлен, ждёт ответов
#: человека. 4 свободен — Validate (T1.8) нашёл утечку в артефакте.
EXIT_LEAK = 4


def _entity_record(
    document: Document,
    entity: Entity,
    *,
    ref_by_entity_id: dict[int, str] | None = None,
    decision_by_ref: dict[str, dict[str, Any]] | None = None,
    marker_by_ref: dict[str, str] | None = None,
    group_id_by_ref: dict[str, str] | None = None,
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
            # Пустая строка — сущность не попала в план (`plan.skipped`):
            # фильтр по типу, решение «оставить» или отсутствие якоря.
            record["marker"] = (marker_by_ref or {}).get(ref, "")
            record["group_id"] = (group_id_by_ref or {}).get(ref, "")
    return record


def _chunk_record(
    document: Document,
    chunk: PiiChunk,
    index: int,
    *,
    ref_by_entity_id: dict[int, str] | None = None,
    marker_by_ref: dict[str, str] | None = None,
    group_id_by_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    segment = document.segments[chunk.segment_order]
    pii: list[dict[str, Any]] = []
    for entity in chunk.entities:
        record = _entity_record(
            document,
            entity,
            ref_by_entity_id=ref_by_entity_id,
            marker_by_ref=marker_by_ref,
            group_id_by_ref=group_id_by_ref,
        )
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


def _plan_record(plan: MaskPlan) -> dict[str, Any]:
    """Сериализовать план масок для report.json — раздел «Проводка плана в CLI»."""
    skipped_by_reason: Counter[str] = Counter(item.reason for item in plan.skipped)
    return {
        "requested_types": list(plan.requested_types),
        "groups": [
            {
                "id": group.id,
                "marker": group.marker,
                "type": group.type.value,
                "profile_id": group.profile_id,
                "ref_count": len(group.refs),
                "sample": group.sample,
            }
            for group in plan.groups
        ],
        "skipped": {
            "count": len(plan.skipped),
            "by_reason": dict(sorted(skipped_by_reason.items())),
        },
    }


def _leak_record(leak: Leak) -> dict[str, Any]:
    """Сериализовать одну утечку как есть — TASKS.md и T1.9 ссылаются на
    ``report["leaked"]`` по имени, поле не переименовывать."""
    return dataclasses.asdict(leak)


def _validation_record(report: ValidationReport) -> dict[str, Any]:
    """Сериализовать ``ValidationReport`` для report.json (T1.8, шаг 10).

    План перечисляет ровно эти поля — ``ok``, ``checked_artifacts``,
    ``checked_parts``, счётчики. Полный список ``residual`` намеренно не
    дублируется здесь: он не провал прогона и не относится к тому, что
    ``TASKS.md``/``T1.9`` называют по имени (``leaked`` — единственный
    список, обязанный быть top-level ключом).
    """
    return {
        "status": "checked",
        "ok": report.ok,
        "checked_artifacts": list(report.checked_artifacts),
        "checked_parts": list(report.checked_parts),
        "leaked_count": len(report.leaked),
        "residual_count": len(report.residual),
    }


def _validation_skipped(reason: str) -> dict[str, Any]:
    """Заглушка ``validation`` для случаев, где проверять нечего.

    Не провал, не «утечки нет»: явное «мы не проверяли» — противоречие П2
    плана T1.6/T1.8 (Validate не трогает ``preview.docx``, у которого нет
    редактирующего рендера, значит и результата проверки нет).
    """
    return {"status": "skipped", "reason": reason}


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
    plan: MaskPlan | None = None,
) -> dict[str, Any]:
    coverage = _document_coverage(source, document)
    decision_by_ref = (
        {item["ref"]: item for item in decisions["by_ref"]} if decisions is not None else None
    )
    critical_unmasked = bool(decisions and decisions.get("critical_unmasked"))
    marker_by_ref = (
        {repl.ref: repl.marker for repl in plan.replacements} if plan is not None else {}
    )
    group_id_by_ref = (
        {repl.ref: repl.group_id for repl in plan.replacements} if plan is not None else {}
    )
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
                document,
                entity,
                ref_by_entity_id=ref_by_entity_id,
                decision_by_ref=decision_by_ref,
                marker_by_ref=marker_by_ref,
                group_id_by_ref=group_id_by_ref,
            )
            for entity in entities
        ],
        "chunks": [
            _chunk_record(
                document,
                chunk,
                index,
                ref_by_entity_id=ref_by_entity_id,
                marker_by_ref=marker_by_ref,
                group_id_by_ref=group_id_by_ref,
            )
            for index, chunk in enumerate(chunks, start=1)
        ],
        "limitations": _limitations(
            coverage, llm_trace=llm_trace, critical_unmasked=critical_unmasked
        ),
    }
    if plan is not None:
        report["plan"] = _plan_record(plan)
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
    redact_style: str | None = None,
    profile: bool = False,
    llm: LLMProvider | None = None,
    tracer: TracingProvider | None = None,
) -> tuple[Path, Path, Path | None, Path | None, list[Entity], tuple[Path, Path] | None]:
    """Проверить один DOCX и записать JSON плюс подсвеченную копию.

    Если передан ``tracer``, ``llm`` обязан быть тем же объектом (или
    оборачивать его): рядом с отчётом появятся ``llm-trace.jsonl`` и
    ``llm-trace.md`` с дословным обменом с моделью.
    """
    document = ingest_docx(source)
    detector = DetectAgent([RuleDetector(), AddressDetector()]) if rules_only else DetectAgent()
    # Детекция больше не режется по selected_types (T1.6, шаг 6): фильтр —
    # дело плана, а не детектора. Иначе Validate (T1.8) не смог бы искать
    # утечки незапрошенных типов — их бы попросту не было среди сущностей.
    entities = detector.detect(document).entities
    chunks = build_pii_chunks(document.segments, entities)
    detection = DetectionResult(entities=entities, chunks=chunks)
    profile_result = ProfileAgent(llm).profile(document, detection) if profile else None
    judge_result = (
        JudgeAgent().judge(detection, profile_result) if profile_result is not None else None
    )

    index = EntityIndex(entities)
    ref_by_entity_id = {id(entity): index.ref(entity) for entity in entities}
    plan = PlanAgent().plan(
        document,
        entities,
        profiles=profile_result.profiles if profile_result is not None else None,
        requested_types=selected_types,
    )
    masked_entities = [replacement.entity for replacement in plan.replacements]

    artifact_dir = output_dir / source.stem
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifact_dir / "report.json"
    preview_path = artifact_dir / "preview.docx"
    redacted_path = artifact_dir / "redacted.docx" if redact_style else None
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
        ref_by_entity_id=ref_by_entity_id,
        plan=plan,
    )
    report["preview_only"] = redact_style is None
    # Preview подсвечивает то же, что попало бы в маску — сущности из плана,
    # а не всё найденное детектором (иначе подсветка перестала бы совпадать
    # с --types и с тем, что реально уходит в redacted-копию).
    render_docx_preview(source, preview_path, document, masked_entities)
    if redacted_path is not None and redact_style is not None:
        render_docx_redacted(source, redacted_path, document, plan, style=redact_style)
        validation_report = ValidateAgent().validate(plan, [redacted_path])
        report["validation"] = _validation_record(validation_report)
        report["leaked"] = [_leak_record(leak) for leak in validation_report.leaked]
    else:
        # T1.8, шаг 10: Validate проверяет только артефакты редактирующих
        # рендеров. Без --redact-style обезличенного файла не существует —
        # преview намеренно содержит исходный текст (противоречие П2 плана
        # T1.6/T1.8), проверять там утечки было бы гарантированным красным
        # результатом на артефакте, который таким и задуман.
        report["validation"] = _validation_skipped("preview_only: --redact-style не задан")
        report["leaked"] = []
    _write_report(report_path, report)
    html_path = artifact_dir / "report.html" if html else None
    if html_path is not None:
        render_html_report(report, source, html_path)
    trace_paths = write_trace(artifact_dir, tracer) if tracer is not None else None
    return report_path, preview_path, html_path, redacted_path, entities, trace_paths


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

    Маркер и план строятся тем же ``PlanAgent``, что и в простом CLI-пути
    (T1.6, шаг 6) — иначе report.json графового прогона расходился бы с
    report.json обычного по набору полей у сущностей. Настоящий
    ``masked_black``/``masked_highlight`` (взамен сегодняшнего preview с
    исходным текстом) графовый путь пока не производит — это T1.10,
    переносящий render/validate в узлы графа; здесь план используется
    только для отчёта и для отбора сущностей, попадающих в preview-подсветку.
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
    actions = {item["ref"]: Action(item["action"]) for item in decisions["by_ref"]}
    plan = PlanAgent().plan(
        document,
        entities,
        profiles=profile_result.profiles,
        requested_types=selected_types,
        actions=actions,
    )
    masked_entities = [replacement.entity for replacement in plan.replacements]

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
        plan=plan,
    )
    # Графовый путь пока не производит настоящий обезличенный артефакт —
    # preview.docx намеренно содержит исходный текст (T1.10 подключит сюда
    # render/validate как узлы графа). Validate здесь нечего проверять, но
    # поле должно быть в отчёте того же вида, что у простого CLI-пути.
    report["validation"] = _validation_skipped(
        "graph path does not produce a redacted artifact yet (T1.10)"
    )
    report["leaked"] = []
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


def _document_coverage_pdf(source: Path, document: Document) -> dict[str, Any]:
    pdf = pymupdf.open(str(source))  # type: ignore[no-untyped-call]
    page_count = len(pdf)
    pdf.close()  # type: ignore[no-untyped-call]
    return {
        "safe_to_export": False,
        "pages": {
            "processed": True,
            "count": page_count,
            "segment_count": len(document.segments),
        },
        "images": {
            "processed": False,
            "note": "Страницы-сканы (без текстового слоя) пропускаются (T2.3).",
        },
        "metadata": {
            "processed": False,
            "present_fields": sorted(document.meta),
        },
    }


def _limitations_pdf(coverage: dict[str, Any]) -> list[str]:
    return [
        "Проверяются непустые строки текстового слоя PDF.",
        "Графические объекты и изображения внутри PDF не обезличиваются (T2.3).",
        "Колонтитулы PDF могут содержать текст вне текстового слоя страницы.",
        "Preview содержит исходный текст и не предназначен для передачи наружу.",
    ]


def inspect_pdf(
    source: Path,
    output_dir: Path,
    selected_types: frozenset[EntityType],
    *,
    rules_only: bool,
    redact_style: str | None = None,
) -> tuple[Path, Path, Path | None, list[Entity]]:
    """Проверить один PDF, записать JSON + preview; опционально — redacted-копию."""
    document = ingest_pdf(source)
    detector = DetectAgent([RuleDetector(), AddressDetector()]) if rules_only else DetectAgent()
    # Детекция больше не режется по selected_types (T1.6, шаг 6) — см. тот же
    # комментарий в inspect_docx.
    entities = detector.detect(document).entities
    chunks = build_pii_chunks(document.segments, entities)

    entity_index = EntityIndex(entities)
    ref_by_entity_id = {id(entity): entity_index.ref(entity) for entity in entities}
    plan = PlanAgent().plan(document, entities, requested_types=selected_types)
    marker_by_ref = {repl.ref: repl.marker for repl in plan.replacements}
    group_id_by_ref = {repl.ref: repl.group_id for repl in plan.replacements}
    masked_entities = [replacement.entity for replacement in plan.replacements]

    artifact_dir = output_dir / source.stem
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifact_dir / "report.json"
    preview_path = artifact_dir / "preview.pdf"
    redacted_path = artifact_dir / "redacted.pdf" if redact_style else None

    coverage = _document_coverage_pdf(source, document)
    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "input": source.name,
        "format": document.fmt,
        "preview_only": redact_style is None,
        "selected_types": sorted(entity_type.value for entity_type in selected_types),
        "entity_count": len(entities),
        "chunk_count": len(chunks),
        "summary": _summary(entities),
        "detection_coverage": _detection_coverage(selected_types, detector),
        "document_coverage": coverage,
        "entities": [
            _entity_record(
                document,
                entity,
                ref_by_entity_id=ref_by_entity_id,
                marker_by_ref=marker_by_ref,
                group_id_by_ref=group_id_by_ref,
            )
            for entity in entities
        ],
        "chunks": [
            _chunk_record(
                document,
                chunk,
                index,
                ref_by_entity_id=ref_by_entity_id,
                marker_by_ref=marker_by_ref,
                group_id_by_ref=group_id_by_ref,
            )
            for index, chunk in enumerate(chunks, start=1)
        ],
        "limitations": _limitations_pdf(coverage),
        "plan": _plan_record(plan),
    }
    render_pdf_preview(source, preview_path, document, masked_entities)
    if redacted_path is not None and redact_style is not None:
        render_pdf_redacted(source, redacted_path, document, plan, style=redact_style)
        validation_report = ValidateAgent().validate(plan, [redacted_path])
        report["validation"] = _validation_record(validation_report)
        report["leaked"] = [_leak_record(leak) for leak in validation_report.leaked]
    else:
        report["validation"] = _validation_skipped("preview_only: --redact-style не задан")
        report["leaked"] = []
    _write_report(report_path, report)
    return report_path, preview_path, redacted_path, entities


def _print_leaks(source: Path, report: dict[str, Any]) -> bool:
    """Напечатать утечки в stderr, вернуть True, если они есть.

    Печать в stderr, а не в stdout: код возврата CLI и так сигнализирует
    провал, stderr — для диагностики, не для машинного разбора (машинному
    разбору служит report.json, где ``leaked`` — ключ верхнего уровня).
    """
    leaked = report.get("leaked") or []
    if not leaked:
        return False
    print(f"{source}: ValidateAgent нашёл утечки ({len(leaked)}):", file=sys.stderr)
    for item in leaked:
        print(
            f"  [{item['kind']}] {item['entity_type']} в {item['artifact']}:{item['part']} "
            f"— {item['value']!r} ({item['detail']})",
            file=sys.stderr,
        )
    return True


_SUPPORTED_SUFFIXES = frozenset({".docx", ".pdf"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="masker",
        description="Найти PII в DOCX или PDF и создать JSON-отчёт с подсвеченной preview-копией.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="один или несколько файлов .docx или .pdf; не нужны вместе с --resume",
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
        help="создать цветной HTML-отчёт по чанкам и найденным PII (только для DOCX)",
    )
    parser.add_argument(
        "--redact-style",
        choices=["marker", "blackbox"],
        default=None,
        metavar="STYLE",
        help=(
            "создать обезличенную копию (PDF и DOCX). "
            "marker — светло-серый/белый фон, маркер [ТИП]; "
            "blackbox — чёрный прямоугольник, текст визуально невидим."
        ),
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
        path
        for path in args.files
        if not path.is_file() or path.suffix.casefold() not in _SUPPORTED_SUFFIXES
    ]
    if invalid:
        parser.error(
            "ожидались существующие DOCX или PDF: " + ", ".join(str(path) for path in invalid)
        )

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

    any_leaked = False
    for source in args.files:
        if source.suffix.casefold() == ".pdf":
            # Профилирование/LLM/человек в цикле для PDF не реализованы (T2.2
            # покрывает только детекцию) — PDF всегда идёт по простому пути,
            # но настоящее редактирование (--redact-style) доступно и здесь.
            report_path, preview_path, redacted_path, entities = inspect_pdf(
                source,
                args.out,
                selected_types,
                rules_only=args.rules_only,
                redact_style=args.redact_style,
            )
            print(f"{source}: найдено сущностей — {len(entities)}")
            print(f"  отчёт:  {report_path}")
            print(f"  preview: {preview_path}")
            if redacted_path is not None:
                print(f"  redacted: {redacted_path}")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if _print_leaks(source, report):
                any_leaked = True
            continue

        tracer: TracingProvider | None = None
        run_llm = llm
        if args.llm_trace and llm is not None:
            # Новый трейсер на каждый файл: артефакт рядом с report.json
            # не должен смешивать обмен с LLM по разным документам.
            tracer = TracingProvider(llm)
            run_llm = tracer
        report_path, preview_path, html_path, redacted_path, entities, trace_paths = inspect_docx(
            source,
            args.out,
            selected_types,
            rules_only=args.rules_only,
            html=args.html,
            redact_style=args.redact_style,
            profile=args.profile,
            llm=run_llm,
            tracer=tracer,
        )
        print(f"{source}: найдено сущностей — {len(entities)}")
        print(f"  отчёт:  {report_path}")
        print(f"  preview: {preview_path}")
        if redacted_path is not None:
            print(f"  redacted: {redacted_path}")
        if html_path is not None:
            print(f"  HTML:    {html_path}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if args.profile:
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
        if _print_leaks(source, report):
            any_leaked = True
    print("ВАЖНО: preview содержит исходный текст и служит только для проверки детектора.")
    return EXIT_LEAK if any_leaked else 0


if __name__ == "__main__":
    raise SystemExit(main())
