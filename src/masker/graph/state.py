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
