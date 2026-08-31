"""Единый конверт вопросов и разбор ответов человека.

Один провод наружу для обоих видов вопросов (по классу — тип/профиль — и по
конкретной сущности), общий и с будущим видом ``kind: "pii"`` — раздел 5
плана T1.5.1. Веб рендерит вопросы обобщённо и не обязан знать про виды.
"""

from __future__ import annotations

from typing import Any

from masker.graph.state import State

#: Версия схемы конверта вопросов и файла ответов. Поднимается руками при
#: изменении состава обязательных ключей — защита от рассинхрона старого
#: веб-клиента с новым CLI/сервером.
SCHEMA_VERSION = 1

#: Ключи, обязательные у любого вопроса независимо от ``kind`` — контракт,
#: который веб умеет рендерить обобщённо.
REQUIRED_QUESTION_KEYS = (
    "id",
    "kind",
    "target",
    "title",
    "prompt",
    "options",
    "default",
    "critical",
    "found",
    "samples",
    "anchors",
)


def _anchor_labels(anchors: list[dict[str, Any]]) -> list[str]:
    return [str(anchor.get("label", "")) for anchor in anchors]


def _policy_question_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Вопрос политики (по типу или профилю) уже несёт все нужные поля."""
    return {
        "id": str(item["id"]),
        "kind": str(item["kind"]),
        "target": str(item["target"]),
        "title": str(item["title"]),
        "prompt": str(item["prompt"]),
        "options": [str(value) for value in item.get("options", [])],
        "default": str(item["default"]),
        "critical": bool(item["critical"]),
        "found": int(item["found"]),
        "samples": [str(value) for value in item.get("samples", [])],
        "anchors": _anchor_labels(item.get("anchors", [])),
    }


def _entity_question_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Вопрос судьи про конкретную сущность: разворачиваем ``key`` в тип/значение.

    ``Question`` (``model.py``) не несёт отдельного человекочитаемого
    заголовка или образца — это законная сущность более узкого назначения,
    чем ``PolicyQuestion``, поэтому title/samples строятся здесь из ``key``
    (``"<тип>:<нормализованное значение>"``).
    """
    key = str(item["key"])
    entity_type, _, value = key.partition(":")
    if not value:
        entity_type, value = key, ""
    return {
        "id": str(item["id"]),
        "kind": str(item["kind"]),
        "target": key,
        "title": entity_type,
        "prompt": str(item["prompt"]),
        "options": [str(v) for v in item.get("options", [])],
        "default": str(item["default"]),
        # Судья не спрашивает про критичное — инвариант AGENTS.md: ни один
        # Question.refs не ссылается на критичную сущность.
        "critical": False,
        "found": len(item.get("refs", [])),
        "samples": [value] if value else [],
        "anchors": _anchor_labels(item.get("anchors", [])),
    }


def build_ask_payload(state: State) -> dict[str, Any]:
    """Собрать единый плоский конверт: сначала вопросы политики, затем судьи.

    Одно прерывание на документ (``ask_human_node``) отдаёт наружу ровно этот
    словарь; он же — содержимое ``questions.json``.
    """
    meta = state.get("meta", {})
    options = state.get("options", {})
    questions = [_policy_question_payload(item) for item in state.get("policy_questions", [])]
    questions.extend(_entity_question_payload(item) for item in state.get("questions", []))
    return {
        "schema_version": SCHEMA_VERSION,
        "thread_id": str(options.get("thread_id", "")),
        "document": {
            "name": str(meta.get("name", "")),
            "format": str(meta.get("format", "")),
        },
        "questions": questions,
    }


def parse_answers(raw: dict[str, Any]) -> dict[str, str]:
    """Разобрать присланные ответы, отбраковав чужую версию схемы.

    Нестроковые значения молча отбрасываются: они не могут быть валидным
    вариантом из ``options`` и будут учтены как отсутствующий ответ выше по
    цепочке (``PolicyAgent.apply`` / ``JudgeAgent.apply_answers``).
    """
    schema_version = raw.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            "неверная версия схемы ответов: ожидалась "
            f"{SCHEMA_VERSION}, получена {schema_version!r}"
        )
    answers = raw.get("answers", {})
    return {str(key): value for key, value in answers.items() if isinstance(value, str)}
