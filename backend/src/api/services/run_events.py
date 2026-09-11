"""Краткоживущие события хода прогона.

PII из `detect` остаётся только в памяти процесса и удаляется при завершении
прогона. Очередь исполнителя отделяет узел LangGraph от хранения событий.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor


class RunEventBroker:
    """Упорядоченный in-memory журнал активных прогонов."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[uuid.UUID, list[dict[str, object]]] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="run-events")

    def open(self, run_id: uuid.UUID) -> None:
        """Открыть журнал до запуска фонового графа."""
        with self._lock:
            self._events[run_id] = []

    def publish(self, run_id: uuid.UUID, node: str, content: dict[str, object]) -> None:
        """Поставить снимок в очередь и немедленно вернуть управление узлу."""
        self._executor.submit(self._append, run_id, node, dict(content))

    def _append(self, run_id: uuid.UUID, node: str, content: dict[str, object]) -> None:
        with self._lock:
            events = self._events.get(run_id)
            if events is not None:
                events.append({"sequence": len(events) + 1, "node": node, "content": content})

    def read(self, run_id: uuid.UUID, after: int = 0) -> list[dict[str, object]]:
        """Вернуть события после курсора; данные принадлежат активному прогону."""
        with self._lock:
            result: list[dict[str, object]] = []
            for item in self._events.get(run_id, []):
                sequence = item.get("sequence")
                if isinstance(sequence, int) and sequence > after:
                    result.append(dict(item))
            return result

    def close(self, run_id: uuid.UUID) -> None:
        """Удалить PII вместе с завершённым прогоном после очереди публикаций."""
        self._executor.submit(self._events.pop, run_id, None)


run_events = RunEventBroker()
