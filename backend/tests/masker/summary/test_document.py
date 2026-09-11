"""Д3: жанр, первая страница и краткое содержание документа."""

from __future__ import annotations

import json

from masker.llm import FakeProvider
from masker.model import Anchor, Document, MaskPlan, Replacement, Segment, Source
from masker.model import Entity as MaskEntity
from masker.summary import (
    ContractSummary,
    analyze_document,
    build_document_card,
    export_summary,
    first_page_text,
)
from masker.summary.document import _ANALYSIS_SCHEMA, _DOCUMENT_GENRES, _kind_from_payload


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
            "kind": "non_contract",
            "genre": "иное",
            "genre_detail": "ГОСТ",
            "confidence": 0.93,
        }
    )

    analysis = analyze_document(document, [], FakeProvider([response]))
    assert analysis.kind.status == "non_contract"
    assert analysis.kind.genre == "иное: ГОСТ"
    assert analysis.brief_summary is not None
    assert analysis.llm_calls == 1


def test_low_confidence_is_unknown_not_non_contract() -> None:
    document = _document(Segment("Текст без жанра.", Anchor("docx", ("body", 0)), 0))
    response = json.dumps(
        {
            "summary": "Это документ. В нём есть сведения. Его жанр неясен.",
            "kind": "non_contract",
            "genre": "письмо",
            "genre_detail": None,
            "confidence": 0.5,
        }
    )

    analysis = analyze_document(document, [], FakeProvider([response]))
    assert analysis.kind.status == "unknown"
    assert analysis.kind.genre is None
    assert analysis.brief_summary is not None


def test_document_card_does_not_collect_fields_for_confirmed_non_contract() -> None:
    """Число в ГОСТе не становится суммой договора после определения жанра."""
    document = _document(
        Segment("ГОСТ 123. Допустимое значение: 1 000 000 руб.", Anchor("docx", ("body", 0)), 0)
    )
    amount = MaskEntity(
        type="contract_amount",
        text="1 000 000 руб.",
        segment_order=0,
        start=30,
        end=43,
        source=Source.RULE,
    )
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "summary": (
                        "Это ГОСТ. Он устанавливает требования. Он задаёт допустимые значения."
                    ),
                    "kind": "non_contract",
                    "genre": "иное",
                    "genre_detail": "ГОСТ",
                    "confidence": 0.95,
                }
            )
        ]
    )

    card = build_document_card(document, [amount], [], provider)

    assert card.document_kind.status == "non_contract"
    assert card.brief_summary
    assert card.contract_amount is None
    assert card.contract_amount_fact.status == "not_found"


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


def test_decimal_and_legal_abbreviation_summary_reaches_card() -> None:
    """Пересказ из LLM не теряется из-за точек в цене или ссылке на статью."""
    document = _document(
        Segment("Государственный контракт № 654000009321.", Anchor("docx", ("body", 0)), 0)
    )
    response = json.dumps(
        {
            "summary": (
                "Стороны заключили контракт. Цена составляет 30000.00 руб. "
                "Условия могут меняться по ст. 95 Федерального закона. "
                "Исполнитель оказывает услуги."
            ),
            "kind": "contract",
            "genre": None,
            "genre_detail": None,
            "confidence": 1.0,
        }
    )

    card = build_document_card(document, [], [], FakeProvider([response]))

    assert card.brief_summary is not None
    assert "30000.00 руб." in card.brief_summary


def test_unknown_long_genre_becomes_short_other() -> None:
    """Нарушивший enum ответ не передаёт в карточку рассуждения модели."""
    kind = _kind_from_payload(
        {
            "kind": "non_contract",
            "genre": "Технические условия; далее модель рассуждает о выборе жанра " * 4,
            "genre_detail": None,
            "confidence": 0.95,
        }
    )

    assert kind.status == "non_contract"
    assert kind.genre == "иное: Технические условия"
    assert kind.genre is not None and len(kind.genre) <= len("иное: ") + 80


def test_analysis_schema_has_closed_genre_list_and_other_detail() -> None:
    """Схема не оставляет модели неопределённый список жанров."""
    properties = _ANALYSIS_SCHEMA["properties"]
    assert isinstance(properties, dict)
    assert properties["genre"] == {"enum": [*_DOCUMENT_GENRES, None]}
    assert properties["genre_detail"] == {"type": ["string", "null"], "maxLength": 80}


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
