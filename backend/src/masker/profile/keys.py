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
_WORD = re.compile(r"[а-яё]+", re.IGNORECASE)
_INITIALS = re.compile(r"\b([а-яё])\.([а-яё])?\.?,?", re.IGNORECASE)


def merge_key(entity: Entity) -> str:
    """Ключ для объединения: тип всегда входит в значение."""
    value = entity.normalized or entity.text
    if entity.type in _DIGIT_TYPES:
        value = re.sub(r"\D", "", value)
    elif entity.type == EntityType.ORG_NAME:
        value = _FORMS.sub("", value)
        value = re.sub(r"[«»\"']", "", value)
        value = " ".join(value.casefold().split())
    elif entity.type == EntityType.PERSON:
        value = _person_identity_key(value)
    else:
        value = " ".join(value.casefold().split())
    return f"{entity.type}:{value}"


def _person_identity_key(text: str) -> str:
    """Ключ ФИО для связи полной, падежной и инициальной формы в профиле."""
    words = _WORD.findall(text.casefold())
    if not words:
        return ""
    initials = _INITIALS.findall(text.casefold())
    if initials:
        surname = words[-1]
        first = initials[0][0]
    else:
        surname = words[0]
        first = words[1][:1] if len(words) > 1 else ""
    # 12.09.2026: «Угнивенко Дмитрия» и «Угнивенко Дмитрий», а также
    # «Д.К. Угнивенко», должны связать сертификат ЭП с подписью Заказчика.
    # Основа фамилии и первая буква имени устойчивы к падежу, но не склеят
    # однофамильцев с разными именами.
    if surname.endswith(("ова", "ева", "ина")):
        surname = surname[:-1]
    return f"{surname}:{first}"
