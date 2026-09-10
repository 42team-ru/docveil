"""Учёт ресурсов прогона без PII и без нарушения детерминизма отчёта.

Длительности намеренно живут в ``runtime-metrics.json``, а не в
``report.json``: время исполнения не детерминировано. В State хранятся
только промежуточные данные, из которых в конце строятся два артефакта:
стабильная лента для отчёта и фактические runtime-метрики.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from masker.llm.base import LLMProvider, LLMUsage, Message

RUNTIME_METRICS_NAME = "runtime-metrics.json"


def _as_dict(value: object) -> dict[str, object]:
    """Честно проверить тип перед разбором нетипизированных данных State.

    В ``State`` телеметрия хранится как ``object``: LangGraph не знает
    нашей внутренней схемы. Если там окажется не словарь, это ошибка в
    другом узле — падать здесь молча в пустой словарь нельзя, но и
    поднимать исключение на каждый косвенный доступ избыточно, поэтому
    вызывающий код получает предсказуемое "нет данных" вместо утечки типа.
    """
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    """Аналог ``_as_dict`` для полей, которые обязаны быть списком."""
    return list(value) if isinstance(value, list) else []


def _int_or_none(value: object) -> int | None:
    """Достать int из нетипизированного поля, не путая его с bool."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _int_field(mapping: dict[str, object], key: str, default: int = 0) -> int:
    """Достать int-поле словаря с честным дефолтом вместо падения на мусоре."""
    value = _int_or_none(mapping.get(key))
    return default if value is None else value


def _float_field(mapping: dict[str, object], key: str, default: float = 0.0) -> float:
    """Достать float-поле словаря, принимая и int, но не bool."""
    value = mapping.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


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
    completion = _decimal_or_none(raw.get("completion_per_1k"), "llm.pricing.completion_per_1k")
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
        usage: LLMUsage | None = None
        try:
            response, usage = _complete_with_usage(self._inner, messages, schema=schema)
            return response
        finally:
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

    @property
    def calls(self) -> object:
        """Прозрачно отдать записи трассировки ProfileAgent'у, если она есть."""
        return getattr(self._inner, "calls", ())

    def delta_since(self, offset: int) -> tuple[int, list[dict[str, object]]]:
        return len(self._records), [dict(item) for item in self._records[offset:]]


def _complete_with_usage(
    provider: LLMProvider, messages: list[Message], *, schema: dict[str, Any] | None
) -> tuple[str, LLMUsage | None]:
    """Вызвать расширенный контракт только когда его реализует провайдер."""
    extended = getattr(provider, "complete_with_usage", None)
    if callable(extended):
        response, usage = (
            extended(messages) if schema is None else extended(messages, schema=schema)
        )
        return response, usage if isinstance(usage, LLMUsage) else None
    response = (
        provider.complete(messages)
        if schema is None
        else provider.complete(messages, schema=schema)
    )
    return response, None


def _provider_kind(provider: object) -> str:
    declared = getattr(provider, "provider_kind", None)
    if isinstance(declared, str) and declared:
        return declared.casefold()
    inner = getattr(provider, "_inner", None)
    if inner is not None:
        return _provider_kind(inner)
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
        str(name): _as_dict(value)
        for name, value in _as_dict(telemetry.get("stages", {})).items()
        if isinstance(value, dict)
    }
    stage = stages.setdefault(node, {"calls": 0, "duration_ms": 0.0})
    stage["calls"] = _int_field(stage, "calls") + 1
    stage["duration_ms"] = _float_field(stage, "duration_ms") + duration_ms

    events = [
        _as_dict(item) for item in _as_list(telemetry.get("events", [])) if isinstance(item, dict)
    ]
    previous_elapsed = _float_field(events[-1], "elapsed_ms") if events else 0.0
    events.append(
        {
            "sequence": len(events) + 1,
            "elapsed_ms": previous_elapsed + duration_ms,
            "node": node,
            "message": message,
        }
    )

    llm = _as_dict(telemetry.get("llm", {}))
    old_calls = [
        _as_dict(item) for item in _as_list(llm.get("calls", [])) if isinstance(item, dict)
    ]
    old_calls.extend(calls)
    llm["calls"] = old_calls
    llm["prompt_tokens"] = sum(
        tokens
        for item in old_calls
        if (tokens := _int_or_none(item.get("prompt_tokens"))) is not None
    )
    llm["completion_tokens"] = sum(
        tokens
        for item in old_calls
        if (tokens := _int_or_none(item.get("completion_tokens"))) is not None
    )
    return {**telemetry, "stages": stages, "events": events, "llm": llm}


def report_telemetry(telemetry: object, *, runtime_available: bool) -> dict[str, object]:
    """Детерминированная часть телеметрии для ``report.json``."""
    raw = dict(telemetry) if isinstance(telemetry, dict) else empty_telemetry()
    llm = _as_dict(raw.get("llm", {}))
    calls = [_as_dict(item) for item in _as_list(llm.get("calls", [])) if isinstance(item, dict)]
    pricing = pricing_from_dict(raw.get("pricing")) if raw.get("pricing") is not None else None
    usage = _usage_report(calls, pricing)
    events = [
        {
            "sequence": int(item["sequence"]),
            "node": str(item["node"]),
            "message": str(item["message"]),
        }
        for item in _as_list(raw.get("events", []))
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
            name: {
                "calls": int(value.get("calls", 0)),
                "duration_ms": value.get("duration_ms", 0.0),
            }
            for name, value in sorted(_as_dict(raw.get("stages", {})).items())
            if isinstance(value, dict)
        },
        "events": [
            dict(item) for item in _as_list(raw.get("events", [])) if isinstance(item, dict)
        ],
    }


def _usage_report(calls: list[dict[str, object]], pricing: LLMPricing | None) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for call in calls:
        grouped[str(call.get("node", "unknown"))].append(call)

    prompt = sum(
        tokens for item in calls if (tokens := _int_or_none(item.get("prompt_tokens"))) is not None
    )
    completion = sum(
        tokens
        for item in calls
        if (tokens := _int_or_none(item.get("completion_tokens"))) is not None
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
                tokens
                for item in items
                if (tokens := _int_or_none(item.get("prompt_tokens"))) is not None
            ),
            "completion_tokens": sum(
                tokens
                for item in items
                if (tokens := _int_or_none(item.get("completion_tokens"))) is not None
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
        # ``configured`` гарантирует, что оба тарифа заданы, но это свойство
        # dataclass, а не структурный тип, поэтому mypy не сужает
        # `Decimal | None` сам — проверяем честно, а не отбрасываем None.
        assert pricing.prompt_per_1k is not None, "LLMPricing.configured противоречит своим полям"
        assert pricing.completion_per_1k is not None, (
            "LLMPricing.configured противоречит своим полям"
        )
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
        "status": status,
        "message": message,
    }
    if prompt or completion:
        result["by_node"] = by_node
    if pricing is not None:
        result["pricing"] = pricing.as_dict()
    if status == "charged" and pricing is not None and pricing.configured:
        assert pricing.prompt_per_1k is not None
        assert pricing.completion_per_1k is not None
        amount = (
            Decimal(prompt) / Decimal(1000) * pricing.prompt_per_1k
            + Decimal(completion) / Decimal(1000) * pricing.completion_per_1k
        )
        result["cost"] = {"amount": format(amount, "f"), "currency": pricing.currency}
    else:
        result["cost"] = None
    return result
