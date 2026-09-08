"""Конверт правок оператора — второе прерывание графа (раунд проверки).

Первое прерывание (``ask_human``) спрашивает человека до маскирования: какие
типы и каких субъектов трогать. Второе спрашивает после: оператор видит
готовый отчёт и обезличенный документ и правит результат — снимает лишнюю
маску, меняет тип у группы, добавляет пропущенное движком значение.

Форма та же, что у ``questions.py``, и по той же причине: конверт, а не голый
словарь. ``Command(resume={})`` с пустым значением langgraph трактует как
«значения нет» и ставит узел на паузу заново.

Правки не применяются напрямую к документу: они разворачиваются в решения по
ссылкам и в новые сущности, после чего граф заново проходит
``plan → summary → render → validate → report``. Поэтому согласованность
маркеров, защита критичных типов и проверка утечек держатся тем же кодом, что
и на первом проходе, а не переписываются во втором месте.
"""

from __future__ import annotations

from typing import Any

from masker.graph.state import State

#: Версия конверта правок. Поднимается руками при несовместимой смене формы —
#: старый клиент получит `ValueError`, а не молча иначе понятые правки.
SCHEMA_VERSION = 1

#: Что оператор может сказать про ссылку или группу.
MASK_ACTION = "mask"
KEEP_ACTION = "keep"
_ACTIONS = frozenset({MASK_ACTION, KEEP_ACTION})


def build_review_payload(state: State) -> dict[str, Any]:
    """Конверт паузы: отчёт прогона целиком плюс метаданные документа.

    Отдаём именно ``report`` из состояния, а не отдельно собранную выжимку:
    оператор правит то, что видит на экране проверки, и этот же отчёт уже
    разобран фронтом. Второй формы того же документа быть не должно.
    """
    meta = state.get("meta", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "thread_id": str(state.get("options", {}).get("thread_id", "")),
        "document": {"name": str(meta.get("name", "")), "format": str(state.get("fmt", ""))},
        "report": dict(state.get("report", {})),
    }


def parse_review_edits(raw: Any) -> dict[str, Any]:
    """Разобрать конверт правок оператора.

    Строгие проверки — только на форму конверта: несовпадение
    ``schema_version`` это ошибка вызывающего, а не повод догадываться.
    Внутри конверта действует то же правило, что у ``parse_answers``: всё
    непонятное отбрасывается молча, потому что молчание здесь означает
    «оставить решение движка», а угадывание — тихую подмену воли оператора.
    """
    if not isinstance(raw, dict):
        raise ValueError("правки должны быть словарём")
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"несовместимая версия конверта правок: {version!r}, ожидается {SCHEMA_VERSION}"
        )

    edits = raw.get("edits")
    if not isinstance(edits, dict):
        raise ValueError("конверт правок без поля 'edits'")

    return {
        "decisions": _decisions(edits.get("decisions")),
        "type_overrides": _type_overrides(edits.get("type_overrides")),
        "manual": _manual(edits.get("manual")),
    }


def _decisions(raw: Any) -> dict[str, str]:
    """``{ref: "mask"|"keep"}``; неизвестное действие отбрасывается."""
    if not isinstance(raw, dict):
        return {}
    return {
        str(ref): value
        for ref, value in raw.items()
        if isinstance(value, str) and value in _ACTIONS
    }


def _type_overrides(raw: Any) -> dict[str, str]:
    """``{ref: type_id}``. Существование типа проверяет реестр, не разбор."""
    if not isinstance(raw, dict):
        return {}
    return {str(ref): value for ref, value in raw.items() if isinstance(value, str) and value}


def _manual(raw: Any) -> list[dict[str, str]]:
    """Значения, которые движок пропустил, а оператор нашёл глазами.

    Адресуется значением, а не координатой в документе: одно и то же
    значение обязано получить один маркер во всём документе (инвариант
    согласованности псевдонимов), поэтому добавленное вручную ищется по
    всему тексту, а не только там, где оператор его выделил.
    """
    if not isinstance(raw, list):
        return []
    manual: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        type_id = item.get("type")
        if not isinstance(text, str) or not text.strip():
            continue
        if not isinstance(type_id, str) or not type_id:
            continue
        manual.append({"type": type_id, "text": text})
    return manual
