"""Тесты загрузки и валидации пользовательской конфигурации типов (шаг 4 T1.13)."""

from __future__ import annotations

from typing import Any

import pytest

from masker.typeconfig import CustomTypeError, load_type_config


def _type(id_: str = "contract_no", **overrides: Any) -> dict[str, Any]:
    """Валидная запись типа по умолчанию — регулярка без context."""
    base: dict[str, Any] = {
        "id": id_,
        "title": "Номер договора",
        "marker": "[ДОГОВОР-{n}]",
        "detect": {"kind": "regex", "pattern": r"№\s?\d+/\d{4}", "ignorecase": False},
    }
    base.update(overrides)
    return base


def _config(*types: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "types": list(types)}


# ---------------------------------------------------------------------------
# Успешная загрузка
# ---------------------------------------------------------------------------


def test_valid_regex_type_loaded() -> None:
    specs = load_type_config(_config(_type()))
    assert len(specs) == 1
    spec = specs[0]
    assert spec.spec.id == "contract_no"
    assert spec.kind == "regex"
    assert spec.spec.marker_label == "ДОГОВОР"
    assert spec.context == ()
    assert spec.pattern.search("№ 44/2026") is not None


def test_valid_regex_type_with_context_loaded() -> None:
    item = _type(
        id_="shipment_date",
        title="Дата отгрузки",
        marker="[ДАТА-ОТГРУЗКИ-{n}]",
        detect={
            "kind": "regex",
            "pattern": r"\d{2}\.\d{2}\.\d{4}",
            "ignorecase": False,
            "context": ["отгрузк", "поставк"],
        },
    )
    specs = load_type_config(_config(item))
    assert specs[0].context == ("отгрузк", "поставк")


def test_valid_literals_type_loaded() -> None:
    item = _type(
        id_="internal_secret",
        title="Скрыть по списку",
        marker="[СКРЫТО-{n}]",
        detect={
            "kind": "literals",
            "values": ["Проект «Заря»", "внутренний код 42"],
            "match": "whole_word",
            "ignorecase": True,
        },
    )
    specs = load_type_config(_config(item))
    spec = specs[0]
    assert spec.kind == "literals"
    assert spec.pattern.search("у нас Проект «Заря» стартовал") is not None


def test_load_from_path(tmp_path: Any) -> None:
    yaml_text = r"""
version: 1
types:
  - id: contract_no
    title: Номер договора
    marker: "[ДОГОВОР-{n}]"
    detect:
      kind: regex
      pattern: "№\\s?\\d+/\\d{4}"
      ignorecase: false
"""
    path = tmp_path / "masker.types.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    specs = load_type_config(path)
    assert specs[0].spec.id == "contract_no"
    assert specs[0].pattern.search("№ 44/2026") is not None


def test_two_regex_types_and_one_literal_all_loaded() -> None:
    literal = _type(
        id_="internal_secret",
        title="Скрыть по списку",
        marker="[СКРЫТО-{n}]",
        detect={"kind": "literals", "values": ["Заря"], "match": "whole_word"},
    )
    specs = load_type_config(_config(_type(), literal))
    assert {s.spec.id for s in specs} == {"contract_no", "internal_secret"}


# ---------------------------------------------------------------------------
# Верхний уровень схемы
# ---------------------------------------------------------------------------


def test_unsupported_version_rejected() -> None:
    with pytest.raises(CustomTypeError, match="version"):
        load_type_config({"version": 2, "types": [_type()]})


def test_empty_types_list_rejected() -> None:
    with pytest.raises(CustomTypeError, match="types"):
        load_type_config({"version": 1, "types": []})


def test_types_not_list_rejected() -> None:
    with pytest.raises(CustomTypeError, match="types"):
        load_type_config({"version": 1, "types": {"id": "x"}})


# ---------------------------------------------------------------------------
# id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["Contract", "1abc", "ab", "contract-no", "с_кириллицей"])
def test_id_format_invalid_rejected(bad_id: str) -> None:
    with pytest.raises(CustomTypeError, match="id"):
        load_type_config(_config(_type(id_=bad_id)))


def test_id_collision_with_builtin() -> None:
    with pytest.raises(CustomTypeError, match="inn"):
        load_type_config(_config(_type(id_="inn")))


def test_duplicate_id_rejected() -> None:
    with pytest.raises(CustomTypeError) as exc_info:
        load_type_config(_config(_type(), _type()))
    message = str(exc_info.value)
    assert "contract_no" in message
    assert "#1" in message
    assert "#2" in message


# ---------------------------------------------------------------------------
# title / marker
# ---------------------------------------------------------------------------


def test_empty_title_rejected() -> None:
    with pytest.raises(CustomTypeError, match="title"):
        load_type_config(_config(_type(title="")))


def test_missing_title_rejected() -> None:
    item = _type()
    del item["title"]
    with pytest.raises(CustomTypeError, match="title"):
        load_type_config(_config(item))


def test_marker_without_placeholder_rejected() -> None:
    with pytest.raises(CustomTypeError, match="marker"):
        load_type_config(_config(_type(marker="[ДОГОВОР]")))


def test_marker_with_role_placeholder_accepted() -> None:
    specs = load_type_config(_config(_type(marker="[{role}-ДОГОВОР]")))
    assert specs[0].spec.marker_label == "ДОГОВОР"


# ---------------------------------------------------------------------------
# critical
# ---------------------------------------------------------------------------


def test_critical_true_emits_warning() -> None:
    with pytest.warns(UserWarning, match="critical"):
        specs = load_type_config(_config(_type(critical=True)))
    assert specs[0].spec.critical is True


def test_critical_false_by_default_no_warning(recwarn: pytest.WarningsRecorder) -> None:
    specs = load_type_config(_config(_type()))
    assert specs[0].spec.critical is False
    assert len(recwarn) == 0


# ---------------------------------------------------------------------------
# detect.kind
# ---------------------------------------------------------------------------


def test_unknown_detect_kind_rejected() -> None:
    with pytest.raises(CustomTypeError, match=r"detect\.kind"):
        load_type_config(_config(_type(detect={"kind": "gliner"})))


def test_detect_not_dict_rejected() -> None:
    with pytest.raises(CustomTypeError, match="detect"):
        load_type_config(_config(_type(detect="regex")))


def test_literals_without_values_rejected() -> None:
    with pytest.raises(CustomTypeError, match="values"):
        load_type_config(_config(_type(detect={"kind": "literals"})))


def test_literals_invalid_match_mode_rejected() -> None:
    with pytest.raises(CustomTypeError, match="match"):
        load_type_config(
            _config(_type(detect={"kind": "literals", "values": ["x"], "match": "regex"}))
        )


def test_regex_without_pattern_rejected() -> None:
    with pytest.raises(CustomTypeError, match="pattern"):
        load_type_config(_config(_type(detect={"kind": "regex"})))


def test_regex_context_not_list_of_strings_rejected() -> None:
    with pytest.raises(CustomTypeError, match="context"):
        load_type_config(
            _config(
                _type(
                    detect={
                        "kind": "regex",
                        "pattern": r"\d{2}\.\d{2}\.\d{4}",
                        "context": "отгрузк",
                    }
                )
            )
        )


# ---------------------------------------------------------------------------
# Валидатор регулярок: ReDoS и прочие опасности
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [r"(a+)+$", r"(a|a)*b", r"^(\w+\s?)*$"],
    ids=["nested-quantifier", "ambiguous-alternation", "nested-quantifier-in-group"],
)
def test_catastrophic_patterns_rejected(pattern: str) -> None:
    with pytest.raises(CustomTypeError) as exc_info:
        load_type_config(_config(_type(detect={"kind": "regex", "pattern": pattern})))
    assert "contract_no" in str(exc_info.value)


def test_valid_contract_number_pattern_accepted() -> None:
    specs = load_type_config(_config(_type(detect={"kind": "regex", "pattern": r"№\s?\d+/\d{4}"})))
    assert specs[0].pattern.search("договор № 44/2026") is not None


def test_empty_match_pattern_rejected() -> None:
    with pytest.raises(CustomTypeError, match="пуст"):
        load_type_config(_config(_type(detect={"kind": "regex", "pattern": "a*"})))


def test_backreference_pattern_rejected() -> None:
    with pytest.raises(CustomTypeError, match="обратн"):
        load_type_config(_config(_type(detect={"kind": "regex", "pattern": r"(\d+)-\1"})))


def test_pattern_too_long_rejected() -> None:
    long_pattern = r"\d" * 250
    with pytest.raises(CustomTypeError, match="200"):
        load_type_config(_config(_type(detect={"kind": "regex", "pattern": long_pattern})))


def test_pattern_with_disallowed_inline_flag_rejected() -> None:
    with pytest.raises(CustomTypeError, match="IGNORECASE"):
        load_type_config(_config(_type(detect={"kind": "regex", "pattern": r"(?m)^a$"})))


def test_pattern_with_ignorecase_flag_via_ignorecase_field_accepted() -> None:
    specs = load_type_config(
        _config(_type(detect={"kind": "regex", "pattern": r"№\s?\d+/\d{4}", "ignorecase": True}))
    )
    assert specs[0].pattern.search("№ 44/2026") is not None


def test_invalid_regex_syntax_rejected() -> None:
    with pytest.raises(CustomTypeError):
        load_type_config(_config(_type(detect={"kind": "regex", "pattern": "("})))
