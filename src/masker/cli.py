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

from masker.detect import DetectAgent, RuleDetector
from masker.detect.ner import LABEL_TO_TYPE
from masker.detect.result import PiiChunk, build_pii_chunks
from masker.detect.rules import PATTERNS
from masker.ingest.docx_ingest import ingest_docx
from masker.model import Document, Entity, EntityType
from masker.render.docx_preview import render_docx_preview
from masker.report.html import render_html_report

DEFAULT_OUTPUT = Path("out") / "inspect"
REPORT_VERSION = 2
WORD_TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"


def _entity_record(document: Document, entity: Entity) -> dict[str, Any]:
    segment = document.segments[entity.segment_order]
    return {
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
    table_paragraphs = {
        id(paragraph._p): paragraph.text
        for table in source_docx.tables
        for row in table.rows
        for cell in row.cells
        for paragraph in cell.paragraphs
        if paragraph.text.strip()
    }
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
            "nonempty_paragraphs": len(document.segments),
        },
        "tables": {
            "processed": False,
            "count": len(source_docx.tables),
            "nonempty_paragraphs": len(table_paragraphs),
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


def _xml_part_has_text(archive: zipfile.ZipFile, name: str) -> bool:
    root = ElementTree.fromstring(archive.read(name))
    return any((element.text or "").strip() for element in root.iter(WORD_TEXT_TAG))


def _detection_coverage(
    selected_types: frozenset[EntityType], *, rules_only: bool
) -> dict[str, list[str]]:
    active_types = set(PATTERNS)
    if not rules_only:
        active_types.update(LABEL_TO_TYPE.values())
    return {
        "requested_types": sorted(entity_type.value for entity_type in selected_types),
        "active_detector_types": sorted(entity_type.value for entity_type in active_types),
        "requested_without_detector": sorted(
            entity_type.value for entity_type in selected_types - active_types
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
    *,
    rules_only: bool,
) -> dict[str, Any]:
    return {
        "report_version": REPORT_VERSION,
        "input": source.name,
        "format": document.fmt,
        "preview_only": True,
        "selected_types": sorted(entity_type.value for entity_type in selected_types),
        "entity_count": len(entities),
        "chunk_count": len(chunks),
        "summary": _summary(entities),
        "detection_coverage": _detection_coverage(selected_types, rules_only=rules_only),
        "document_coverage": _document_coverage(source, document),
        "entities": [_entity_record(document, entity) for entity in entities],
        "chunks": [
            _chunk_record(document, chunk, index) for index, chunk in enumerate(chunks, start=1)
        ],
        "limitations": [
            "Проверяются только непустые абзацы основного текста DOCX.",
            "Таблицы, колонтитулы, сноски и метаданные пока не обезличиваются.",
            "Preview содержит исходный текст и не предназначен для передачи наружу.",
        ],
    }


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
) -> tuple[Path, Path, Path | None, list[Entity]]:
    """Проверить один DOCX и записать JSON плюс подсвеченную копию."""
    document = ingest_docx(source)
    detector = DetectAgent([RuleDetector()]) if rules_only else DetectAgent()
    entities = [
        entity for entity in detector.detect(document).entities if entity.type in selected_types
    ]
    chunks = build_pii_chunks(document.segments, entities)

    artifact_dir = output_dir / source.stem
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifact_dir / "report.json"
    preview_path = artifact_dir / "preview.docx"
    report = _build_report(
        source,
        document,
        entities,
        chunks,
        selected_types,
        rules_only=rules_only,
    )
    _write_report(report_path, report)
    render_docx_preview(source, preview_path, document, entities)
    html_path = artifact_dir / "report.html" if html else None
    if html_path is not None:
        render_html_report(report, source, html_path)
    return report_path, preview_path, html_path, entities


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="masker",
        description="Найти PII в DOCX и создать JSON-отчёт с подсвеченной preview-копией.",
    )
    parser.add_argument("files", nargs="+", type=Path, help="один или несколько файлов .docx")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        selected_types = _parse_types(args.types)
    except ValueError as error:
        parser.error(str(error))

    invalid = [
        path for path in args.files if not path.is_file() or path.suffix.casefold() != ".docx"
    ]
    if invalid:
        parser.error("ожидались существующие DOCX: " + ", ".join(str(path) for path in invalid))

    for source in args.files:
        report_path, preview_path, html_path, entities = inspect_docx(
            source,
            args.out,
            selected_types,
            rules_only=args.rules_only,
            html=args.html,
        )
        print(f"{source}: найдено сущностей — {len(entities)}")
        print(f"  отчёт:  {report_path}")
        print(f"  preview: {preview_path}")
        if html_path is not None:
            print(f"  HTML:    {html_path}")
    print("ВАЖНО: preview содержит исходный текст и служит только для проверки детектора.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
