"""Сборка структуры report.json из результатов агентов.

Перенесено из ``masker.cli`` без изменения поведения (T1.10, шаг 1):
``cli.py`` остаётся вызывающим (argparse, запись файлов, печать), а сборка
самой структуры отчёта — предметная логика, которой предстоит переехать в
узел графа ``report`` (T1.10, шаг 7).

``build_report_payload`` не открывает файлов и не строит детекторы:
``document_coverage`` и ``detection_coverage`` передаются готовыми словарями
(их считает ``masker.report.coverage`` там, где уже открыт документ).
"""

from __future__ import annotations

import dataclasses
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from masker.detect.result import PiiChunk
from masker.entity_types import EntityTypeRegistry
from masker.graph.serde import judge_to_dicts, profiles_to_dicts
from masker.judge.agent import JudgeResult
from masker.model import ConfidenceLevel, Document, Entity, Leak, MaskPlan, ValidationReport
from masker.profile.agent import ProfileResult

REPORT_VERSION = 3


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
        "type": entity.type,
        "text": entity.text,
        "normalized": entity.normalized,
        "source": entity.source.value,
        "confidence": entity.confidence,
        #: Уровень уверенности (Р8) — "confirmed"/"probable"/"possible".
        #: "possible" дублируется в ``report["review_possible"]`` по группам,
        #: чтобы UI мог снять лишнюю маску одним кликом.
        "level": entity.level.value,
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
        replacement = f"⟦{entity.type.upper()}:{value[start:end]}⟧"
        value = value[:start] + replacement + value[end:]
    return value


def _summary(entities: list[Entity]) -> dict[str, Any]:
    by_type = Counter(entity.type for entity in entities)
    by_source = Counter(entity.source.value for entity in entities)
    by_level = Counter(entity.level.value for entity in entities)
    return {
        "entities_total": len(entities),
        "by_type": dict(sorted(by_type.items())),
        "by_source": dict(sorted(by_source.items())),
        #: Р8 — сколько сущностей на каждом уровне уверенности; "possible"
        #: здесь же считает то, что попадёт в ``review_possible``.
        "by_level": dict(sorted(by_level.items())),
        "minimum_confidence": min((entity.confidence for entity in entities), default=None),
    }


def _limitations(
    coverage: dict[str, Any], *, llm_trace: bool = False, critical_unmasked: bool = False
) -> list[str]:
    limitations = [
        "Проверяются непустые абзацы основного текста и верхнеуровневых таблиц DOCX.",
        "Колонтитулы, сноски и метаданные пока не обезличиваются.",
        "Адрес собирается в пределах одного абзаца.",
        "Место рождения не покрыто (T1.16).",
        "Детектируются все календарные даты; какие из них — персональные данные, "
        "решает судья, а не детектор (T1.15).",
        "Двузначный год (12.02.25) и периоды (в марте 2025) не распознаются как даты.",
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


def _limitations_pdf(coverage: dict[str, Any]) -> list[str]:
    return [
        "Проверяются непустые строки текстового слоя PDF.",
        "Графические объекты и изображения внутри PDF не обезличиваются (T2.3).",
        "Колонтитулы PDF могут содержать текст вне текстового слоя страницы.",
        "Preview содержит исходный текст и не предназначен для передачи наружу.",
    ]


def _limitations_xlsx(coverage: dict[str, Any]) -> list[str]:
    return [
        "Проверяются непустые ячейки всех листов XLSX.",
        "Формулы читаются по кэшированному отображаемому значению; "
        "зависимые от маски формулы заменяются заглушкой.",
        "Книги со сводными таблицами отклоняются: их кэш пока нельзя безопасно очистить.",
        "Метаданные до рендера не входят в детекцию; "
        "в выходных вариантах очищаются свойства книги.",
    ]


#: Порядок «силы» уровня для группы (Р8): группа наследует самый уверенный
#: уровень, встреченный хоть у одной её сущности — единственное вхождение,
#: подтверждённое дважды или контрольной суммой, снимает подозрение со
#: всей группы одинаковых значений в документе.
_LEVEL_RANK: dict[str, int] = {
    ConfidenceLevel.POSSIBLE.value: 0,
    ConfidenceLevel.PROBABLE.value: 1,
    ConfidenceLevel.CONFIRMED.value: 2,
}


def _best_level(levels: list[str]) -> str:
    return max(levels, key=lambda level: _LEVEL_RANK.get(level, -1))


def _plan_record(
    plan: MaskPlan,
    registry: EntityTypeRegistry,
    level_by_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Сериализовать план масок для report.json — раздел «Проводка плана в CLI»."""
    skipped_by_reason: Counter[str] = Counter(item.reason for item in plan.skipped)
    level_by_ref = level_by_ref or {}
    return {
        "requested_types": list(plan.requested_types),
        "groups": [
            {
                "id": group.id,
                "marker": group.marker,
                "type": group.type,
                "type_title": registry.spec(group.type).title,
                "profile_id": group.profile_id,
                "ref_count": len(group.refs),
                "sample": group.sample,
                #: Р8 — лучший (самый уверенный) уровень среди ссылок группы;
                #: "" — ни для одной ссылки уровень не известен report'у.
                "level": _best_level(
                    [level_by_ref[ref] for ref in group.refs if ref in level_by_ref]
                )
                if any(ref in level_by_ref for ref in group.refs)
                else "",
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
    список, обязанный быть top-level ключом). ``layout`` — сохранность
    вёрстки PDF вне замен (план T2.2.2, шаг 4), пуст для DOCX и для
    прогонов без переданного ``source``. ``certificate`` — сертификат
    обезличивания (план М3, ``masker.validate.certificate``) —
    ``None``, только если ``ValidationReport`` собран в обход
    ``ValidateAgent.validate`` (тесты).
    """
    return {
        "status": "checked",
        "ok": report.ok,
        "checked_artifacts": list(report.checked_artifacts),
        "checked_parts": list(report.checked_parts),
        "leaked_count": len(report.leaked),
        "residual_count": len(report.residual),
        "layout": [dataclasses.asdict(item) for item in report.layout],
        "certificate": dataclasses.asdict(report.certificate) if report.certificate else None,
    }


def _validation_skipped(reason: str) -> dict[str, Any]:
    """Заглушка ``validation`` для случаев, где проверять нечего.

    Не провал, не «утечки нет»: явное «мы не проверяли» — противоречие П2
    плана T1.6/T1.8 (Validate не трогает ``preview.docx``, у которого нет
    редактирующего рендера, значит и результата проверки нет).
    """
    return {"status": "skipped", "reason": reason}


def marker_legend(render_degradations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Собрать строки легенды сокращений маркера (план М1, правило 6).

    Вход — ``report["render_degradations"]``: один элемент на каждую замену,
    для которой лестница отступления (``mask/labels.py::marker_ladder``)
    реально спустилась со ступени — то есть на странице показан не
    ``canonical_label``, а его сокращение (``shown_label`` != пусто и не
    равен каноническому). Заказчик видит в документе, например, ``[Ф1]`` —
    легенда объясняет, что это значит и на каких страницах встречается:
    ``{"shown_label": "[Ф1]", "canonical_label": "[ПОСТАВЩИК-ФИО-1]",
    "pages": [3, 5]}``.

    Деградации со ступенью «blank» (``shown_label == ""``, вообще ничего не
    вписано) в легенду не попадают — расшифровывать в документе нечего, там
    только закраска без текста. Страницы — человекочитаемая нумерация с 1,
    а не 0-based индекс PyMuPDF, которым оперирует рендер. Результат
    отсортирован по (``shown_label``, ``canonical_label``) — детерминизм
    отчёта не должен зависеть от порядка ``render_degradations`` на входе.
    """
    pages_by_key: dict[tuple[str, str], set[int]] = defaultdict(set)
    for item in render_degradations:
        shown = str(item.get("shown_label") or "")
        canonical = str(item.get("canonical_label") or "")
        if not shown or not canonical or shown == canonical:
            continue
        pages_by_key[(shown, canonical)].add(int(item.get("page", 0)) + 1)
    return [
        {"shown_label": shown, "canonical_label": canonical, "pages": sorted(pages)}
        for (shown, canonical), pages in sorted(pages_by_key.items())
    ]


def build_report_payload(
    source: Path,
    document: Document,
    entities: list[Entity],
    chunks: list[PiiChunk],
    selected_types: frozenset[str],
    document_coverage: dict[str, Any],
    detection_coverage: dict[str, list[str]],
    profile_result: ProfileResult | None = None,
    judge_result: JudgeResult | None = None,
    llm_trace: bool = False,
    decisions: dict[str, Any] | None = None,
    ref_by_entity_id: dict[int, str] | None = None,
    plan: MaskPlan | None = None,
    registry: EntityTypeRegistry | None = None,
) -> dict[str, Any]:
    """Собрать структуру ``report.json`` из результатов агентов.

    ``document_coverage``/``detection_coverage`` — уже посчитанные словари
    (``masker.report.coverage``): эта функция файлов не открывает и
    детекторов не строит.
    """
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
    # Р8: уровень уверенности по ссылке — читается прямо из `entities`
    # (``Entity.level`` проставляет ``DetectAgent.detect()``), а не
    # пересчитывается здесь заново — единственный источник правды один раз
    # посчитан на детекции.
    level_by_ref: dict[str, str] = (
        {
            ref_by_entity_id[id(entity)]: entity.level.value
            for entity in entities
            if id(entity) in ref_by_entity_id
        }
        if ref_by_entity_id is not None
        else {}
    )
    # ``document_coverage`` PDF-варианта не содержит ключа "tables" —
    # ``_limitations`` (докс-специфичные пункты) на нём упал бы KeyError;
    # PDF всегда идёт по ``_limitations_pdf`` (T1.10, шаг 9: единый путь
    # для обоих форматов).
    if document.fmt == "pdf":
        limitations = _limitations_pdf(document_coverage)
    elif document.fmt == "xlsx":
        limitations = _limitations_xlsx(document_coverage)
    else:
        limitations = _limitations(
            document_coverage, llm_trace=llm_trace, critical_unmasked=critical_unmasked
        )
    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "input": source.name,
        "format": document.fmt,
        "preview_only": True,
        "selected_types": sorted(selected_types),
        "entity_count": len(entities),
        "chunk_count": len(chunks),
        "summary": _summary(entities),
        "detection_coverage": detection_coverage,
        "document_coverage": document_coverage,
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
        "limitations": limitations,
    }
    review_possible: list[dict[str, Any]] = []
    if plan is not None:
        plan_record = _plan_record(plan, registry or EntityTypeRegistry.builtin(), level_by_ref)
        report["plan"] = plan_record
        # Р8, «снять одним кликом»: отдельная секция с группами уровня
        # "possible" — ровно то, что заказчик просил не искать по всему
        # отчёту, а увидеть одним списком.
        review_possible = [
            group for group in plan_record["groups"] if group["level"] == ConfidenceLevel.POSSIBLE
        ]
    report["review_possible"] = review_possible
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
