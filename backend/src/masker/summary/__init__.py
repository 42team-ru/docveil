"""Карточка договора — ContractSummary (Фаза 3 плана)."""

from masker.summary.agent import build_summary
from masker.summary.document import (
    DocumentAnalysis,
    analyze_document,
    build_document_card,
    first_page_text,
)
from masker.summary.export import SummaryLeakError, export_summary
from masker.summary.model import (
    ContractFact,
    ContractParty,
    ContractSummary,
    DeliveryFact,
    DocumentKind,
    FactAlternative,
    FactAnchor,
    MoneyFact,
    PaymentFact,
    PaymentStage,
)

__all__ = [
    "ContractFact",
    "ContractParty",
    "ContractSummary",
    "DeliveryFact",
    "DocumentAnalysis",
    "DocumentKind",
    "FactAlternative",
    "FactAnchor",
    "MoneyFact",
    "PaymentFact",
    "PaymentStage",
    "SummaryLeakError",
    "analyze_document",
    "build_document_card",
    "build_summary",
    "export_summary",
    "first_page_text",
]
