"""Трейсер обмена профилировщика с LLM.

Отладочный инструмент: показывает всю цепочку решения по каждому вызову —
что отправили модели, что она вернула дословно, что из ответа распарсилось,
что отсеяла валидация и что применилось к профилю и почему. Ничего из этого
не входит в обычный отчёт: без подключённого трейсера поведение остальных
агентов не меняется.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from masker.llm.base import LLMError, LLMProvider, LLMUsage, Message

TRACE_JSONL_NAME = "llm-trace.jsonl"
TRACE_MARKDOWN_NAME = "llm-trace.md"

_OUTCOME_LABELS: dict[str, str] = {
    "applied": "роль применена",
    "empty_role": "отклонена: модель вернула пустой role_title",
    "confidence_not_higher": "отклонена: уверенность модели не выше структурной",
    "confidence_below_threshold": "отклонена: уверенность модели ниже порога роли",
    "rejected_by_validation": "отклонена валидацией",
}


@dataclass(frozen=True, slots=True)
class CallTrace:
    """Один обмен с LLM: что отправлено и что вернулось дословно."""

    index: int
    messages: tuple[Message, ...]
    response: str | None
    error: str | None
    duration_ms: float
    request_chars: int
    response_chars: int


@dataclass(frozen=True, slots=True)
class ProfileOutcome:
    """Что стало с одним предложением модели по профилю и почему."""

    profile_id: str
    outcome: str
    old_role_title: str
    new_role_title: str
    old_confidence: float
    new_confidence: float
    reason: str = ""


@dataclass(frozen=True, slots=True)
class BatchTrace:
    """Диагностика разбора одного ответа модели: сколько предложено/выжило и что с чем стало."""

    call_index: int
    proposed_profiles: int
    valid_profiles: int
    outcomes: tuple[ProfileOutcome, ...]
    diagnostics: tuple[str, ...]


class TracingProvider:
    """Обёртка ``LLMProvider``, которая пишет трейс, не меняя поведения поставщика.

    Реализует тот же протокол ``complete(messages) -> str``, поэтому её можно
    передать в ``ProfileAgent`` вместо любого другого поставщика — согласно
    требованию заказчика №6 вызов модели идёт только через ``LLMProvider``.
    """

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.calls: list[CallTrace] = []
        self.batches: list[BatchTrace] = []

    @property
    def last_usage(self) -> LLMUsage | None:
        """Прозрачно отдать usage внутреннего поставщика обёртке учёта."""
        value = getattr(self._inner, "last_usage", None)
        return value if isinstance(value, LLMUsage) else None

    def complete(self, messages: list[Message], *, schema: dict[str, Any] | None = None) -> str:
        """Выполнить вызов внутреннего поставщика и записать его дословно.

        ``schema`` пробрасывается во внутренний поставщик без изменений —
        трейсер не часть контракта Р7-3, только прозрачная обёртка над ним.
        Без ``schema`` зовём внутренний `complete()` тем же способом, что и
        до Р7-3 (без keyword-аргумента), чтобы обёртка не требовала от
        старых реализаций `LLMProvider` поддержки нового параметра.
        """
        index = len(self.calls) + 1
        request_chars = sum(len(message.content) for message in messages)
        start = time.monotonic()
        try:
            response = (
                self._inner.complete(messages)
                if schema is None
                else self._inner.complete(messages, schema=schema)
            )
        except LLMError as error:
            duration_ms = (time.monotonic() - start) * 1000
            self.calls.append(
                CallTrace(
                    index=index,
                    messages=tuple(messages),
                    response=None,
                    error=str(error),
                    duration_ms=duration_ms,
                    request_chars=request_chars,
                    response_chars=0,
                )
            )
            raise
        duration_ms = (time.monotonic() - start) * 1000
        self.calls.append(
            CallTrace(
                index=index,
                messages=tuple(messages),
                response=response,
                error=None,
                duration_ms=duration_ms,
                request_chars=request_chars,
                response_chars=len(response),
            )
        )
        return response

    def record_batch(
        self,
        *,
        call_index: int,
        proposed_profiles: int,
        valid_profiles: int,
        outcomes: list[ProfileOutcome],
        diagnostics: list[str],
    ) -> None:
        """Записать, что случилось с профилями, предложенными в одном ответе модели."""
        self.batches.append(
            BatchTrace(
                call_index=call_index,
                proposed_profiles=proposed_profiles,
                valid_profiles=valid_profiles,
                outcomes=tuple(outcomes),
                diagnostics=tuple(diagnostics),
            )
        )


def write_trace(directory: Path, tracer: TracingProvider) -> tuple[Path, Path]:
    """Записать трейс на диск: ``llm-trace.jsonl`` машиночитаемо, ``llm-trace.md`` для человека.

    Файлы содержат исходные PII в открытом виде — тот же класс артефакта, что
    ``preview.docx``, и не предназначены для передачи наружу.
    """
    directory.mkdir(parents=True, exist_ok=True)
    jsonl_path = directory / TRACE_JSONL_NAME
    markdown_path = directory / TRACE_MARKDOWN_NAME
    _write_jsonl(jsonl_path, tracer)
    _write_markdown(markdown_path, tracer)
    jsonl_path.chmod(0o600)
    markdown_path.chmod(0o600)
    return jsonl_path, markdown_path


def _write_jsonl(path: Path, tracer: TracingProvider) -> None:
    lines: list[str] = []
    for call in tracer.calls:
        lines.append(
            json.dumps(
                {
                    "kind": "call",
                    "index": call.index,
                    "messages": [
                        {"role": message.role, "content": message.content}
                        for message in call.messages
                    ],
                    "response": call.response,
                    "error": call.error,
                    "duration_ms": call.duration_ms,
                    "request_chars": call.request_chars,
                    "response_chars": call.response_chars,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    for batch in tracer.batches:
        lines.append(
            json.dumps(
                {
                    "kind": "batch",
                    "call_index": batch.call_index,
                    "proposed_profiles": batch.proposed_profiles,
                    "valid_profiles": batch.valid_profiles,
                    "outcomes": [
                        {
                            "profile_id": outcome.profile_id,
                            "outcome": outcome.outcome,
                            "old_role_title": outcome.old_role_title,
                            "new_role_title": outcome.new_role_title,
                            "old_confidence": outcome.old_confidence,
                            "new_confidence": outcome.new_confidence,
                            "reason": outcome.reason,
                        }
                        for outcome in batch.outcomes
                    ],
                    "diagnostics": list(batch.diagnostics),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    text = "\n".join(lines)
    path.write_text(text + "\n" if text else "", encoding="utf-8")


def _write_markdown(path: Path, tracer: TracingProvider) -> None:
    batches_by_call = {batch.call_index: batch for batch in tracer.batches}
    parts: list[str] = ["# Трейс обмена с LLM", ""]
    if not tracer.calls:
        parts.append("Вызовов LLM не было.")
    for call in tracer.calls:
        parts.append(f"## Вызов {call.index}")
        parts.append("")
        parts.append(
            f"Длительность: {call.duration_ms:.1f} мс. "
            f"Запрос: {call.request_chars} симв. Ответ: {call.response_chars} симв."
        )
        parts.append("")
        for message in call.messages:
            parts.append(f"### Сообщение: {message.role}")
            parts.append("")
            parts.append("```")
            parts.append(message.content)
            parts.append("```")
            parts.append("")
        if call.error is not None:
            parts.append("### Ошибка")
            parts.append("")
            parts.append(call.error)
            parts.append("")
        else:
            parts.append("### Ответ модели (дословно)")
            parts.append("")
            parts.append("```")
            parts.append(call.response or "")
            parts.append("```")
            parts.append("")
        batch = batches_by_call.get(call.index)
        if batch is not None:
            parts.append(
                f"Профилей предложено: {batch.proposed_profiles}; "
                f"прошло валидацию: {batch.valid_profiles}."
            )
            parts.append("")
            if batch.diagnostics:
                parts.append("Диагностика разбора и валидации:")
                parts.append("")
                for diagnostic in batch.diagnostics:
                    parts.append(f"- {diagnostic}")
                parts.append("")
            if batch.outcomes:
                parts.append(
                    "| профиль | исход | роль было | роль стало | "
                    "уверенность было → стало | причина |"
                )
                parts.append("|---|---|---|---|---|---|")
                for outcome in batch.outcomes:
                    label = _OUTCOME_LABELS.get(outcome.outcome, outcome.outcome)
                    parts.append(
                        f"| {outcome.profile_id} | {label} | "
                        f"{outcome.old_role_title or '—'} | {outcome.new_role_title or '—'} | "
                        f"{outcome.old_confidence:.2f} → {outcome.new_confidence:.2f} | "
                        f"{outcome.reason or '—'} |"
                    )
                parts.append("")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
