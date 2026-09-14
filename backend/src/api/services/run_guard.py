"""Отмена и таймаут активных прогонов.

Один синглтон ``run_guard`` на процесс: ``_execute`` регистрирует старт,
``notify_progress`` (через ``progress_observer``) вызывает ``check`` на
каждой границе узла. ``DELETE /api/runs/{id}`` вызывает ``cancel`` —
следующий ``check`` поднимет ``RunCancelledError(BaseException)``, которая
обходит ``except Exception`` внутри LangGraph и всплывает в ``execute_run``.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

from masker.run import RunCancelledError, RunTimedOutError

#: Максимальное время одного прохода графа; после — ``RunTimedOutError``.
RUN_TIMEOUT = timedelta(minutes=30)


class RunGuard:
    def __init__(self, timeout: timedelta = RUN_TIMEOUT) -> None:
        self._lock = threading.Lock()
        self._cancelled: set[uuid.UUID] = set()
        self._started_at: dict[uuid.UUID, datetime] = {}
        self._timeout = timeout

    def start(self, run_id: uuid.UUID) -> None:
        with self._lock:
            self._started_at[run_id] = datetime.now(UTC)
            self._cancelled.discard(run_id)

    def cancel(self, run_id: uuid.UUID) -> None:
        with self._lock:
            self._cancelled.add(run_id)

    def close(self, run_id: uuid.UUID) -> None:
        with self._lock:
            self._cancelled.discard(run_id)
            self._started_at.pop(run_id, None)

    def check(self, run_id: uuid.UUID) -> None:
        """Поднять исключение, если прогон отменён или вышел за лимит времени."""
        with self._lock:
            if run_id in self._cancelled:
                raise RunCancelledError(f"прогон {run_id} отменён оператором")
            started = self._started_at.get(run_id)
        if started is not None and datetime.now(UTC) - started > self._timeout:
            raise RunTimedOutError(
                f"прогон {run_id} превысил лимит {int(self._timeout.total_seconds() // 60)} минут"
            )


run_guard = RunGuard()
