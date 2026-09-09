"""Белый список для уровня уверенности «possible» (Р8).

Данные, не код — см. ``data/name_whitelist.yaml``: юридические термины,
месяцы, валюты, названия законов и ГОСТов/ТУ, из-за которых заглавное имя
собственное вне контекста стороны договора не должно тянуть маску в отчёте
на «снять одним кликом».
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml


@functools.lru_cache(maxsize=1)
def name_whitelist() -> frozenset[str]:
    """Прочитать белый список один раз за процесс, ключи — casefold()."""
    path = Path(__file__).with_name("data") / "name_whitelist.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    terms: set[str] = set()
    for key, values in raw.items():
        if key == "version":
            continue
        terms.update(str(value).casefold() for value in values)
    return frozenset(terms)


def is_whitelisted(text: str) -> bool:
    """Вернуть, покрыт ли текст белым списком целиком либо словами.

    Полная фраза целиком (``"Российская Федерация"``) — самый частый
    случай. Второй проход — по отдельным словам, чтобы не перечислять в
    данных каждую комбинацию (например, «Технических условий по ГОСТ» не
    нужно вносить фразой целиком, если каждое слово уже в списке).
    """
    whitelist = name_whitelist()
    normalized = " ".join(text.split()).casefold()
    if normalized in whitelist:
        return True
    tokens = [token.strip(".,;:()[]{}«»\"'“”„-") for token in normalized.split()]
    tokens = [token for token in tokens if token]
    return bool(tokens) and all(token in whitelist for token in tokens)
