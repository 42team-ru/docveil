"""Д3: жанр, первая страница и краткое содержание документа."""

from __future__ import annotations

import json

from masker.llm import FakeProvider
from masker.model import Anchor, Document, MaskPlan, Replacement, Segment, Source
from masker.model import Entity as MaskEntity
from masker.summary import ContractSummary, analyze_document, export_summary, first_page_text


def _document(*segments: Segment, fmt: str = "docx") -> Document:
    return Document(path="source." + fmt, fmt=fmt, segments=list(segments))


def test_non_contract_has_genre_summary_and_no_contract_fields() -> None:
    document = _document(
        Segment("ГОСТ 30524-2013. Требования к услугам.", Anchor("docx", ("body", 0)), 0)
    )
    response = json.dumps(
        {
            "summary": (
                "Документ устанавливает требования. Он описывает область применения. "
                "Он задаёт правила качества."
            ),
            "is_contract": False,
            "genre": "ГОСТ",
            "confidence": 0.93,
        }
    )

    analysis = analyze_document(document, [], FakeProvider([response]))
    assert analysis.kind.status == "non_contract"
    assert analysis.kind.genre == "ГОСТ"
    assert analysis.brief_summary is not None
    assert analysis.llm_calls == 1


def test_low_confidence_is_unknown_not_non_contract() -> None:
    document = _document(Segment("Текст без жанра.", Anchor("docx", ("body", 0)), 0))
    response = json.dumps(
        {
            "summary": "Это документ. В нём есть сведения. Его жанр неясен.",
            "is_contract": False,
            "genre": "письмо",
            "confidence": 0.5,
        }
    )

    analysis = analyze_document(document, [], FakeProvider([response]))
    assert analysis.kind.status == "unknown"
    assert analysis.kind.genre is None
    assert analysis.brief_summary is not None


def test_obvious_supply_contract_needs_only_summary_call() -> None:
    document = _document(
        Segment(
            "ДОГОВОР ПОСТАВКИ № 7\nЗаказчик, ИНН 7700000001. Поставщик, ИНН 7800000001.",
            Anchor("docx", ("body", 0)),
            0,
        )
    )
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "summary": (
                        "Заказчик заключает договор. Поставщик поставит товар. "
                        "Документ устанавливает условия поставки."
                    )
                }
            )
        ]
    )

    analysis = analyze_document(document, [], provider)
    assert analysis.kind.status == "contract"
    assert analysis.kind.source == "rule"
    assert analysis.llm_calls == 1
    assert provider.calls == 1


def test_pdf_analysis_input_contains_only_first_page() -> None:
    document = _document(
        Segment("Первая страница.", Anchor("pdf", ("page", 0, 0, 10)), 0),
        Segment("Вторая страница.", Anchor("pdf", ("page", 1, 0, 10)), 1),
        fmt="pdf",
    )

    assert first_page_text(document) == "Первая страница."


def test_exported_brief_summary_does_not_leak_in_report_json() -> None:
    inn = "7707000001"
    entity = MaskEntity(
        type="inn", text=inn, segment_order=0, start=0, end=len(inn), source=Source.RULE
    )
    plan = MaskPlan(
        replacements=(
            Replacement("E1", entity, "[ЗАКАЗЧИК-ИНН]", "G1", "P1", Anchor("docx", ("body", 0))),
        ),
        groups=(),
        skipped=(),
        requested_types=(),
    )
    summary = ContractSummary(
        brief_summary=f"Документ с ИНН {inn}. Он описывает условия. Он адресован заказчику."
    )

    report_json = json.dumps(
        {"contract_summary": export_summary(summary, plan)}, ensure_ascii=False
    )
    assert inn not in report_json
    assert "[ЗАКАЗЧИК-ИНН]" in report_json
