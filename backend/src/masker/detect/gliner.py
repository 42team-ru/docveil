"""GLiNER2 executor пользовательских семантических типов."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from masker.config import project_section
from masker.detect.normalize import normalize_value
from masker.model import Document, Entity, Segment, Source
from masker.typeconfig import CustomTypeSpec

DEFAULT_MODEL_PATH = Path("models/gliner")
logger = logging.getLogger(__name__)
_NUMERIC_DATE = re.compile(r"\d{2}[./-]\d{2}[./-]\d{4}\Z")
SUPPORTED_RUNTIME_VERSIONS = {
    "gliner2": "2.0.0",
    "transformers": "4.57.6",
    "torch": "2.14.0+cpu",
}


def verify_runtime_versions() -> None:
    """Не запускать GLiNER на несовместимом наборе пакетов молча.

    GLiNER2 способен загрузиться с несовместимым ``transformers`` и вернуть
    пустой результат без исключения. Р10 фиксирует проверенный набор, чтобы
    такая деградация стала явной ошибкой до начала детекции.
    """
    for package, expected in SUPPORTED_RUNTIME_VERSIONS.items():
        try:
            actual = version(package)
        except PackageNotFoundError as error:
            raise RuntimeError(
                f"GLiNER2 недоступен: пакет {package!r} не установлен; ожидается {expected}."
            ) from error
        if actual != expected:
            raise RuntimeError(
                f"GLiNER2 несовместим: {package}={actual}, ожидается строго {expected}. "
                "Детекция остановлена, чтобы не выдать молчаливый пустой результат."
            )


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

        verify_runtime_versions()

        configured_path = project_section("models").get("gliner_path", str(DEFAULT_MODEL_PATH))
        if not isinstance(configured_path, str):
            raise ValueError("models.gliner_path в YAML-конфиге должен быть строкой")
        model_path = Path(os.environ.get("MASKER_GLINER_PATH", configured_path))
        if not model_path.is_dir():
            raise RuntimeError(
                f"Локальные веса GLiNER2 не найдены: {model_path}. "
                "Запустите `.venv/bin/python scripts/warm_gliner.py`."
            )
        import warnings

        import torch
        from gliner2 import AutoExtractor

        torch.set_num_threads(1)
        # Перехватываем предупреждение transformers об несовместимом типе модели
        # ("You are using a model of type `extractor` to instantiate a model of
        # type ``"): в gliner2>=2.0.0 старые веса молча дают пустой результат.
        # Лучше упасть явно, чем работать и ничего не находить.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "error",
                message="You are using a model of type",
                category=UserWarning,
            )
            try:
                self._model = AutoExtractor.from_pretrained(str(model_path))
            except Exception as exc:
                if "You are using a model of type" in str(exc):
                    raise RuntimeError(
                        f"Модель GLiNER2 в {model_path} несовместима с установленной "
                        f"версией gliner2: {exc}\n"
                        "Обновите веса: `.venv/bin/python scripts/warm_gliner.py`, "
                        "или понизьте gliner2 до <2.0.0."
                    ) from exc
                raise
        underlying = getattr(self._model, "model", self._model)
        if hasattr(underlying, "eval"):
            underlying.eval()

    def detect(self, document: Document) -> list[Entity]:
        """Найти пользовательские сущности, сохраняя конкуренцию ролей.

        ``gliner_structure`` запускаются одним schema-запросом на сегмент.
        У полей такого schema общая задача извлечения, поэтому модель видит
        альтернативные роли одновременно (например, дату подписания и дату
        отгрузки одинакового формата). Отдельные запросы лишают её этого
        противопоставления и могут отдать одну позицию обеим ролям.
        """
        entities: list[Entity] = []
        structure_specs = tuple(item for item in self._specs if item.kind == "gliner_structure")
        label_specs = tuple(item for item in self._specs if item.kind == "gliner_label")
        has_candidates = {item.spec.id: False for item in self._specs}
        for segment in sorted(document.segments, key=lambda item: item.order):
            for custom in sorted(label_specs, key=lambda item: item.spec.id):
                raw = self._extract(segment.text, custom)
                spans = self._spans(raw, segment.text, custom)
                has_candidates[custom.spec.id] |= bool(spans)
                entities.extend(self._entities_for_spans(custom, segment, spans))
            if structure_specs:
                structure_results = self._extract_structures(segment.text, structure_specs)
                for custom in structure_specs:
                    spans = self._structure_spans(
                        structure_results, segment.text, custom.spec.id, custom
                    )
                    has_candidates[custom.spec.id] |= bool(spans)
                    entities.extend(self._entities_for_spans(custom, segment, spans))
        for type_id, found in sorted(has_candidates.items()):
            if not found:
                logger.warning(
                    "GLiNER: пользовательский тип %r не дал ни одного кандидата в документе.",
                    type_id,
                )
        return sorted(
            entities, key=lambda item: (item.segment_order, item.start, item.end, item.type)
        )

    @staticmethod
    def _entities_for_spans(
        custom: CustomTypeSpec, segment: Segment, spans: Sequence[tuple[int, int, float]]
    ) -> list[Entity]:
        """Превратить спаны одного пользовательского типа в сущности."""
        return [
            Entity(
                type=custom.spec.id,
                text=segment.text[start:end],
                segment_order=segment.order,
                start=start,
                end=end,
                source=Source.NER,
                confidence=confidence,
                normalized=normalize_value(custom.spec.id, segment.text[start:end]),
            )
            for start, end, confidence in spans
        ]

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

    def _extract_structures(self, text: str, specs: Sequence[CustomTypeSpec]) -> Any:
        """Одним запросом извлечь все структурные роли сегмента.

        В schema имя поля — id типа, а не ``CustomTypeSpec.field``: последнее
        может совпасть у независимых пользовательских конфигураций, тогда как
        id уже валидирован уникальным. Описание поля остаётся исходным и несёт
        для модели весь смысл роли.
        """
        schema = self._model.create_schema().structure("custom_entities")
        for custom in sorted(specs, key=lambda item: item.spec.id):
            schema = schema.field(
                custom.spec.id,
                dtype="str",
                description=custom.description,
                threshold=custom.threshold,
            )
        return self._model.extract(text, schema, include_confidence=True, include_spans=True)

    # Не `@staticmethod` с обращением к глобальному имени класса: preview
    # подменяет `masker.detect.gliner.GlinerDetector` функцией-фабрикой,
    # чтобы подставить модель, и тогда `GlinerDetector._spans_from_values`
    # уходит в функцию, а не в класс (падало 11.09.2026 на
    # `test_preview_dispatches_gliner_kind_via_injected_model`). `cls`
    # связывается с настоящим классом и переживает такую подмену.
    @classmethod
    def _spans(cls, result: Any, text: str, custom: CustomTypeSpec) -> list[tuple[int, int, float]]:
        values: Any
        if custom.kind == "gliner_label":
            values = result.get("entities", {}).get(custom.label, [])
        else:
            records = result.get(custom.structure, []) if isinstance(result, Mapping) else []
            values = [record.get(custom.field) for record in records if isinstance(record, Mapping)]
        return cls._spans_from_values(values, text, custom)

    @staticmethod
    def _spans_from_values(
        values: Any, text: str, custom: CustomTypeSpec
    ) -> list[tuple[int, int, float]]:
        """Прочитать спаны из значений одного поля GLiNER-ответа."""
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
            if _expects_calendar_date(custom) and _NUMERIC_DATE.fullmatch(value_text) is None:
                # GLiNER может принять номер договора «10/2026» за дату
                # поставки. Это не спор ролей: кандидат не удовлетворяет
                # явно заявленному формату значения, поэтому его нельзя
                # передавать в общее разрешение пересечений как «ту же
                # сущность». Проверка привязана к семантике custom-спека,
                # а не к его id: одинаково действует для любого
                # пользовательского типа, который описан как дата.
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

    @classmethod
    def _structure_spans(
        cls,
        result: Any,
        text: str,
        field: str,
        custom: CustomTypeSpec,
    ) -> list[tuple[int, int, float]]:
        """Вынуть поле общего структурного schema через общий парсер спанов.

        Тоже `cls`, а не имя класса: причина та же, что у `_spans` выше.
        """
        records = result.get("custom_entities", []) if isinstance(result, Mapping) else []
        values = [record.get(field) for record in records if isinstance(record, Mapping)]
        return cls._spans_from_values(values, text, custom)


def _flatten(values: Any) -> Iterable[Any]:
    if isinstance(values, list):
        for value in values:
            if isinstance(value, list):
                yield from value
            elif value is not None:
                yield value
    elif values is not None:
        yield values


def _expects_calendar_date(custom: CustomTypeSpec) -> bool:
    """Запрашивает ли пользователь именно календарную дату, а не произвольный текст."""
    description = " ".join(
        (custom.spec.id, custom.spec.title, custom.label, custom.description)
    ).casefold()
    return "дата" in description or "date" in description
