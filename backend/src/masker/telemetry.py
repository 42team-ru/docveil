"""Учёт ресурсов прогона без PII и без нарушения детерминизма отчёта.

Длительности намеренно живут в ``runtime-metrics.json``, а не в
``report.json``: время исполнения не детерминировано. В State хранятся
только промежуточные данные, из которых в конце строятся два артефакта:
стабильная лента для отчёта и фактические runtime-метрики.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

from masker.llm.base import LLMProvider, LLMUsage, Message

RUNTIME_METRICS_NAME = "runtime-metrics.json"


@dataclass(frozen=True, slots=True)
class LLMPricing:
    """Тариф модели из конфигурации, без догадок при отсутствующей цене."""

    prompt_per_1k: Decimal | None = None
    completion_per_1k: Decimal | None = None
    currency: str = "RUB"
    verified_at: str = ""

    @property
    def configured(self) -> bool:
        return self.prompt_per_1k is not None and self.completion_per_1k is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "prompt_per_1k": str(self.prompt_per_1k) if self.prompt_per_1k is not None else None,
            "completion_per_1k": (
                str(self.completion_per_1k) if self.completion_per_1k is not None else None
            ),
            "currency": self.currency,
            "verified_at": self.verified_at,
        }


def pricing_from_dict(raw: object) -> LLMPricing | None:
    """Прочитать валидированную конфигурацию тарифа в независимый тип."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("llm.pricing должна быть YAML-объектом")
    prompt = _decimal_or_none(raw.get("prompt_per_1k"), "llm.pricing.prompt_per_1k")
    completion = _decimal_or_none(
        raw.get("completion_per_1k"), "llm.pricing.completion_per_1k"
    )
    if (prompt is None) != (completion is None):
        raise ValueError("задайте оба тарифа llm.pricing или не задавайте ни одного")
    currency = raw.get("currency", "RUB")
    verified_at = raw.get("verified_at", "")
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("llm.pricing.currency должна быть непустой строкой")
    if not isinstance(verified_at, str):
        raise ValueError("llm.pricing.verified_at должна быть строкой")
    if prompt is not None and not verified_at.strip():
        raise ValueError("для заданного тарифа укажите llm.pricing.verified_at")
    return LLMPricing(prompt, completion, currency.strip().upper(), verified_at.strip())


def _decimal_or_none(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, int | float | str) or isinstance(value, bool):
        raise ValueError(f"{field_name} должна быть неотрицательным числом или null")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"{field_name} должна быть числом") from error
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field_name} должна быть неотрицательным числом")
    return number


class MeteringProvider:
    """Обёртка LLMProvider, связывающая фактический usage с узлом графа.

    Узлы не знают ни GigaChat, ни OpenRouter: они только получают провайдер
    для своего имени. Маркер узла проставляется в обёртке вызывающего,
    поэтому замена реализации модели не меняет логику графа.
    """

    def __init__(self, inner: LLMProvider, pricing: LLMPricing | None = None) -> None:
        self._inner = inner
        self.pricing = pricing
        self._stage = "unknown"
        self._records: list[dict[str, object]] = []

    @contextmanager
    def for_stage(self, stage: str) -> Iterator[MeteringProvider]:
        previous, self._stage = self._stage, stage
        try:
            yield self
        finally:
            self._stage = previous

    def complete(self, messages: list[Message], *, schema: dict[str, Any] | None = None) -> str:
        try:
            return (
                self._inner.complete(messages)
                if schema is None
                else self._inner.complete(messages, schema=schema)
            )
        finally:
            usage = _usage_of(self._inner)
            self._records.append(
                {
                    "node": self._stage,
                    "provider": _provider_kind(self._inner),
                    "prompt_tokens": usage.prompt_tokens if usage is not None else None,
                    "completion_tokens": usage.completion_tokens if usage is not None else None,
                }
            )

    def record_batch(self, **kwargs: object) -> None:
        """Не потерять профильный LLM-трейс под дополнительной обёрткой."""
        recorder = getattr(self._inner, "record_batch", None)
        if callable(recorder):
            recorder(**kwargs)

    def delta_since(self, offset: int) -> tuple[int, list[dict[str, object]]]:
        return len(self._records), [dict(item) for item in self._records[offset:]]


def _usage_of(provider: object) -> LLMUsage | None:
    value = getattr(provider, "last_usage", None)
    return value if isinstance(value, LLMUsage) else None


def _provider_kind(provider: object) -> str:
    declared = getattr(provider, "provider_kind", None)
    if isinstance(declared, str) and declared:
        return declared.casefold()
    name = provider.__class__.__name__.removesuffix("Provider").casefold()
    return name or "unknown"


def empty_telemetry(*, pricing: LLMPricing | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "stages": {},
        "events": [],
        "llm": {"calls": [], "prompt_tokens": 0, "completion_tokens": 0},
    }
    if pricing is not None:
        result["pricing"] = pricing.as_dict()
    return result


def append_stage(
    previous: object,
    *,
    node: str,
    duration_ms: float,
    message: str,
    calls: list[dict[str, object]],
    pricing: LLMPricing | None,
) -> dict[str, object]:
    """Добавить замер и безопасное событие, сохранив JSON-совместимость State."""
    telemetry = dict(previous) if isinstance(previous, dict) else empty_telemetry(pricing=pricing)
    if pricing is not None and "pricing" not in telemetry:
        telemetry["pricing"] = pricing.as_dict()
    stages = {
        str(name): dict(value)
        for name, value in dict(telemetry.get("stages", {})).items()
        if isinstance(value, dict)
    }
    stage = stages.setdefault(node, {"calls": 0, "duration_ms": 0.0})
    stage["calls"] = int(stage.get("calls", 0)) + 1
    stage["duration_ms"] = float(stage.get("duration_ms", 0.0)) + duration_ms

    events = [dict(item) for item in telemetry.get("events", []) if isinstance(item, dict)]
    previous_elapsed = float(events[-1].get("elapsed_ms", 0.0)) if events else 0.0
    events.append(
        {
            "sequence": len(events) + 1,
            "elapsed_ms": previous_elapsed + duration_ms,
            "node": node,
            "message": message,
        }
    )

    llm = dict(telemetry.get("llm", {}))
    old_calls = [dict(item) for item in llm.get("calls", []) if isinstance(item, dict)]
    old_calls.extend(calls)
    llm["calls"] = old_calls
    llm["prompt_tokens"] = sum(
        int(item["prompt_tokens"])
        for item in old_calls
        if isinstance(item.get("prompt_tokens"), int)
    )
    llm["completion_tokens"] = sum(
        int(item["completion_tokens"])
        for item in old_calls
        if isinstance(item.get("completion_tokens"), int)
    )
    return {**telemetry, "stages": stages, "events": events, "llm": llm}


def report_telemetry(telemetry: object, *, runtime_available: bool) -> dict[str, object]:
    """Детерминированная часть телеметрии для ``report.json``."""
    raw = dict(telemetry) if isinstance(telemetry, dict) else empty_telemetry()
    llm = dict(raw.get("llm", {}))
    calls = [dict(item) for item in llm.get("calls", []) if isinstance(item, dict)]
    pricing = pricing_from_dict(raw.get("pricing")) if raw.get("pricing") is not None else None
    usage = _usage_report(calls, pricing)
    events = [
        {"sequence": int(item["sequence"]), "node": str(item["node"]), "message": str(item["message"])}
        for item in raw.get("events", [])
        if isinstance(item, dict)
    ]
    runtime: dict[str, object] = {
        "available": runtime_available,
        "artifact": RUNTIME_METRICS_NAME if runtime_available else None,
        "note": (
            "Длительности стадий и относительное время событий записаны отдельно, "
            "чтобы report.json оставался побайтово детерминированным."
        ),
    }
    return {"events": events, "llm": usage, "runtime": runtime}


def runtime_metrics(telemetry: object) -> dict[str, object]:
    """Недетерминированный companion-файл с миллисекундами, без PII."""
    raw = dict(telemetry) if isinstance(telemetry, dict) else empty_telemetry()
    return {
        "schema_version": 1,
        "stages": {
            name: {"calls": int(value.get("calls", 0)), "duration_ms": value.get("duration_ms", 0.0)}
            for name, value in sorted(dict(raw.get("stages", {})).items())
            if isinstance(value, dict)
        },
        "events": [dict(item) for item in raw.get("events", []) if isinstance(item, dict)],
    }


def _usage_report(calls: list[dict[str, object]], pricing: LLMPricing | None) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for call in calls:
        grouped[str(call.get("node", "unknown"))].append(call)

    prompt = sum(int(item["prompt_tokens"]) for item in calls if isinstance(item.get("prompt_tokens"), int))
    completion = sum(
        int(item["completion_tokens"])
        for item in calls
        if isinstance(item.get("completion_tokens"), int)
    )
    known_calls = sum(
        item.get("prompt_tokens") is not None and item.get("completion_tokens") is not None
        for item in calls
    )
    by_node = [
        {
            "node": node,
            "calls": len(items),
            "prompt_tokens": sum(
                int(item["prompt_tokens"])
                for item in items
                if isinstance(item.get("prompt_tokens"), int)
            ),
            "completion_tokens": sum(
                int(item["completion_tokens"])
                for item in items
                if isinstance(item.get("completion_tokens"), int)
            ),
        }
        for node, items in sorted(grouped.items())
    ]
    providers = {str(item.get("provider", "unknown")) for item in calls}
    if not calls:
        message = "Потрачено 0: модель не понадобилась для этого документа."
        status = "model_not_needed"
    elif providers == {"cassette"}:
        message = "Потрачено 0: использованы записанные ответы (cassette), сеть не использовалась."
        status = "offline_cassette"
    elif known_calls != len(calls):
        message = "Токены не вернул поставщик; стоимость не рассчитывалась."
        status = "usage_unavailable"
    elif pricing is None or not pricing.configured:
        message = "Токены учтены, но тариф не задан; стоимость не рассчитывалась."
        status = "tariff_not_configured"
    else:
        amount = (
            Decimal(prompt) / Decimal(1000) * pricing.prompt_per_1k
            + Decimal(completion) / Decimal(1000) * pricing.completion_per_1k
        )
        message = f"Потрачено {format(amount, 'f')} {pricing.currency}."
        status = "charged"
    result: dict[str, object] = {
        "calls": len(calls),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "by_node": by_node,
        "status": status,
        "message": message,
    }
    if pricing is not None:
        result["pricing"] = pricing.as_dict()
    if status == "charged" and pricing is not None:
        amount = (
            Decimal(prompt) / Decimal(1000) * pricing.prompt_per_1k
            + Decimal(completion) / Decimal(1000) * pricing.completion_per_1k
        )
        result["cost"] = {"amount": format(amount, "f"), "currency": pricing.currency}
    else:
        result["cost"] = None
    return result
