"""Словарь организационно-правовых форм и исправление границ NER."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

# Эти символы не несут значения, если остаются на краю вырезанного модельного спана.
TRIM_CHARS = " \t\u00a0.,;:\u2014\u2013-()[]{}«»\"'“”„…/"
_QUOTE_CHARS = frozenset(
    char for pair in (("«", "»"), ('"', '"'), ("“", "”"), ("„", "“")) for char in pair
)
_SHRINK_TRIM_CHARS = "".join(char for char in TRIM_CHARS if char not in _QUOTE_CHARS)


@dataclass(frozen=True, slots=True)
class OrgForms:
    """Неизменяемые данные словаря организационно-правовых форм."""

    forms: tuple[str, ...]
    role_stems: tuple[str, ...]
    role_words: frozenset[str]
    requisite_labels: frozenset[str]
    public_bodies: tuple[str, ...]
    quote_pairs: tuple[tuple[str, str], ...]


@functools.lru_cache(maxsize=1)
def org_forms() -> OrgForms:
    """Прочитать словарь один раз за процесс."""
    path = Path(__file__).with_name("data") / "org_forms.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    forms = tuple(
        sorted(
            [*raw["abbreviations"], *raw["full_forms"]],
            key=lambda item: (-len(item), item.casefold()),
        )
    )
    return OrgForms(
        forms=forms,
        role_stems=tuple(raw["role_stems"]),
        role_words=frozenset(raw["role_words"]),
        requisite_labels=frozenset(raw["requisite_labels"]),
        public_bodies=tuple(raw["public_bodies"]),
        quote_pairs=tuple((pair[0], pair[1]) for pair in raw["quote_pairs"]),
    )


def _trim_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start] in TRIM_CHARS:
        start += 1
    while start < end and text[end - 1] in TRIM_CHARS:
        end -= 1
    return start, end


def _expand_quotes(text: str, start: int, end: int) -> tuple[int, int]:
    """Включить парные кавычки, когда модель захватила только имя."""
    for opening, closing in org_forms().quote_pairs:
        if start > 0 and text[start - 1] == opening:
            closing_pos = text.find(closing, start, end + 1)
            if closing_pos != -1:
                start -= 1
                end = max(end, closing_pos + 1)
                break
        if end < len(text) and text[end] == closing:
            opening_pos = text.rfind(opening, start, end)
            if opening_pos >= start:
                start = opening_pos
                end += 1
                break
    return start, end


def expand_org_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Расширить имя организации влево на форму и парные кавычки."""
    start, end = _trim_bounds(text, start, end)
    if start == end:
        return None
    start, end = _expand_quotes(text, start, end)

    prefix_end = start
    while prefix_end > 0 and text[prefix_end - 1] in TRIM_CHARS:
        prefix_end -= 1
    prefix = text[:prefix_end]
    folded_prefix = prefix.casefold()
    for form in org_forms().forms:
        folded_form = form.casefold()
        if not folded_prefix.endswith(folded_form):
            continue
        candidate_start = prefix_end - len(form)
        if candidate_start and (
            text[candidate_start - 1].isalnum() or text[candidate_start - 1] == "_"
        ):
            continue
        start = candidate_start
        break
    return start, end


def is_role_stopword(text: str, start: int = 0, end: int | None = None) -> bool:
    """Проверить, что спан состоит только из служебных ролевых слов."""
    end = len(text) if end is None else end
    start, end = _trim_bounds(text, start, end)
    value = text[start:end].casefold()
    tokens = [token for token in value.replace("-", " ").split() if token]
    if not tokens:
        return True
    data = org_forms()
    return all(
        token in data.role_words
        or any(token.startswith(stem) and len(token) - len(stem) <= 3 for stem in data.role_stems)
        for token in tokens
    )


def is_public_body(text: str) -> bool:
    """Проверить, что название целиком обозначает публичное учреждение."""
    value = text.strip(TRIM_CHARS).casefold()
    tokens = [token.strip(TRIM_CHARS) for token in value.replace("-", " ").split()]
    tokens = [token for token in tokens if token]
    return bool(tokens) and all(
        any(
            token.startswith(stem) and len(token) - len(stem) <= 3
            for stem in org_forms().public_bodies
        )
        for token in tokens
    )


def is_organization_form_only(text: str) -> bool:
    """Не выпускать остаток «ООО» без собственно названия."""
    value = text.strip(TRIM_CHARS).casefold()
    return bool(value) and value in {form.casefold() for form in org_forms().forms}


def has_organization_evidence(text: str) -> bool:
    """Найти в остатке форму организации либо полную пару кавычек."""
    folded = text.casefold()
    for form in org_forms().forms:
        match = re.search(rf"(?<!\w){re.escape(form.casefold())}(?!\w)", folded)
        if match is not None:
            return True
    return any(
        (opening == closing and text.count(opening) >= 2)
        or (opening != closing and opening in text and closing in text)
        for opening, closing in org_forms().quote_pairs
    )


def _quotes_balanced(text: str) -> bool:
    return all(
        text.count(opening) % 2 == 0
        if opening == closing
        else text.count(opening) == text.count(closing)
        for opening, closing in org_forms().quote_pairs
    )


def _trim_shrink_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start] in _SHRINK_TRIM_CHARS:
        start += 1
    while start < end and text[end - 1] in _SHRINK_TRIM_CHARS:
        end -= 1
    return start, end


def shrink_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Убрать захваченные моделью подписи и значения реквизитов справа."""
    start, end = _trim_shrink_bounds(text, start, end)
    while start < end:
        token_match = re.search(r"\S+$", text[start:end])
        if token_match is None:
            break
        token_start = start + token_match.start()
        token = text[token_start:end].strip(TRIM_CHARS)
        removable = (
            not token
            or any(char.isdigit() for char in token)
            or token.casefold() in org_forms().requisite_labels
        )
        if not removable:
            break
        candidate_end = token_start
        candidate_start, candidate_end = _trim_shrink_bounds(text, start, candidate_end)
        if not _quotes_balanced(text[candidate_start:candidate_end]):
            break
        start, end = candidate_start, candidate_end
    start, end = _trim_shrink_bounds(text, start, end)
    if start == end or not any(char.isalpha() for char in text[start:end]):
        return None
    return start, end


def fix_person_initials(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Добавить точку к последнему инициалу, если Natasha её не включила."""
    start, end = _trim_bounds(text, start, end)
    if start == end:
        return None
    initials_without_dot = re.search(r"\b[А-ЯЁ]\.[А-ЯЁ]$", text[start:end], re.IGNORECASE)
    if end < len(text) and text[end] == "." and initials_without_dot:
        end += 1
    return start, end
