"""GLiNER2 executor пользовательских семантических типов."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from masker.detect.normalize import normalize_value
from masker.model import Document, Entity, Source
from masker.typeconfig import CustomTypeSpec

DEFAULT_MODEL_PATH = Path("models/gliner")


class GlinerDetector:
    """Запускает локальную GLiNER2 только для переданных custom-спеков."""

    name = "gliner"
    source = Source.NER
    priority = 50

    def __init__(self, specs: Sequence[CustomTypeSpec], model: Any | None = None) -> None:
        self._specs = tuple(item for item in specs if item.kind.startswith("gliner_"))
        self.types = frozenset(item.spec.id for item in self._specs)
        if model is not None:
            self._model = model
            return

        model_path = Path(os.environ.get("MASKER_GLINER_PATH", DEFAULT_MODEL_PATH))
        if not model_path.is_dir():
            raise RuntimeError(
                f"Локальные веса GLiNER2 не найдены: {model_path}. "
                "Запустите `.venv/bin/python scripts/warm_gliner.py`."
            )
        import torch
        from gliner2 import AutoExtractor

        torch.set_num_threads(1)
        self._model = AutoExtractor.from_pretrained(str(model_path))
        underlying = getattr(self._model, "model", self._model)
        if hasattr(underlying, "eval"):
            underlying.eval()

    def detect(self, document: Document) -> list[Entity]:
        entities: list[Entity] = []
        for segment in sorted(document.segments, key=lambda item: item.order):
            for custom in sorted(self._specs, key=lambda item: item.spec.id):
                raw = self._extract(segment.text, custom)
                for span in self._spans(raw, segment.text, custom):
                    text = segment.text[span[0] : span[1]]
                    entities.append(
                        Entity(
                            type=custom.spec.id,
                            text=text,
                            segment_order=segment.order,
                            start=span[0],
                            end=span[1],
                            source=Source.NER,
                            confidence=span[2],
                            normalized=normalize_value(custom.spec.id, text),
                        )
                    )
        return sorted(
            entities, key=lambda item: (item.segment_order, item.start, item.end, item.type)
        )

    def _extract(self, text: str, custom: CustomTypeSpec) -> Any:
        if custom.kind == "gliner_label":
            return self._model.extract_entities(
                text,
                {custom.label: custom.description},
                threshold=custom.threshold,
                include_confidence=True,
                include_spans=True,
            )
        schema = (
            self._model.create_schema()
            .structure(custom.structure)
            .field(
                custom.field,
                dtype="str",
                description=custom.description,
                threshold=custom.threshold,
            )
        )
        return self._model.extract(text, schema, include_confidence=True, include_spans=True)

    @staticmethod
    def _spans(result: Any, text: str, custom: CustomTypeSpec) -> list[tuple[int, int, float]]:
        values: Any
        if custom.kind == "gliner_label":
            values = result.get("entities", {}).get(custom.label, [])
        else:
            records = result.get(custom.structure, []) if isinstance(result, Mapping) else []
            values = [record.get(custom.field) for record in records if isinstance(record, Mapping)]
        flat = list(_flatten(values))
        found: list[tuple[int, int, float]] = []
        cursors: dict[str, int] = {}
        for value in flat:
            if isinstance(value, Mapping):
                value_text = str(value.get("text", ""))
                start = value.get("start")
                end = value.get("end")
                confidence = float(value.get("confidence", custom.threshold))
            else:
                value_text = str(value)
                start = end = None
                confidence = custom.threshold
            if not value_text:
                continue
            if not isinstance(start, int) or not isinstance(end, int):
                start = text.find(value_text, cursors.get(value_text, 0))
                if start < 0:
                    continue
                end = start + len(value_text)
            if 0 <= start < end <= len(text) and text[start:end] == value_text:
                found.append((start, end, confidence))
                cursors[value_text] = end
        return sorted(set(found))


def _flatten(values: Any) -> Iterable[Any]:
    if isinstance(values, list):
        for value in values:
            if isinstance(value, list):
                yield from value
            elif value is not None:
                yield value
    elif values is not None:
        yield values
