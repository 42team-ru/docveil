"""Офлайн-приёмка Д3 на ответах, записанных владельцем продукта."""

from __future__ import annotations

from pathlib import Path

import pytest

from masker.detect import DetectAgent, default_detectors
from masker.eval import _ingest
from masker.llm import CassetteProvider, LLMError
from masker.profile import ProfileAgent
from masker.summary import build_document_card
from masker.summary.document import _is_obvious_contract, _messages, first_page_text

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
CASSETTES = ROOT / "fixtures" / "llm" / "summary"
CONTRACT = ROOT / "fixtures" / "real-contracts" / "open-contracts" / "arkhschool-68-183.pdf"
EAT = ROOT / "fixtures" / "real-contracts" / "open-contracts" / "eat-654000009321.pdf"
GOST = ROOT / "fixtures" / "negative" / "negative_01_gost.docx"


def _card(path: Path):
    """Повторить Д3 локально: LLM отвечает только из кассет, сети нет."""
    document = _ingest(path)
    detection = DetectAgent(default_detectors()).detect(document)
    profiles = ProfileAgent(None).profile(document, detection).profiles
    provider = CassetteProvider(CASSETTES)
    # Замерено 11.09.2026: поле kind стало обязательным, поэтому старые
    # кассеты с is_contract не являются ответами действующего промпта. Не
    # подменяем их: владелец должен записать новый живой ответ, а офлайн-тест
    # сообщает причину skip до этого момента.
    messages = _messages(
        first_page_text(document),
        classify=not _is_obvious_contract(first_page_text(document), profiles),
    )
    try:
        provider.complete(messages)
    except LLMError as error:
        pytest.skip(
            "для текущего промпта Д3 нет кассеты; требуется третья перезапись владельцем "
            f"{path.name} через `.venv/bin/python scripts/record_llm_cassettes.py`: {error}"
        )
    return build_document_card(document, detection.entities, profiles, provider)


def test_recorded_contract_has_kind_summary_and_fields() -> None:
    """Живой ответ на договор остаётся воспроизводимым без ключа и сети."""
    card = _card(CONTRACT)

    assert card.document_kind.status == "contract"
    assert card.brief_summary
    assert card.contract_amount_fact.status in {"found", "ambiguous", "not_found"}
    assert card.contract_number_fact.status in {"found", "ambiguous", "not_found"}


def test_recorded_eat_summary_reaches_card() -> None:
    """Ответ кассеты с десятичной ценой остаётся виден оператору в карточке."""
    card = _card(EAT)

    assert card.document_kind.status == "contract"
    assert card.brief_summary


def test_recorded_gost_is_not_contract_and_has_no_contract_fields() -> None:
    """ГОСТ не выдаётся за договор с шестью неудавшимися поисками полей."""
    card = _card(GOST)

    assert card.document_kind.status == "non_contract"
    assert card.document_kind.genre
    assert card.brief_summary
    assert card.customer is None
    assert card.supplier is None
    assert card.contract_amount is None
    assert card.contract_number is None
    assert card.delivery_periods == []
    assert card.payment_terms is None
    assert card.federal_law == []
