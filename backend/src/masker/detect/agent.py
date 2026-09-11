"""Оркестрация подключаемых детекторов PII."""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

from masker.detect.base import EntityDetector
from masker.detect.confidence import classify_level
from masker.detect.legal_references import is_public_legal_reference_type
from masker.detect.normalize import normalize_value
from masker.detect.normalize_layout import normalize_for_detection
from masker.detect.orgforms import (
    has_organization_evidence,
    is_organization_form_only,
    is_role_stopword,
    shrink_span,
)
from masker.detect.person_frequency import drop_frequent_common_noun_persons
from masker.detect.requisite_blocks import find_requisite_block_candidates
from masker.detect.requisites import drop_incomplete_requisites
from masker.detect.result import DetectionResult, build_pii_chunks
from masker.detect.sweep import sweep
from masker.entity_types import EntityTypeRegistry
from masker.llm import LLMProvider
from masker.model import Document, Entity, EntityType, Segment, Source

if TYPE_CHECKING:
    from masker.detect.verifier import VerifierReport

MIN_FRAGMENT_LEN = 2
logger = logging.getLogger(__name__)


def _overlaps(first: Entity, second: Entity) -> bool:
    return (
        first.segment_order == second.segment_order
        and first.start < second.end
        and second.start < first.end
    )


def _one_span_contains_other(first: Entity, second: Entity) -> bool:
    """Совпадают ли спаны либо один целиком содержит другой в сегменте."""
    return (
        first.segment_order == second.segment_order
        and first.start <= second.start
        and second.end <= first.end
    ) or (
        second.segment_order == first.segment_order
        and second.start <= first.start
        and first.end <= second.end
    )


def _is_money_contract_amount_pair(first: Entity, second: Entity) -> bool:
    """Один и тот же спан может быть и общей суммой, и ценой договора.

    Это не конфликт конкурирующих детекторов: ``contract_amount`` — более
    конкретная классификация ``money``. Обе записи нужны, чтобы пользователь
    мог выбрать либо все суммы, либо только цену договора. Рендер получает
    только одну замену: ``PlanAgent`` предпочитает конкретный тип, когда
    выбраны оба.
    """
    return (
        {first.type, second.type} == {EntityType.MONEY, EntityType.CONTRACT_AMOUNT}
        and first.segment_order == second.segment_order
        and first.start == second.start
        and first.end == second.end
    )


class DetectAgent:
    """Объединяет детекторы, проверяет их контракт и строит общие чанки."""

    def __init__(
        self,
        detectors: Iterable[EntityDetector] | None = None,
        registry: EntityTypeRegistry | None = None,
        llm: LLMProvider | None = None,
    ) -> None:
        if detectors is None:
            from masker.detect import default_detectors

            detectors = default_detectors()
        self._detectors = list(detectors)
        self._registry = registry if registry is not None else EntityTypeRegistry.builtin()
        # Р7 (TASKS.md): верификатор на recall — опциональный последний шаг,
        # включается, только если вызывающий явно передал `LLMProvider`.
        # `None` по умолчанию — офлайн-ворота (`make gate`, весь остальной
        # корпус тестов) продолжают работать без единого сетевого вызова, как
        # и раньше; см. `masker.detect.verifier.verify_recall`.
        self._llm = llm

    @property
    def detectors(self) -> tuple[EntityDetector, ...]:
        """Подключённые детекторы в порядке их запуска."""
        return tuple(self._detectors)

    def _validate(
        self, detector: EntityDetector, document: Document, entities: list[Entity]
    ) -> None:
        segments = {segment.order: segment for segment in document.segments}
        for entity in entities:
            segment = segments.get(entity.segment_order)
            if segment is None:
                raise ValueError(f"Detector {detector.name!r} returned an unknown segment_order")
            if entity.type not in self._registry:
                known = ", ".join(self._registry.ids())
                raise ValueError(
                    f"Detector {detector.name!r} returned unknown entity type {entity.type!r}."
                    f" Known: {known}"
                )
            if not isinstance(entity.source, Source):
                raise ValueError(f"Detector {detector.name!r} returned an invalid entity source")
            if not 0 <= entity.start < entity.end <= len(segment.text):
                raise ValueError(f"Detector {detector.name!r} returned an invalid entity span")
            if entity.text != segment.text[entity.start : entity.end]:
                raise ValueError(
                    f"Detector {detector.name!r} returned entity text outside its span"
                )

    def _resolve_overlaps(self, found: list[tuple[EntityDetector, Entity]]) -> list[Entity]:
        ordered = sorted(
            found,
            key=lambda item: (
                -item[0].priority,
                -item[1].confidence,
                -(item[1].end - item[1].start),
                item[1].type,
                item[1].segment_order,
                item[1].start,
                item[1].end,
                item[0].name,
            ),
        )
        accepted: list[Entity] = []
        for _detector, entity in ordered:
            overlaps = [existing for existing in accepted if _overlaps(entity, existing)]
            if not overlaps:
                accepted.append(entity)
                continue
            if all(_is_money_contract_amount_pair(entity, existing) for existing in overlaps):
                accepted.append(entity)
                continue
            if self._replaces_noncritical_builtin(entity, overlaps):
                accepted = [existing for existing in accepted if existing not in overlaps]
                accepted.append(entity)
                continue
            if entity.source is Source.RULE:
                continue
            accepted.extend(DetectAgent._carve(entity, overlaps))
        return sorted(
            accepted,
            key=lambda item: (item.segment_order, item.start, item.end, item.type),
        )

    def _replaces_noncritical_builtin(self, candidate: Entity, overlaps: list[Entity]) -> bool:
        """Может ли пользовательская роль заменить общий встроенный тип.

        11.09.2026: пользовательский тип, найденный в том же значении,
        информативнее общего встроенного типа: ``shipment_date`` сохраняет
        роль, которую ``date`` теряет. Это общее правило для любого
        пользовательского типа, а не исключение для дат. Оно ограничено
        совпадающими или вложенными спанами: при частичном пересечении
        остаётся обычное безопасное вычитание. Встроенный критичный тип
        никогда не заменяется — его маска важнее уточнения роли.
        """
        if self._registry.is_builtin(str(candidate.type)):
            return False
        if any(
            not self._registry.is_builtin(str(existing.type))
            or self._registry.is_critical(str(existing.type))
            for existing in overlaps
        ):
            return False
        return all(_one_span_contains_other(candidate, existing) for existing in overlaps)

    def _warn_displaced_custom_types(
        self,
        found: list[tuple[EntityDetector, Entity]],
        accepted: list[Entity],
    ) -> None:
        """Явно сообщить, если overlap-resolution вытеснил все кандидаты типа."""
        custom_candidates: dict[str, set[tuple[int, int, int]]] = {}
        for _detector, entity in found:
            if not self._registry.is_builtin(str(entity.type)):
                custom_candidates.setdefault(str(entity.type), set()).add(
                    (entity.segment_order, entity.start, entity.end)
                )
        accepted_keys = {
            (str(entity.type), entity.segment_order, entity.start, entity.end)
            for entity in accepted
        }
        for type_id, candidates in sorted(custom_candidates.items()):
            if not any((type_id, *candidate) in accepted_keys for candidate in candidates):
                logger.warning(
                    "Пользовательский тип %r: %d кандидатов, но все вытеснены "
                    "разрешением пересечений; проверьте пересекающийся встроенный тип.",
                    type_id,
                    len(candidates),
                )

    @staticmethod
    def _carve(entity: Entity, existing: list[Entity]) -> list[Entity]:
        """Вычесть из модельного спана точные, уже принятые сущности правил."""
        intervals = sorted(
            (
                max(entity.start, other.start),
                min(entity.end, other.end),
            )
            for other in existing
            if other.segment_order == entity.segment_order
        )
        fragments: list[tuple[int, int]] = []
        cursor = entity.start
        for start, end in intervals:
            if cursor < start:
                fragments.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < entity.end:
            fragments.append((cursor, entity.end))

        carved: list[Entity] = []
        for start, end in fragments:
            local_start = start - entity.start
            local_end = end - entity.start
            bounds = shrink_span(entity.text, local_start, local_end)
            if bounds is None:
                continue
            local_start, local_end = bounds
            value_start = entity.start + local_start
            value_end = entity.start + local_end
            text = entity.text[local_start:local_end]
            if (
                value_end - value_start < MIN_FRAGMENT_LEN
                or not any(char.isalpha() for char in text)
                or is_organization_form_only(text)
                or is_role_stopword(text)
            ):
                continue
            if value_start != entity.start and not DetectAgent._has_fragment_evidence(
                entity.type, text
            ):
                continue
            carved.append(
                Entity(
                    type=entity.type,
                    text=text,
                    segment_order=entity.segment_order,
                    start=value_start,
                    end=value_end,
                    source=entity.source,
                    confidence=entity.confidence,
                    normalized=normalize_value(entity.type, text),
                )
            )
        return carved

    @staticmethod
    def _count_signals(entity: Entity, found: list[tuple[EntityDetector, Entity]]) -> int:
        """Сколько разных детекторов независимо нашли пересекающийся спан (Р8).

        Считается по «сырым» находкам (``found``), собранным ДО разрешения
        перекрытий — именно там ещё видно, что, например, оргформа-правило и
        локальная NER независимо указали на одно и то же имя. После
        ``_resolve_overlaps`` из двух перекрывшихся спанов остаётся один, и
        сам факт согласия исчез бы, если бы его не посчитали здесь.
        """
        names = {
            detector.name
            for detector, candidate in found
            if _overlaps(entity, candidate) and candidate.type == entity.type
        }
        return len(names)

    def _levelled(
        self, entities: list[Entity], found: list[tuple[EntityDetector, Entity]]
    ) -> list[Entity]:
        """Проставить уровень уверенности (Р8) каждой принятой сущности.

        Сквозной досмотр (``sweep``) не участвует в ``found`` — его находки
        не от отдельного детектора, а копия уже принятого значения в другом
        месте документа, поэтому им достаётся тот же классификатор с
        ``signal_count=1``: без второго независимого детектора и без
        критичности/контрольной суммы они не станут ``CONFIRMED`` только за
        счёт повторения текста.
        """
        return [
            dataclasses.replace(
                entity,
                level=classify_level(
                    entity,
                    signal_count=self._count_signals(entity, found),
                    registry=self._registry,
                ),
            )
            for entity in entities
        ]

    @staticmethod
    def _has_fragment_evidence(entity_type: str, text: str) -> bool:
        if entity_type == EntityType.ORG_NAME:
            return has_organization_evidence(text)
        if entity_type != EntityType.PERSON:
            return False
        tokens = [token.strip(".,;:()[]{}«»\"'“”„") for token in text.split()]
        return bool(tokens) and all(
            token
            and (token[0].isupper() or bool(re.fullmatch(r"[А-ЯЁ]\.?", token, flags=re.IGNORECASE)))
            for token in tokens
        )

    @staticmethod
    def _normalize_document(document: Document) -> tuple[Document, dict[int, list[int]]]:
        """Построить документ с «чистым» текстом для детекторов (Р1).

        Каждый сегмент нормализуется независимо (`normalize_for_detection`),
        якорь и порядок сохраняются — детекторы адресуются к тем же
        сегментам, что и раньше, только текст в них уже без вёрстки:
        схлопнутых пробельных вариантов, переноса строки посреди номера,
        разрядки меток, гомоглифов. Карта смещений на сегмент нужна
        `_remap_entities`, чтобы вернуть найденные спаны в координаты
        исходного документа — контракт `model.py` наружу не меняется.
        """
        segments: list[Segment] = []
        maps: dict[int, list[int]] = {}
        for segment in document.segments:
            normalized_text, mapping = normalize_for_detection(segment.text)
            maps[segment.order] = mapping
            segments.append(
                Segment(text=normalized_text, anchor=segment.anchor, order=segment.order)
            )
        normalized = Document(
            path=document.path, fmt=document.fmt, segments=segments, meta=document.meta
        )
        return normalized, maps

    @staticmethod
    def _remap_entities(
        entities: list[Entity],
        maps: dict[int, list[int]],
        original_segments: dict[int, Segment],
    ) -> list[Entity]:
        """Отобразить спаны детектора с нормализованного текста на исходный.

        Детектор искал по `normalize_for_detection(segment.text)` и вернул
        смещения в ЭТОМ тексте — они не совпадают по длине с исходным
        (два пробела схлопнуты в один, перенос строки внутри номера
        удалён), поэтому пересчёт через простую разницу длин здесь неверен:
        конец спана обязан идти через ту же карту, что и начало
        (``mapping[end]``), а не через ``mapping[start] + (end - start)``.

        ``entity.normalized`` не пересчитывается: детектор уже посчитал его
        от «чистого» значения, которое сам нашёл (``normalize_value`` в
        ``rules.py``/``morph.py`` и т.п.), — это и есть канонический ключ.
        Пересчёт от восстановленного исходного текста был бы ХУЖЕ: в нём
        может остаться необработанный мягкий перенос или неразрывный
        пробел (см. кейсы Р1), которые `normalize_value` не обязан знать,
        и один и тот же реквизит с вёрсткой и без неё получил бы разные
        ключи согласованности.
        """
        remapped: list[Entity] = []
        for entity in entities:
            mapping = maps[entity.segment_order]
            original_text = original_segments[entity.segment_order].text
            start = mapping[entity.start]
            end = mapping[entity.end]
            if entity.type is EntityType.PERSON and re.search(r"[А-ЯЁ]\.[А-ЯЁ]$", entity.text):
                cursor = end
                while cursor < len(original_text) and original_text[cursor] == " ":
                    cursor += 1
                if cursor < len(original_text) and original_text[cursor] == ".":
                    # На `dagestanschool-kais-808.pdf` 11.09.2026 Natasha
                    # отдавала «Магомедов Н.Г» без завершающей точки, хотя
                    # карта уже привела к ней через разрядочные пробелы.
                    # Точка завершает инициал, а не предложение, поэтому
                    # расширяем только эту строго распознанную форму.
                    end = cursor + 1
            remapped.append(
                Entity(
                    type=entity.type,
                    text=original_text[start:end],
                    segment_order=entity.segment_order,
                    start=start,
                    end=end,
                    source=entity.source,
                    confidence=entity.confidence,
                    normalized=entity.normalized,
                )
            )
        return remapped

    def detect(self, document: Document) -> DetectionResult:
        """Запустить детекторы и вернуть проверенный, объединённый результат.

        Все детекторы получают один и тот же нормализованный документ
        (Р1) — так вёрсточные варианты (NBSP, перенос строки в номере,
        разрядка «И Н Н», гомоглифы) чинятся один раз для всех детекторов
        разом, а не в каждом из них по отдельности. Найденные спаны сразу
        отображаются назад на координаты исходного сегмента, поэтому
        дальше по конвейеру (``_validate``, ``_resolve_overlaps``, ``sweep``)
        ничего не знает о нормализации — она полностью прозрачна снаружи.

        Сквозной досмотр (``sweep``, план T2.2.2, шаг 8, Д13) — последний
        проход, после разрешения перекрытий: расширяет уже принятые
        значения по всему документу, а не ищет новые типы сущностей.
        """
        normalized_document, maps = self._normalize_document(document)
        original_segments = {segment.order: segment for segment in document.segments}
        found: list[tuple[EntityDetector, Entity]] = []
        for detector in self._detectors:
            entities = detector.detect(normalized_document)
            # Контракт детектора проверяется на том же тексте, по которому
            # он искал (нормализованном) — иначе сломанный плагин, который
            # сам себе противоречит (текст не совпадает со своим спаном),
            # прошёл бы незамеченным: `_remap_entities` берёт текст среза
            # ИСХОДНОГО сегмента по координатам, а не то, что вернул
            # детектор, и молча «чинит» результат несогласованного плагина.
            self._validate(detector, normalized_document, entities)
            entities = self._remap_entities(entities, maps, original_segments)
            self._validate(detector, document, entities)
            found.extend((detector, entity) for entity in entities)
        # 11.09.2026: `44-ФЗ` из преамбулы контракта был формально найден
        # `RuleDetector`, а затем ошибочно попадал в план масок. Реквизит
        # нормативного акта публичен; фильтруем его после всех детекторов,
        # не меняя запрещённый низкоуровневый шаблон `rules.py`.
        found = [
            (detector, entity)
            for detector, entity in found
            if not is_public_legal_reference_type(entity.type)
        ]
        entities = self._resolve_overlaps(found)
        self._warn_displaced_custom_types(found, entities)
        extra_sweep_types = frozenset(
            entity_type
            for detector in self._detectors
            for entity_type in getattr(detector, "sweep_types", frozenset())
        )
        entities = sorted(
            [*entities, *sweep(document, entities, extra_sweep_types)],
            key=lambda item: (item.segment_order, item.start, item.end, item.type),
        )
        # Блоки реквизитов/подписей как источник кандидатов (Р6, план
        # TASKS.md): тот же класс шага, что и `sweep` выше, — не
        # `EntityDetector` (протокол не видит уже найденные сущности, а
        # построение блока в них нуждается, см. докстринг модуля), а
        # отдельный проход после разрешения перекрытий, ДО простановки
        # уровня уверенности, чтобы новым кандидатам тоже достался обычный
        # путь `classify_level` (Р8), а не отдельная жёстко прибитая метка.
        entities = sorted(
            [*entities, *find_requisite_block_candidates(document, entities)],
            key=lambda item: (item.segment_order, item.start, item.end, item.type),
        )
        verifier_report: VerifierReport | None = None
        if self._llm is not None:
            # Р7: верификатор смотрит только на то, что осталось непокрытым
            # ПОСЛЕ Р4/Р5/Р6 (морфология, оргформы, блоки реквизитов) — их
            # находки уже в `entities` к этому моменту, поэтому кандидатные
            # окна строятся от актуального остатка, а не от «сырых» правил.
            from masker.detect.verifier import summarize_verdicts, verify_recall

            verifier_result = verify_recall(document, entities, self._llm)
            verifier_report = summarize_verdicts(document, verifier_result)
            entities = sorted(
                [*entities, *verifier_result.entities],
                key=lambda item: (item.segment_order, item.start, item.end, item.type),
            )
        # Р13: формальная длина — свойство реквизита, а не только регулярки.
        # Этот общий барьер покрывает любой текущий или будущий детектор до
        # профилирования и планирования масок.
        entities = drop_incomplete_requisites(entities)
        # Р15: повторяющаяся роль стороны может прийти и от NER, и от
        # структурного блока реквизитов. Фильтруем объединённый результат,
        # чтобы один источник не мог обойти общий частотный барьер.
        entities = drop_frequent_common_noun_persons(entities)
        # Уровень уверенности (Р8) — последний шаг, после того как состав
        # принятых сущностей окончательно определён: `_count_signals` читает
        # ещё не разрешённые `found`, а `sweep`-находки уже сами по себе
        # заведомо однодетекторные (см. докстринг `_levelled`).
        entities = self._levelled(entities, found)
        chunks = build_pii_chunks(document.segments, entities)
        return DetectionResult(entities=entities, chunks=chunks, verifier=verifier_report)
