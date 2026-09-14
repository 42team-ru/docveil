"""Ответ компилятора своих типов: нормализация имени исполнителя детекции."""

from __future__ import annotations

from api.services.custom_types_service import _compiled_out, _normalized_spec

_SPEC = {
    "id": "shipment_date",
    "title": "Дата отгрузки",
    "marker": "[ДАТА-ОТГРУЗКИ-{n}]",
    "detect": {
        "kind": "regex_context",
        "pattern": r"\d{2}\.\d{2}\.\d{4}",
        "context": ["отгрузк"],
        "ignorecase": True,
    },
}


def test_regex_context_is_normalized_to_regex() -> None:
    """LLM возвращает имя исполнителя, схема ответа знает только `regex`."""
    normalized = _normalized_spec(_SPEC)

    assert normalized["detect"]["kind"] == "regex"
    # Остальные поля не трогаются, исходный словарь не мутируется.
    assert normalized["detect"]["context"] == ["отгрузк"]
    assert _SPEC["detect"]["kind"] == "regex_context"


def test_known_kind_passes_through_unchanged() -> None:
    """Уже нормальный `kind` возвращается тем же объектом, без копирования."""
    spec = {**_SPEC, "detect": {**_SPEC["detect"], "kind": "regex"}}

    assert _normalized_spec(spec) is spec


def test_compiled_out_accepts_compiler_output_with_executor_name() -> None:
    """Без нормализации ответ падал `union_tag_invalid` уже на валидации."""
    out = _compiled_out({"outcome_kind": "compile", "spec": _SPEC})

    assert out.outcome == "compile"
    assert out.spec is not None
    assert out.spec.detect.kind == "regex"
