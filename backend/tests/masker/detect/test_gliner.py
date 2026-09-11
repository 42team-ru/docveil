"""Контракт GLiNER2-адаптера без загрузки тяжёлой модели."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

import pytest

from masker.detect.agent import DetectAgent
from masker.detect.gliner import GlinerDetector, verify_runtime_versions
from masker.entity_types import EntityTypeRegistry
from masker.model import Anchor, Document, Segment, Source
from masker.typeconfig import load_type_config

# 11.09.2026: проверки пути к весам достижимы только с установленным GLiNER2.
# В CI extra намеренно не ставится, но тесты защиты от отсутствующего runtime
# должны продолжать выполняться там, а не исчезать вместе с этим сценарием.
_GLINER2_INSTALLED = importlib.util.find_spec("gliner2") is not None


class FakeGliner:
    def extract_entities(self, text: str, labels: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["include_spans"] is True
        return {
            "entities": {
                "должность": [
                    {"text": "главный инженер", "start": 0, "end": 15, "confidence": 0.91},
                    # Старый формат без offsets: адаптер обязан найти второе вхождение.
                    "главный инженер",
                ]
            }
        }


class EmptyGliner:
    def extract_entities(self, text: str, labels: Any, **kwargs: Any) -> dict[str, Any]:
        return {"entities": {"должность": []}}


class StructureSchema:
    def __init__(self) -> None:
        self.fields: list[str] = []

    def structure(self, name: str) -> StructureSchema:
        assert name == "custom_entities"
        return self

    def field(self, name: str, **kwargs: Any) -> StructureSchema:
        assert kwargs["dtype"] == "str"
        self.fields.append(name)
        return self


class FakeStructureGliner:
    def __init__(self) -> None:
        self.schema = StructureSchema()
        self.calls = 0

    def create_schema(self) -> StructureSchema:
        return self.schema

    def extract(self, text: str, schema: StructureSchema, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        assert schema is self.schema
        assert set(schema.fields) == {"shipment_date", "signing_date"}
        signing_start = text.index("12.02.2026")
        shipment_start = text.index("12.02.2026", signing_start + 1)
        return {
            "custom_entities": [
                {
                    "signing_date": {
                        "text": "12.02.2026",
                        "start": signing_start,
                        "end": signing_start + 10,
                        "confidence": 0.99,
                    },
                    "shipment_date": {
                        "text": "12.02.2026",
                        "start": shipment_start,
                        "end": shipment_start + 10,
                        "confidence": 0.98,
                    },
                }
            ]
        }


def _specs():
    return load_type_config(
        {
            "version": 1,
            "types": [
                {
                    "id": "job_title",
                    "title": "Должность",
                    "marker": "[ДОЛЖНОСТЬ-{n}]",
                    "detect": {
                        "kind": "gliner_label",
                        "label": "должность",
                        "description": "Название должности сотрудника",
                        "threshold": 0.3,
                    },
                }
            ],
        }
    )


def _structure_specs():
    return load_type_config(
        {
            "version": 1,
            "types": [
                {
                    "id": "shipment_date",
                    "title": "Дата отгрузки",
                    "marker": "[ОТГРУЗКА-{n}]",
                    "detect": {
                        "kind": "gliner_structure",
                        "label": "дата отгрузки",
                        "description": "Дата фактической отгрузки товара",
                        "structure": "shipment",
                        "field": "date",
                    },
                },
                {
                    "id": "signing_date",
                    "title": "Дата подписания",
                    "marker": "[ПОДПИСАНИЕ-{n}]",
                    "detect": {
                        "kind": "gliner_structure",
                        "label": "дата подписания",
                        "description": "Дата подписания договора",
                        "structure": "signing",
                        "field": "date",
                    },
                },
            ],
        }
    )


def _document() -> Document:
    text = "главный инженер и снова главный инженер"
    return Document("test.docx", "docx", [Segment(text, Anchor("docx", ("body", 0)), 0)])


def test_gliner_spans_are_valid_and_two_runs_identical() -> None:
    specs = _specs()
    detector = GlinerDetector(specs, model=FakeGliner())
    registry = EntityTypeRegistry.builtin().extend(item.spec for item in specs)
    agent = DetectAgent([detector], registry)

    first = agent.detect(_document()).entities
    second = agent.detect(_document()).entities

    assert first == second
    assert [item.text for item in first] == ["главный инженер", "главный инженер"]
    assert all(item.source is Source.NER for item in first)


def test_gliner_structure_queries_competing_roles_together() -> None:
    """Одинаковые значения получают роли из одного schema-запроса модели."""
    text = "Подписано 12.02.2026; отгрузка 12.02.2026"
    document = Document("test.docx", "docx", [Segment(text, Anchor("docx", ("body", 0)), 0)])
    model = FakeStructureGliner()
    specs = _structure_specs()
    registry = EntityTypeRegistry.builtin().extend(item.spec for item in specs)

    result = DetectAgent([GlinerDetector(specs, model=model)], registry).detect(document)

    assert model.calls == 1
    assert [(item.type, item.start, item.end) for item in result.entities] == [
        ("signing_date", text.index("12.02.2026"), text.index("12.02.2026") + 10),
        ("shipment_date", text.rindex("12.02.2026"), text.rindex("12.02.2026") + 10),
    ]


def test_gliner_logs_explicitly_when_custom_type_has_no_candidates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Пустой ответ модели виден оператору, а не похож на отсутствие такого типа."""
    detector = GlinerDetector(_specs(), model=EmptyGliner())
    registry = EntityTypeRegistry.builtin().extend(item.spec for item in _specs())

    with caplog.at_level(logging.INFO, logger="masker.detect.gliner"):
        result = DetectAgent([detector], registry).detect(_document())

    assert result.entities == []
    assert "job_title" in caplog.text
    assert "не дал ни одного кандидата в документе" in caplog.text


@pytest.mark.skipif(
    not _GLINER2_INSTALLED,
    reason="пропущено: проверка локальных весов требует установленный пакет gliner2",
)
def test_missing_weights_has_actionable_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setenv("MASKER_GLINER_PATH", str(missing))
    with pytest.raises(RuntimeError, match=r"gliner2"):
        GlinerDetector(_specs())


@pytest.mark.skipif(
    not _GLINER2_INSTALLED,
    reason="пропущено: проверка локальных весов требует установленный пакет gliner2",
)
def test_gliner_path_reads_from_project_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing-from-yaml"
    config = tmp_path / "masker.yaml"
    config.write_text(f"models:\n  gliner_path: {missing}\n", encoding="utf-8")
    monkeypatch.setenv("MASKER_CONFIG", str(config))
    monkeypatch.delenv("MASKER_GLINER_PATH", raising=False)

    with pytest.raises(RuntimeError, match=r"gliner2"):
        GlinerDetector(_specs())


def test_missing_gliner_package_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Р10: отсутствие GLiNER2 останавливает детекцию с понятным действием."""

    def missing_gliner2(package: str) -> str:
        if package == "gliner2":
            from importlib.metadata import PackageNotFoundError

            raise PackageNotFoundError(package)
        return "2.0.0"

    monkeypatch.setattr("masker.detect.gliner.version", missing_gliner2)

    with pytest.raises(RuntimeError, match=r"пакет 'gliner2' не установлен") as exc_info:
        verify_runtime_versions()

    assert "ожидается 2.0.0" in str(exc_info.value)


def test_missing_gliner_package_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Р10: отсутствие GLiNER2 останавливает детекцию с понятным действием."""

    def missing_gliner2(package: str) -> str:
        if package == "gliner2":
            from importlib.metadata import PackageNotFoundError

            raise PackageNotFoundError(package)
        return "2.0.0"

    monkeypatch.setattr("masker.detect.gliner.version", missing_gliner2)

    with pytest.raises(RuntimeError, match=r"пакет 'gliner2' не установлен") as exc_info:
        verify_runtime_versions()

    assert "ожидается 2.0.0" in str(exc_info.value)


def test_incompatible_model_type_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """gliner2>=2.0.0 на старых весах типа 'extractor' молча даёт пустой список.
    Детектор обязан упасть с RuntimeError, а не вернуть пустой результат.
    """
    import sys
    import types
    import warnings

    model_dir = tmp_path / "fake_model"
    model_dir.mkdir()
    monkeypatch.setenv("MASKER_GLINER_PATH", str(model_dir))

    def bad_from_pretrained(path: str) -> Any:
        warnings.warn(
            "You are using a model of type `extractor` to instantiate a model of type ``",
            UserWarning,
            stacklevel=2,
        )
        return object()

    class FakeAutoExtractor:
        from_pretrained = staticmethod(bad_from_pretrained)

    fake_gliner2 = types.ModuleType("gliner2")
    fake_gliner2.AutoExtractor = FakeAutoExtractor  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gliner2", fake_gliner2)

    fake_torch = types.ModuleType("torch")
    fake_torch.set_num_threads = lambda n: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    supported_versions = {"gliner2": "2.0.0", "transformers": "4.57.6", "torch": "2.14.0+cpu"}
    monkeypatch.setattr("masker.detect.gliner.version", supported_versions.__getitem__)

    with pytest.raises(RuntimeError, match="несовместима"):
        GlinerDetector(_specs())


def test_incompatible_runtime_fails_instead_of_returning_empty_predictions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Р10: несовместимость зависимостей не маскируется пустым списком."""
    versions = {"gliner2": "2.0.0", "transformers": "5.16.1", "torch": "2.14.0+cpu"}
    monkeypatch.setattr("masker.detect.gliner.version", versions.__getitem__)

    with pytest.raises(RuntimeError, match="несовместим") as exc_info:
        verify_runtime_versions()

    assert "transformers=5.16.1" in str(exc_info.value)
