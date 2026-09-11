"""Классификация жанра и краткое содержание по первой странице оригинала."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from masker.llm import LLMError, LLMProvider, Message
from masker.model import Document, Entity, Profile
from masker.summary.model import ContractSummary, DocumentKind

_FIRST_PAGE_LIMIT = 6_000
_MIN_CONFIDENCE = 0.8
_CONTRACT_TITLE_RE = re.compile(r"^\s*(?:проект\s+)?договор\s+поставки\s+№", re.I)
_CUSTOMER_RE = re.compile(r"\b(?:заказчик|покупатель)\b", re.I)
_SUPPLIER_RE = re.compile(r"\b(?:поставщик|исполнитель|продавец)\b", re.I)
_INN_RE = re.compile(r"\bинн\b", re.I)
_SENTENCE_RE = re.compile(r"[.!?](?=\s|$)")
_NON_TERMINAL_DOT_RE = re.compile(r"(?<=\d)\.(?=\d)|\b(?:ст|п|г|руб)\.(?=\s|$)", re.I)
# Решение 11.09.2026: модель должна выбирать классификацию, а не изобретать
# таксономию вслух. ``иное`` оставляет короткий выход для редких документов.
_DOCUMENT_GENRES = (
    "договор",
    "техническое задание",
    "технические условия / стандарт",
    "технические условия",
    "устав",
    "счёт",
    "акт",
    "приказ",
    "доверенность",
    "письмо",
    "отчёт",
    "иное",
)
_OTHER_GENRE = "иное"
_MAX_GENRE_DETAIL = 80

# Замерено 11.09.2026: все живые ответы оставляли тип в null, потому что
# контракт спрашивал лишь bool is_contract. Явный трёхзначный kind не даёт
# технической неопределённости притвориться ни договором, ни не-договором.
_ANALYSIS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "kind": {"enum": ["contract", "non_contract", "unknown"]},
        "genre": {"enum": [*_DOCUMENT_GENRES, None]},
        "genre_detail": {"type": ["string", "null"], "maxLength": _MAX_GENRE_DETAIL},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["summary", "kind", "genre", "genre_detail", "confidence"],
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


def build_document_card(
    document: Document,
    entities: list[Entity],
    profiles: list[Profile],
    llm: LLMProvider | None,
    *,
    llm_calls: int = 0,
) -> ContractSummary:
    """Собрать часть Д3: жанр, пересказ и только уместные поля договора.

    Функция нужна короткому прогону записи кассет: он повторяет смысл узла
    ``summary`` без рендера, маскирования и всего корпуса. Экспорт в пакет
    намеренно остаётся обязанностью графа, потому что только там уже готов
    ``MaskPlan``.
    """
    from masker.summary.agent import build_summary

    analysis = analyze_document(document, profiles, llm)
    total_calls = llm_calls + analysis.llm_calls
    if analysis.kind.status == "non_contract":
        # Замерено 11.09.2026: у ГОСТа раньше выводились шесть пустых полей
        # договора. У не-договора поля не «не найдены»: они неприменимы. Поэтому не
        # запускаем детерминированный сборщик, который мог бы случайно
        # принять число или дату из ГОСТа за условие договора.
        return ContractSummary(
            brief_summary=analysis.brief_summary,
            document_kind=analysis.kind,
            generated_at="",
            llm_calls=total_calls,
        )
    summary = build_summary(
        entities,
        profiles,
        llm_calls=total_calls,
        generated_at="",
        document=document,
    )
    summary.brief_summary = analysis.brief_summary
    summary.document_kind = analysis.kind
    return summary


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
        "Определи тип документа. Поле kind обязательно: contract, non_contract или unknown; "
        "для non_contract обязательно выбери genre только из списка: "
        f"{', '.join(_DOCUMENT_GENRES)}. Для contract genre и genre_detail равны null. "
        "Если жанр не подходит к списку, выбери genre «иное» и в genre_detail дай "
        "название своими словами в одной короткой фразе не длиннее 80 символов. "
        "Для любого другого genre genre_detail равен null. Не объясняй свой выбор. "
        "Не оставляй kind null и не заменяй его другим полем."
        if classify
        # Решение 11.09.2026: меняем версию и короткого запроса пересказа
        # вместе с классификацией, чтобы третья запись кассет проверила все
        # пять карточек одним согласованным сценарием, а не смесью версий.
        else "Документ уже определён правилом как договор. Верни только JSON пересказа."
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
    kind = payload.get("kind")
    genre = payload.get("genre")
    genre_detail = payload.get("genre_detail")
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        return DocumentKind()
    if not isinstance(kind, str) or confidence < _MIN_CONFIDENCE:
        return DocumentKind()
    if kind == "contract":
        return DocumentKind(
            status="contract", genre="договор", confidence=float(confidence), source="llm"
        )
    if kind != "non_contract" or not isinstance(genre, str) or not genre.strip():
        return DocumentKind()
    if genre not in _DOCUMENT_GENRES:
        # Решение 11.09.2026: схема — договорённость, а не защита от старого
        # или ошибочного ответа. Вне перечня безопасно показываем «иное».
        genre = _OTHER_GENRE
        genre_detail = payload.get("genre")
    if genre == _OTHER_GENRE:
        detail = _short_genre_detail(genre_detail)
        if not detail:
            return DocumentKind()
        genre = f"{_OTHER_GENRE}: {detail}"
    return DocumentKind(
        status="non_contract", genre=genre, confidence=float(confidence), source="llm"
    )


def _short_genre_detail(value: object) -> str | None:
    """Вернуть короткое название редкого жанра без рассуждений модели."""
    if not isinstance(value, str):
        return None
    detail = value.strip()
    if not detail:
        return None
    # Решение 11.09.2026: даже нарушившая схему модель не должна превратить
    # карточку в протокол своих рассуждений; первая фраза содержит название.
    sentence = re.split(r"[.!?;]\s+", detail, maxsplit=1)[0].strip()
    return sentence[:_MAX_GENRE_DETAIL].rstrip()


def _valid_summary(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    summary = value.strip()
    # Замерено 11.09.2026 на eat-654000009321.pdf: «30000.00 руб.» и
    # «ст. 95» ошибочно считались двумя дополнительными предложениями, из-за
    # чего честный пересказ из кассеты отбрасывался до попадания в карточку.
    sentence_count = len(_SENTENCE_RE.findall(_NON_TERMINAL_DOT_RE.sub("", summary)))
    return summary if 3 <= sentence_count <= 5 else None
