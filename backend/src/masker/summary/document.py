"""Классификация жанра и краткое содержание по первой странице оригинала."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from masker.llm import LLMError, LLMProvider, Message
from masker.model import Document, Profile
from masker.summary.model import DocumentKind

_FIRST_PAGE_LIMIT = 6_000
_MIN_CONFIDENCE = 0.8
_CONTRACT_TITLE_RE = re.compile(r"^\s*(?:проект\s+)?договор\s+поставки\s+№", re.I)
_CUSTOMER_RE = re.compile(r"\b(?:заказчик|покупатель)\b", re.I)
_SUPPLIER_RE = re.compile(r"\b(?:поставщик|исполнитель|продавец)\b", re.I)
_INN_RE = re.compile(r"\bинн\b", re.I)
_SENTENCE_RE = re.compile(r"[.!?](?=\s|$)")

_ANALYSIS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "is_contract": {"type": "boolean"},
        "genre": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["summary", "is_contract", "genre", "confidence"],
    "additionalProperties": False,
}
_SUMMARY_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class DocumentAnalysis:
    """Результат одного вызова модели (или правила) без не-JSON объектов."""

    kind: DocumentKind
    brief_summary: str | None
    llm_calls: int


def first_page_text(document: Document) -> str:
    """Вернуть только первую страницу; для DOCX/XLSX — её начальный фрагмент.

    У DOCX и XLSX в исходном контейнере нет достоверного разбиения на
    страницы. В таком случае берём первые ``_FIRST_PAGE_LIMIT`` символов, а
    не весь документ: это тот же ограниченный вход, что и для PDF.
    """
    if document.fmt == "pdf":
        first_page = [
            segment.text
            for segment in document.segments
            if len(segment.anchor.locator) > 1
            and segment.anchor.locator[0] == "page"
            and segment.anchor.locator[1] == 0
        ]
        return "\n".join(first_page)[:_FIRST_PAGE_LIMIT]
    return document.text()[:_FIRST_PAGE_LIMIT]


def analyze_document(
    document: Document, profiles: list[Profile], llm: LLMProvider | None
) -> DocumentAnalysis:
    """Определить жанр и попросить 3--5 фраз, не отправляя весь документ."""
    page = first_page_text(document)
    if _is_obvious_contract(page, profiles):
        return _summarize_obvious_contract(page, llm)
    if llm is None:
        return DocumentAnalysis(DocumentKind(), None, 0)
    try:
        response = llm.complete(_messages(page, classify=True), schema=_ANALYSIS_SCHEMA)
        payload = json.loads(response)
    except (LLMError, json.JSONDecodeError, TypeError, ValueError):
        return DocumentAnalysis(DocumentKind(), None, 1)
    if not isinstance(payload, dict):
        return DocumentAnalysis(DocumentKind(), None, 1)
    summary = _valid_summary(payload.get("summary"))
    kind = _kind_from_payload(payload)
    return DocumentAnalysis(kind, summary, 1)


def _summarize_obvious_contract(page: str, llm: LLMProvider | None) -> DocumentAnalysis:
    kind = DocumentKind(status="contract", genre="договор", confidence=1.0, source="rule")
    if llm is None:
        return DocumentAnalysis(kind, None, 0)
    try:
        response = llm.complete(_messages(page, classify=False), schema=_SUMMARY_SCHEMA)
        payload = json.loads(response)
    except (LLMError, json.JSONDecodeError, TypeError, ValueError):
        return DocumentAnalysis(kind, None, 1)
    summary = _valid_summary(payload.get("summary")) if isinstance(payload, dict) else None
    return DocumentAnalysis(kind, summary, 1)


def _is_obvious_contract(page: str, profiles: list[Profile]) -> bool:
    if _CONTRACT_TITLE_RE.search(page) is None:
        return False
    roles = {profile.role_title.casefold() for profile in profiles if profile.role_title}
    has_profile_sides = bool(roles & {"заказчик", "покупатель"}) and bool(
        roles & {"поставщик", "исполнитель", "продавец"}
    )
    has_requisites = len(_INN_RE.findall(page)) >= 2
    has_named_sides = _CUSTOMER_RE.search(page) and _SUPPLIER_RE.search(page)
    return has_requisites and (has_profile_sides or bool(has_named_sides))


def _messages(page: str, *, classify: bool) -> list[Message]:
    action = (
        "Определи, является ли документ договором, и назови жанр, если это не договор."
        if classify
        else "Документ уже определён правилом как договор."
    )
    return [
        Message(
            "system",
            "Составь краткое содержание документа ровно в 3--5 фразах. "
            "Называй стороны точным написанием из текста, не склоняй имена и названия. "
            f"{action} Верни только JSON по переданной схеме.",
        ),
        Message("user", page),
    ]


def _kind_from_payload(payload: dict[object, object]) -> DocumentKind:
    confidence = payload.get("confidence")
    is_contract = payload.get("is_contract")
    genre = payload.get("genre")
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        return DocumentKind()
    if not isinstance(is_contract, bool) or confidence < _MIN_CONFIDENCE:
        return DocumentKind()
    if is_contract:
        return DocumentKind(
            status="contract", genre="договор", confidence=float(confidence), source="llm"
        )
    if not isinstance(genre, str) or not genre.strip():
        return DocumentKind()
    return DocumentKind(
        status="non_contract", genre=genre.strip(), confidence=float(confidence), source="llm"
    )


def _valid_summary(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    summary = value.strip()
    sentence_count = len(_SENTENCE_RE.findall(summary))
    return summary if 3 <= sentence_count <= 5 else None
