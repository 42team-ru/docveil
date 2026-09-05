"""Детерминированные ключи связывания найденных сущностей."""

from __future__ import annotations

import re

from masker.detect.dateparse import parse_literal
from masker.detect.orgforms import org_forms
from masker.model import EntityType

_WHITESPACE = re.compile(r"\s+")
# Токен-инициал: одна буква, за которой может идти ещё одна и более пар
# «точка+буква», плюс необязательная точка на конце. Так распознаются и
# «б», и «б.», и «б.м» (без пробела), и «б.м.» — но не полное слово вроде
# «иванов», где между буквами нет точек.
_INITIAL_TOKEN = re.compile(r"^[а-я](?:\.[а-я])*\.?$")
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
    """Свести ФИО к ключу вида «фамилия и.о.» независимо от порядка слов и точек.

    Инициалы («Б.М.», «Б.М», «Б», «Б.») распознаются и приводятся к канону
    «б.м.» отдельно от полных слов, а полные слова (фамилия, при наличии —
    остальные части) всегда идут первыми, независимо от того, где они стояли
    в тексте: «Атараев Б.М» и «Б.М. Атараев» дают один и тот же ключ.

    Сопоставление полной формы («Иванов Иван Иванович») с инициальной формой
    («И.И. Иванов») этим не решается — это две разные полные строки, и ключи
    у них останутся разными; такое сопоставление — предмет отдельной задачи
    T1.6, а не этой нормализации.
    """
    words: list[str] = []
    initials: list[str] = []
    for token in _base(text).split():
        if _INITIAL_TOKEN.match(token):
            initials.extend(letter for letter in token if letter != ".")
            continue
        if len(token) >= 4:
            for ending in _PERSON_ENDINGS:
                if token.endswith(ending) and len(token) - len(ending) >= 3:
                    token = token[: -len(ending)]
                    break
        words.append(token)
    canon = list(words)
    if initials:
        canon.append("".join(f"{letter}." for letter in initials))
    return " ".join(canon)


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
    if entity in {EntityType.DATE, EntityType.BIRTH_DATE}:
        return _normalize_date(text)
    return _base(text)


def _normalize_date(text: str) -> str:
    """ISO-ключ: `14.10.1986` и `14 октября 1986` дают один маркер.

    Разбор не удался — возвращаем `_base(text)`: неразобранный литерал
    получит свой маркер и не сольётся с чужой датой. Падать нормализация
    не должна, иначе плановая согласованность псевдонимов превратится в
    ошибку прогона.
    """
    parsed = parse_literal(text)
    if parsed is None:
        return _base(text)
    return parsed.isoformat()
