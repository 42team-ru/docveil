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
        # Старые клиенты и уже сохранённые конверты завершают прогон, как
        # раньше. Только новая ручка перегенерации передаёт ``False``.
        "finalize": raw.get("finalize", True) is not False,
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


def _manual(raw: Any) -> list[dict[str, Any]]:
    """Значения, которые движок пропустил, а оператор нашёл глазами.

    Без `region` — адресуется значением, а не координатой: одно и то же
    значение обязано получить один маркер во всём документе (инвариант
    согласованности псевдонимов), поэтому добавленное вручную ищется по
    всему тексту, а не только там, где оператор его выделил.

    С `region` — оператор обвёл место на превью: адрес точный, текстовый
    поиск не нужен и не надёжен (OCR-шум на сканах может не совпасть с тем,
    что оператор напечатал глазами). `region` пропускается дальше как есть
    ({"page", "x0", "y0", "x1", "y1"}, все координаты 0..1); проверка формы
    и денормализация — за `_manual_entities` в графе, а не здесь.
    """
    if not isinstance(raw, list):
        return []
    manual: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        type_id = item.get("type")
        if not isinstance(text, str) or not text.strip():
            continue
        if not isinstance(type_id, str) or not type_id:
            continue
        entry: dict[str, Any] = {"type": type_id, "text": text}
        region = _region(item.get("region"))
        if region is not None:
            entry["region"] = region
        manual.append(entry)
    return manual


def _region(raw: Any) -> dict[str, float | int] | None:
    """`{page, x0, y0, x1, y1}`, все координаты 0..1, `x0<x1` и `y0<y1`.

    Форма уже проверена Pydantic-схемой (`BboxRegionIn`) на входе HTTP — эта
    проверка защищает `_manual_entities` от вызова напрямую (тесты, будущие
    вызывающие) с произвольным словарём, а не дублирует HTTP-валидацию.
    Некорректный `region` не роняет всю правку — молча игнорируется, и
    значение обрабатывается как обычный текстовый поиск (то же правило
    «непонятное отбрасывается молча», что у остального конверта).
    """
    if not isinstance(raw, dict):
        return None
    try:
        page = int(raw["page"])
        x0, y0, x1, y1 = (float(raw[key]) for key in ("x0", "y0", "x1", "y1"))
    except (KeyError, TypeError, ValueError):
        return None
    if page < 0:
        return None
    if not (0.0 <= x0 <= 1.0 and 0.0 <= y0 <= 1.0 and 0.0 <= x1 <= 1.0 and 0.0 <= y1 <= 1.0):
        return None
    if x0 >= x1 or y0 >= y1:
        return None
    return {"page": page, "x0": x0, "y0": y0, "x1": x1, "y1": y1}
