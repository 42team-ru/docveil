"""Ролевые метки, извлекаемые только из формулировок документа."""

from __future__ import annotations

import re
import unicodedata

PREAMBLE = re.compile(r"именуем\w*\s+в\s+дальнейшем\s+[«\"]([^»\"]+)[»\"]", re.IGNORECASE)
REQUISITES = re.compile(r"(?:^|\b)реквизиты\s+([А-ЯЁ][А-ЯЁа-яё\- ]+)", re.IGNORECASE)
SIGNATURE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?([А-ЯЁ][А-ЯЁа-яё\- ]{1,40}):\s*(?=[_—-]{2,}|[А-ЯЁ])"
)


def normalize_label(label: str) -> str:
    """Свести написание роли к стабильной форме без закрытого словаря ролей."""
    return " ".join(label.strip(' \t.,;:«»"').casefold().split())


def find_labels(text: str) -> list[tuple[int, str]]:
    """Найти ролевые метки только в контекстах, явно задающих роль."""
    found: list[tuple[int, str]] = []
    for expression in (PREAMBLE, REQUISITES, SIGNATURE):
        for match in expression.finditer(text):
            label = normalize_label(match.group(1))
            if label:
                found.append((match.start(1), label))
    return sorted(set(found), key=lambda item: item[0])


def slugify(label: str) -> str:
    """Сделать стабильный ASCII slug открытой роли."""
    transliteration = str.maketrans(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        "abvgdeejzijklmnoprstufhzcss_y_eua",
    )
    value = unicodedata.normalize("NFKD", normalize_label(label)).translate(transliteration)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "side"


def role_title(label: str) -> str:
    """Отобразить роль так, как она названа в документе."""
    return normalize_label(label).capitalize()


def marker_label(label: str) -> str:
    """Сделать читаемую часть будущего маркера."""
    return role_title(label).upper().replace(" ", "-")
