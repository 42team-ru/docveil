"""JSON-совместимое состояние части графа profile/judge."""

from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    path: str
    fmt: str
    segments: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    profiles: list[dict[str, Any]]
    unassigned: list[str]
    candidates: list[dict[str, Any]]
    verdicts: list[dict[str, Any]]
    questions: list[dict[str, Any]]
    answers: dict[str, str]
    diagnostics: list[str]
    #: Метаданные документа (имя файла, формат) — только JSON-скаляры, без
    #: датаклассов, чтобы состояние оставалось совместимым с чекпойнтером.
    meta: dict[str, Any]
    #: Опции прогона (типы, rules_only, profile, unmask_critical, ...), из
    #: которых считается детерминированный ``thread_id`` — раздел 5 плана T1.5.1.
    options: dict[str, Any]
    #: Вопросы политики (по типам и профилям) — раздел 5 плана T1.5.1.
    policy_questions: list[dict[str, Any]]
    #: Сводка решений для отчёта: режим, счётчики, диагностика.
    decisions: dict[str, Any]
    #: Итоговое действие на каждую ``ref`` после разрешения конфликтов,
    #: включая проигравшие решения (``overridden``) — раздел 4 плана T1.5.1.
    final_actions: list[dict[str, Any]]
