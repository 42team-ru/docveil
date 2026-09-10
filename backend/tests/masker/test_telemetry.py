"""Учёт ресурсов прогона: безопасность ленты и граница детерминизма."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from masker.graph.nodes import RunDeps
from masker.llm import LLMUsage, Message
from masker.run import RunOptions, report_of, start_run
from masker.telemetry import (
    RUNTIME_METRICS_NAME,
    LLMPricing,
    MeteringProvider,
    report_telemetry,
    runtime_metrics,
)

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"


class _UsageProvider:
    def complete(self, messages: list[Message]) -> str:
        del messages
        return "ok"

    def complete_with_usage(self, messages: list[Message]) -> tuple[str, LLMUsage]:
        del messages
        return "ok", LLMUsage(prompt_tokens=120, completion_tokens=30)


def test_metering_provider_binds_usage_to_calling_graph_node() -> None:
    meter = MeteringProvider(
        _UsageProvider(),
        LLMPricing(Decimal("2"), Decimal("4"), "RUB", "2026-09-10"),
    )

    with meter.for_stage("profile"):
        assert meter.complete([Message("user", "не попадает в отчёт")]) == "ok"

    _, calls = meter.delta_since(0)
    report = report_telemetry(
        {
            "events": [],
            "stages": {},
            "llm": {"calls": calls},
            "pricing": meter.pricing.as_dict(),
        },
        runtime_available=True,
    )
    llm = report["llm"]
    assert llm["by_node"] == [
        {"node": "profile", "calls": 1, "prompt_tokens": 120, "completion_tokens": 30}
    ]
    assert llm["cost"] == {"amount": "0.36", "currency": "RUB"}


def test_usage_report_says_when_no_call_returned_usage() -> None:
    llm = report_telemetry(
        {
            "llm": {
                "calls": [
                    {"node": "profile", "provider": "gigachat"},
                    {"node": "judge", "provider": "gigachat"},
                ]
            },
            "pricing": LLMPricing(Decimal("2"), Decimal("4"), "RUB", "2026-09-10").as_dict(),
        },
        runtime_available=False,
    )["llm"]

    assert llm["status"] == "usage_unavailable"
    assert llm["message"] == "Токены не вернул поставщик; стоимость не рассчитывалась."
    assert llm["cost"] is None


def test_usage_report_charges_exactly_when_every_call_returned_usage() -> None:
    llm = report_telemetry(
        {
            "llm": {
                "calls": [
                    {
                        "node": "profile",
                        "provider": "gigachat",
                        "prompt_tokens": 100,
                        "completion_tokens": 10,
                    },
                    {
                        "node": "judge",
                        "provider": "gigachat",
                        "prompt_tokens": 200,
                        "completion_tokens": 20,
                    },
                ]
            },
            "pricing": LLMPricing(Decimal("2"), Decimal("4"), "RUB", "2026-09-10").as_dict(),
        },
        runtime_available=False,
    )["llm"]

    assert llm["status"] == "charged"
    assert llm["message"] == "Потрачено 0.72 RUB."
    assert llm["cost"] == {"amount": "0.72", "currency": "RUB"}


def test_usage_report_estimates_lower_bound_when_only_some_calls_returned_usage() -> None:
    llm = report_telemetry(
        {
            "llm": {
                "calls": [
                    {
                        "node": "profile",
                        "provider": "gigachat",
                        "prompt_tokens": 100,
                        "completion_tokens": 10,
                    },
                    {
                        "node": "judge",
                        "provider": "gigachat",
                        "prompt_tokens": 200,
                        "completion_tokens": 20,
                    },
                    {"node": "judge", "provider": "gigachat"},
                ]
            },
            "pricing": LLMPricing(Decimal("2"), Decimal("4"), "RUB", "2026-09-10").as_dict(),
        },
        runtime_available=False,
    )["llm"]

    assert llm["status"] == "charged_lower_bound"
    assert llm["message"] == (
        "Не менее 0.72 RUB: usage вернули 2 из 3 вызовов, остальные в расчёт не вошли."
    )
    assert llm["cost"] == {"amount": "0.72", "currency": "RUB", "kind": "lower_bound"}


def test_report_is_deterministic_while_runtime_file_contains_stage_times(tmp_path: Path) -> None:
    options = RunOptions(rules_only=True, interactive=False, preview=False)
    first = start_run(
        FIXTURE,
        options,
        checkpointer_factory=lambda: InMemorySaver(),
        deps=RunDeps(artifact_dir=tmp_path / "first"),
    )
    second = start_run(
        FIXTURE,
        options,
        checkpointer_factory=lambda: InMemorySaver(),
        deps=RunDeps(artifact_dir=tmp_path / "second"),
    )

    first_report = report_of(first)
    second_report = report_of(second)
    assert first_report == second_report
    assert first_report["telemetry"]["llm"] == {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "status": "model_not_needed",
        "message": "Потрачено 0: модель не понадобилась для этого документа.",
        "cost": None,
    }
    assert all("770" not in item["message"] for item in first_report["telemetry"]["events"])

    runtime_path = tmp_path / "first" / RUNTIME_METRICS_NAME
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert json.loads(json.dumps(runtime_metrics({"events": [], "stages": {}}))) == {
        "schema_version": 1,
        "stages": {},
        "events": [],
    }
    assert runtime["stages"]["detect"]["duration_ms"] >= 0
    assert {item["node"] for item in runtime["events"]} >= {"extract", "detect", "report"}


def test_cassette_is_honestly_reported_as_zero_network_cost() -> None:
    report = report_telemetry(
        {
            "events": [],
            "stages": {},
            "llm": {
                "calls": [
                    {
                        "node": "profile",
                        "provider": "cassette",
                        "prompt_tokens": None,
                        "completion_tokens": None,
                    }
                ]
            },
        },
        runtime_available=True,
    )

    assert report["llm"] == {
        "calls": 1,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "status": "offline_cassette",
        "message": (
            "Потрачено 0: использованы записанные ответы (cassette), сеть не использовалась."
        ),
        "cost": None,
    }
