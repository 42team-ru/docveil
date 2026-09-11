"""Контракт GLiNER2-адаптера без загрузки тяжёлой модели."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from masker.detect.agent import DetectAgent
from masker.detect.gliner import GlinerDetector
from masker.entity_types import EntityTypeRegistry
from masker.model import Anchor, Document, Segment, Source
from masker.typeconfig import load_type_config


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


def test_missing_weights_has_actionable_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setenv("MASKER_GLINER_PATH", str(missing))
    with pytest.raises(RuntimeError, match=r"warm_gliner\.py") as exc_info:
        GlinerDetector(_specs())
    assert str(missing) in str(exc_info.value)


def test_gliner_path_reads_from_project_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing-from-yaml"
    config = tmp_path / "masker.yaml"
    config.write_text(f"models:\n  gliner_path: {missing}\n", encoding="utf-8")
    monkeypatch.setenv("MASKER_CONFIG", str(config))
    monkeypatch.delenv("MASKER_GLINER_PATH", raising=False)

    with pytest.raises(RuntimeError, match=r"warm_gliner\.py") as exc_info:
        GlinerDetector(_specs())

    assert str(missing) in str(exc_info.value)


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

    with pytest.raises(RuntimeError, match="несовместима"):
        GlinerDetector(_specs())
