"""Тесты Pydantic-схем пользовательских типов (T1.13, шаг 7).

Проверяется только форма тела запроса — сами Pydantic-модели, без
FastAPI-приложения и без сети: маршруты появляются в шаге 8
(`tests/api/test_custom_types_router.py`), тут они ещё не нужны.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from api.schemas.custom_types import (
    AnswerRequest,
    CompileRequest,
    CompileResponse,
    CustomTypeSpecIn,
    FailedTypeOut,
    FailReason,
)
from masker.typeconfig import load_type_config


def _valid_regex_type(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": 1,
        "id": "shipment_date",
        "title": "Дата отгрузки",
        "marker": "[ДАТА-ОТГРУЗКИ-{n}]",
        "critical": False,
        "detect": {
            "kind": "regex",
            "pattern": r"\d{2}\.\d{2}\.\d{4}",
            "context": ["отгрузк", "поставк"],
        },
    }
    base.update(overrides)
    return base


def _valid_literals_type(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": 1,
        "id": "product_code",
        "title": "Код товара",
        "marker": "[КОД-ТОВАРА-{n}]",
        "critical": True,
        "detect": {"kind": "literals", "values": ["SKU-ABC-42"]},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# CustomTypeSpecIn — форма тела
# ---------------------------------------------------------------------------


def test_valid_regex_spec_is_accepted() -> None:
    spec = CustomTypeSpecIn.model_validate(_valid_regex_type())
    assert spec.id == "shipment_date"
    assert spec.detect.kind == "regex"


def test_valid_literals_spec_is_accepted() -> None:
    spec = CustomTypeSpecIn.model_validate(_valid_literals_type())
    assert spec.id == "product_code"
    assert spec.detect.kind == "literals"


def test_unknown_detect_kind_is_rejected() -> None:
    payload = _valid_regex_type(detect={"kind": "sql_injection", "pattern": "x"})
    with pytest.raises(ValidationError) as excinfo:
        CustomTypeSpecIn.model_validate(payload)
    locations = [error["loc"] for error in excinfo.value.errors()]
    assert any("detect" in loc for loc in locations), locations


def test_unknown_schema_version_is_rejected() -> None:
    payload = _valid_regex_type(schema_version=2)
    with pytest.raises(ValidationError) as excinfo:
        CustomTypeSpecIn.model_validate(payload)
    locations = [error["loc"] for error in excinfo.value.errors()]
    assert any("schema_version" in loc for loc in locations), locations


def test_missing_detect_field_for_kind_is_rejected() -> None:
    """`regex` без `pattern` — форма нарушена, а не «пустой паттерн допустим»."""
    payload = _valid_regex_type(detect={"kind": "regex"})
    with pytest.raises(ValidationError):
        CustomTypeSpecIn.model_validate(payload)


def test_literals_requires_non_empty_values() -> None:
    payload = _valid_literals_type(detect={"kind": "literals", "values": []})
    with pytest.raises(ValidationError):
        CustomTypeSpecIn.model_validate(payload)


def test_gliner_label_requires_description() -> None:
    payload = _valid_regex_type(
        id="delivery_person",
        detect={"kind": "gliner_label", "label": "Получатель груза"},
    )
    with pytest.raises(ValidationError):
        CustomTypeSpecIn.model_validate(payload)


def test_gliner_structure_requires_structure_and_field() -> None:
    payload = _valid_regex_type(
        id="delivery_role",
        detect={
            "kind": "gliner_structure",
            "label": "Получатель груза",
            "description": "ФИО рядом со словом «получатель» в таблице",
        },
    )
    with pytest.raises(ValidationError):
        CustomTypeSpecIn.model_validate(payload)


# ---------------------------------------------------------------------------
# Мост к `load_type_config` — единственному месту проверки регулярок
# ---------------------------------------------------------------------------


def test_valid_body_round_trips_through_load_type_config() -> None:
    spec_in = CustomTypeSpecIn.model_validate(_valid_regex_type())
    compiled = load_type_config({"version": 1, "types": [spec_in.model_dump(mode="json")]})
    assert len(compiled) == 1
    assert compiled[0].spec.id == "shipment_date"
    assert compiled[0].kind == "regex"
    assert compiled[0].context == ("отгрузк", "поставк")


def test_valid_literals_body_round_trips_through_load_type_config() -> None:
    spec_in = CustomTypeSpecIn.model_validate(_valid_literals_type())
    compiled = load_type_config({"version": 1, "types": [spec_in.model_dump(mode="json")]})
    assert len(compiled) == 1
    assert compiled[0].spec.id == "product_code"
    assert compiled[0].spec.critical is True


# ---------------------------------------------------------------------------
# CompileRequest / CompileResponse / AnswerRequest — форма конвертов
# ---------------------------------------------------------------------------


def test_compile_request_requires_non_empty_descriptions() -> None:
    with pytest.raises(ValidationError):
        CompileRequest.model_validate({"object_name": "documents/x.docx", "descriptions": []})


def test_compile_request_valid() -> None:
    request = CompileRequest.model_validate(
        {"object_name": "documents/x.docx", "descriptions": ["замажь даты отгрузки"]}
    )
    assert request.object_name == "documents/x.docx"
    assert request.descriptions == ["замажь даты отгрузки"]


def test_compile_response_accepts_cannot_compile_shape() -> None:
    response = CompileResponse.model_validate(
        {
            "thread_id": "abc123",
            "status": "done",
            "engine_capabilities": ["literals", "regex"],
            "compiled": [],
            "failed": [{"index": 0, "description": "замажь номера морозильников", "reason": "..."}],
            "questions": [],
        }
    )
    assert response.status == "done"
    assert response.failed[0].index == 0


def test_compile_response_accepts_compiled_spec() -> None:
    response = CompileResponse.model_validate(
        {
            "thread_id": "abc123",
            "status": "done",
            "engine_capabilities": ["literals", "regex"],
            "compiled": [
                {
                    "spec": _valid_regex_type(),
                    "outcome": "compile",
                    "preview": {
                        "segments": [
                            {
                                "segment_order": 0,
                                "anchor_label": "п. 1",
                                "text": "Дата отгрузки: 20.03.2026",
                                "matches": [{"start": 15, "end": 25, "value": "20.03.2026"}],
                            }
                        ],
                        "total_matches": 1,
                    },
                }
            ],
            "failed": [],
            "questions": [],
        }
    )
    assert response.compiled[0].spec.id == "shipment_date"
    assert response.compiled[0].preview is not None
    assert response.compiled[0].preview.total_matches == 1


def test_answer_request_default_schema_version() -> None:
    request = AnswerRequest.model_validate({"answers": {"Q1": "mask"}})
    assert request.schema_version == 1
    assert request.answers == {"Q1": "mask"}


def test_answer_request_rejects_unknown_schema_version() -> None:
    with pytest.raises(ValidationError):
        AnswerRequest.model_validate({"schema_version": 2, "answers": {}})


# ---------------------------------------------------------------------------
# CompileRequest.descriptions — граничные значения длины (задача 2.1)
# ---------------------------------------------------------------------------


def test_compile_request_rejects_empty_description() -> None:
    with pytest.raises(ValidationError):
        CompileRequest.model_validate({"object_name": "doc.docx", "descriptions": [""]})


def test_compile_request_rejects_whitespace_only_description() -> None:
    with pytest.raises(ValidationError):
        CompileRequest.model_validate({"object_name": "doc.docx", "descriptions": ["       "]})


def test_compile_request_rejects_too_short_description() -> None:
    with pytest.raises(ValidationError):
        CompileRequest.model_validate({"object_name": "doc.docx", "descriptions": ["паспорт"]})


def test_compile_request_accepts_minimum_length_description() -> None:
    request = CompileRequest.model_validate(
        {"object_name": "doc.docx", "descriptions": ["паспорта"]}
    )
    assert request.descriptions == ["паспорта"]


def test_compile_request_rejects_too_long_description() -> None:
    with pytest.raises(ValidationError):
        CompileRequest.model_validate({"object_name": "doc.docx", "descriptions": ["а" * 1001]})


def test_compile_request_trims_leading_trailing_whitespace() -> None:
    request = CompileRequest.model_validate(
        {"object_name": "doc.docx", "descriptions": ["  замажь даты отгрузки  "]}
    )
    assert request.descriptions == ["замажь даты отгрузки"]


# ---------------------------------------------------------------------------
# FailReason и FailedTypeOut — код ошибки (задача 2.3)
# ---------------------------------------------------------------------------


def test_failed_type_out_default_code_is_cannot_compile() -> None:
    out = FailedTypeOut(index=0, description="x", reason="y")
    assert out.code == FailReason.cannot_compile


def test_failed_type_out_accepts_known_code() -> None:
    out = FailedTypeOut(index=0, description="x", reason="y", code=FailReason.llm_unavailable)
    assert out.code == FailReason.llm_unavailable


def test_compile_response_serialises_fail_reason_code() -> None:
    response = CompileResponse.model_validate(
        {
            "thread_id": "abc",
            "status": "done",
            "compiled": [],
            "failed": [
                {
                    "index": 0,
                    "description": "что-то непонятное",
                    "reason": "слишком общее",
                    "code": "cannot_compile",
                }
            ],
            "questions": [],
        }
    )
    assert response.failed[0].code == FailReason.cannot_compile
