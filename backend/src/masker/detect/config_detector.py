"""Детектор пользовательских типов, пришедших в теле запроса.

Адаптер `CustomTypeSpec` (`masker.typeconfig`) к общему контракту
`EntityDetector` — исполняет executor'ы `literals`, `regex` и
`regex_context` (`docs/plans/T1.13-design-notes.md`, решение 2.4).
Матчер уже провалидирован и скомпилирован в `load_type_config`; здесь
только применение к документу и бюджет времени на пользовательские
регулярки. Семантические executor'ы (`gliner_label`, `gliner_structure`,
`regex_llm_filter`) — отдельные детекторы, здесь их нет.
"""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter

from masker.detect.normalize import normalize_value
from masker.model import Document, Entity, Source
from masker.typeconfig import CustomTypeError, CustomTypeSpec

#: Суммарный бюджет времени пользовательских регулярок на один документ.
#: Превышение — не «поймали взрывной паттерн на лету» (это не умеет ``re``
#: стандартной библиотеки), а «набралось много умеренно медленных
#: паттернов»; настоящая защита от катастрофического бэктрекинга — AST-
#: валидатор в ``typeconfig.py``.
CUSTOM_REGEX_BUDGET_S = 2.0

#: Окно контекста вокруг совпадения регулярки, в символах в каждую сторону
#: (executor ``regex_context``, поле ``detect.context`` спецификации).
CONTEXT_WINDOW_CHARS = 80

#: confidence для литералов — пользователь буквально указал строку.
LITERAL_CONFIDENCE = 1.0
#: confidence для регулярки — ниже, чем у правил с контрольной суммой.
REGEX_CONFIDENCE = 0.9


class ConfigDetector:
    """Ищет сущности пользовательских типов: списком литералов или регуляркой."""

    name = "config"
    source = Source.USER
    priority = 95  # ниже правил проекта (100), выше NER (50)

    def __init__(self, specs: Sequence[CustomTypeSpec]) -> None:
        self._specs = list(specs)
        self.types: frozenset[str] = frozenset(custom.spec.id for custom in self._specs)
        self.sweep_types: frozenset[str] = frozenset(
            custom.spec.id for custom in self._specs if custom.kind == "literals"
        )

    def detect(self, document: Document) -> list[Entity]:
        """Найти сущности всех объявленных пользовательских типов.

        Бюджет ``CUSTOM_REGEX_BUDGET_S`` считается суммарно по всем типам с
        ``kind == "regex"`` в документе; литералы в бюджет не входят — в их
        паттерне нет ни одного квантификатора, взорваться нечему.
        """
        entities: list[Entity] = []
        regex_elapsed = 0.0
        for custom in self._specs:
            if custom.kind == "literals":
                entities.extend(self._detect_literals(custom, document))
                continue
            if custom.kind != "regex":
                continue
            started = perf_counter()
            entities.extend(self._detect_regex(custom, document))
            regex_elapsed += perf_counter() - started
            if regex_elapsed > CUSTOM_REGEX_BUDGET_S:
                raise CustomTypeError(
                    f"Тип {custom.spec.id!r}: пользовательские регулярки превысили "
                    f"бюджет времени {CUSTOM_REGEX_BUDGET_S} с на документ"
                )
        return sorted(
            entities,
            key=lambda entity: (entity.segment_order, entity.start, entity.end, entity.type),
        )

    def _detect_literals(self, custom: CustomTypeSpec, document: Document) -> list[Entity]:
        found: list[Entity] = []
        assert custom.pattern is not None
        for segment in document.segments:
            for match in custom.pattern.finditer(segment.text):
                text = match.group()
                found.append(
                    Entity(
                        type=custom.spec.id,
                        text=text,
                        segment_order=segment.order,
                        start=match.start(),
                        end=match.end(),
                        source=Source.USER,
                        confidence=LITERAL_CONFIDENCE,
                        normalized=normalize_value(custom.spec.id, text),
                    )
                )
        return found

    def _detect_regex(self, custom: CustomTypeSpec, document: Document) -> list[Entity]:
        found: list[Entity] = []
        assert custom.pattern is not None
        for segment in document.segments:
            for match in custom.pattern.finditer(segment.text):
                if custom.context and not _context_present(
                    segment.text, match.start(), match.end(), custom.context
                ):
                    continue
                text = match.group()
                found.append(
                    Entity(
                        type=custom.spec.id,
                        text=text,
                        segment_order=segment.order,
                        start=match.start(),
                        end=match.end(),
                        source=Source.USER,
                        confidence=REGEX_CONFIDENCE,
                        normalized=normalize_value(custom.spec.id, text),
                    )
                )
        return found


def _context_present(text: str, start: int, end: int, keywords: tuple[str, ...]) -> bool:
    """Хотя бы одно контекстное слово встречается в окне ±80 символов вокруг совпадения."""
    window_start = max(0, start - CONTEXT_WINDOW_CHARS)
    window_end = min(len(text), end + CONTEXT_WINDOW_CHARS)
    window = text[window_start:window_end].casefold()
    return any(keyword.casefold() in window for keyword in keywords)
