"""Детерминированные ключи связывания найденных сущностей."""

from __future__ import annotations

import re

from masker.detect.orgforms import org_forms
from masker.model import EntityType

_WHITESPACE = re.compile(r"\s+")
_DIGIT_TYPES = frozenset(
    {
        EntityType.INN,
        EntityType.KPP,
        EntityType.OGRN,
        EntityType.SNILS,
        EntityType.BANK_ACCOUNT,
        EntityType.BIK,
        EntityType.PASSPORT,
        EntityType.PHONE,
    }
)
_PERSON_ENDINGS = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ыми",
    "ими",
    "иях",
    "ах",
    "ях",
    "ого",
    "ему",
    "ой",
    "ей",
    "ом",
    "ем",
    "а",
    "я",
    "у",
    "ю",
    "ы",
    "и",
    "е",
)


def _base(text: str) -> str:
    return _WHITESPACE.sub(" ", text.casefold().replace("ё", "е")).strip()


def _normalize_org(text: str) -> str:
    value = _base(text).strip(" «»\"'“”„")
    for form in org_forms().forms:
        folded = form.casefold()
        if value == folded:
            return ""
        if value.startswith(f"{folded} "):
            value = value[len(folded) :].strip(" «»\"'“”„")
            break
    return _WHITESPACE.sub(" ", value)


def _normalize_person(text: str) -> str:
    tokens: list[str] = []
    for token in _base(text).split():
        if len(token) < 4:
            tokens.append(token)
            continue
        for ending in _PERSON_ENDINGS:
            if token.endswith(ending) and len(token) - len(ending) >= 3:
                token = token[: -len(ending)]
                break
        tokens.append(token)
    return " ".join(tokens)


def normalize_value(entity_type: EntityType | str, text: str) -> str:
    """Вернуть ключ эквивалентности, не предназначенный для отображения."""
    try:
        entity = EntityType(entity_type)
    except ValueError:
        return _base(text)
    if entity in _DIGIT_TYPES:
        return re.sub(r"[\s-]", "", text)
    if entity in {EntityType.EMAIL, EntityType.SITE}:
        return text.casefold()
    if entity is EntityType.ORG_NAME:
        return _normalize_org(text)
    if entity is EntityType.PERSON:
        return _normalize_person(text)
    return _base(text)
