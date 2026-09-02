"""Тесты покрытия документа/детекторов (T1.10, шаг 2) — перенос из cli.py."""

from __future__ import annotations

from pathlib import Path

from masker.detect import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.model import EntityType
from masker.report.coverage import detection_coverage, docx_coverage

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"


def test_docx_coverage_reports_tables_processed_and_headers_not_processed() -> None:
    document = ingest_docx(FIXTURE)

    coverage = docx_coverage(FIXTURE, document)

    assert coverage["tables"]["processed"] is True
    assert coverage["headers"]["processed"] is False


def test_detection_coverage_lists_requested_types() -> None:
    document = ingest_docx(FIXTURE)
    detector = DetectAgent()
    entities = detector.detect(document).entities
    assert entities  # sanity: фикстура содержит хоть что-то детектируемое

    selected_types = frozenset({EntityType.INN, EntityType.PERSON})
    coverage = detection_coverage(selected_types, detector)

    assert coverage["requested_types"] == sorted(
        entity_type.value for entity_type in selected_types
    )
