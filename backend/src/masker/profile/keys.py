"""Детерминированные ключи связи сущностей."""

from __future__ import annotations

import re

from masker.model import Entity, EntityType

_DIGIT_TYPES = frozenset(
    {
        EntityType.INN,
        EntityType.OGRN,
        EntityType.KPP,
        EntityType.SNILS,
        EntityType.BANK_ACCOUNT,
        EntityType.BIK,
    }
)
_FORMS = re.compile(
    r"\b(?:ооо|ао|пао|зао|ип|общество\s+с\s+ограниченной\s+ответственностью|акционерное\s+общество)\b",
    re.IGNORECASE,
)


def merge_key(entity: Entity) -> str:
    """Ключ для объединения: тип всегда входит в значение."""
    value = entity.normalized or entity.text
    if entity.type in _DIGIT_TYPES:
        value = re.sub(r"\D", "", value)
    elif entity.type is EntityType.ORG_NAME:
        value = _FORMS.sub("", value)
        value = re.sub(r"[«»\"']", "", value)
        value = " ".join(value.casefold().split())
    else:
        value = " ".join(value.casefold().split())
    return f"{entity.type.value}:{value}"
