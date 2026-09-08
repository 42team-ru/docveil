"""Уровень уверенности (Р8), который `DetectAgent.detect()` проставляет на
итоговые сущности — интеграционная часть `masker.detect.confidence`:

1. Единственный детектор на открытый класс (org_name/person) без
   контрольной суммы — `POSSIBLE`.
2. Два разных детектора нашли пересекающиеся спаны одного типа — `CONFIRMED`
   без контрольной суммы (Р8, требование «≥2 независимых сигнала»).
3. Критичный тип остаётся `CONFIRMED`, даже если детектор его нашёл с
   низкой уверенностью и без второго сигнала.
4. `sweep`-находки (копия уже принятого значения в другом сегменте) не
   получают `CONFIRMED` просто за счёт повторения текста.
"""

from __future__ import annotations

from dataclasses import dataclass

from masker.detect.agent import DetectAgent
from masker.model import Anchor, ConfidenceLevel, Document, Entity, EntityType, Segment, Source


@dataclass
class StubDetector:
    name: str
    source: Source
    priority: int
    entities: list[Entity]

    def detect(self, document: Document) -> list[Entity]:
        return self.entities


def _document(text: str) -> Document:
    return Document(
        path="test.docx",
        fmt="docx",
        segments=[Segment(text, Anchor("docx", ("body", 0)), 0)],
    )


def test_single_detector_open_class_capitalized_name_is_possible() -> None:
    text = "Поставщик: Смирнов Пётр Александрович."
    document = _document(text)
    start = text.index("Смирнов")
    end = start + len("Смирнов Пётр Александрович")
    ner = StubDetector(
        "natasha",
        Source.NER,
        50,
        [Entity(EntityType.PERSON, text[start:end], 0, start, end, Source.NER, confidence=0.6)],
    )

    result = DetectAgent(detectors=[ner]).detect(document)

    (person,) = result.entities
    assert person.level == ConfidenceLevel.POSSIBLE


def test_two_detectors_agreeing_on_overlapping_span_confirm_without_checksum() -> None:
    text = 'ООО "Ромашка", далее Поставщик'
    document = _document(text)
    start = text.index("Ромашка")
    end = start + len("Ромашка")
    rule = StubDetector(
        "org_form",
        Source.RULE,
        60,
        [Entity(EntityType.ORG_NAME, text[start:end], 0, start, end, Source.RULE, confidence=0.9)],
    )
    ner = StubDetector(
        "natasha",
        Source.NER,
        50,
        [Entity(EntityType.ORG_NAME, text[start:end], 0, start, end, Source.NER, confidence=0.7)],
    )

    result = DetectAgent(detectors=[rule, ner]).detect(document)

    (org,) = result.entities
    assert org.level == ConfidenceLevel.CONFIRMED


def test_critical_type_confirmed_even_with_single_low_confidence_signal() -> None:
    text = "СНИЛС 112-233-445 95 указан в анкете."
    document = _document(text)
    start = text.index("112-233-445 95")
    end = start + len("112-233-445 95")
    weak_ner = StubDetector(
        "natasha",
        Source.NER,
        50,
        [Entity(EntityType.SNILS, text[start:end], 0, start, end, Source.NER, confidence=0.2)],
    )

    result = DetectAgent(detectors=[weak_ner]).detect(document)

    (snils,) = result.entities
    assert snils.level == ConfidenceLevel.CONFIRMED


def test_sweep_hit_of_open_class_value_does_not_inherit_confirmed_from_repetition() -> None:
    """Значение встречается дважды: один раз находит единственный детектор,
    второй раз — только `sweep` (копия того же текста в другом сегменте).
    Повторение само по себе — не второй независимый сигнал (Р8): sweep не
    участвует в подсчёте `signal_count`, иначе достаточно было бы дважды
    напечатать любое слово, чтобы получить `CONFIRMED`."""
    document = Document(
        path="test.docx",
        fmt="docx",
        segments=[
            Segment(
                "Поставщик Смирнов Пётр Александрович подписал акт.", Anchor("docx", ("body", 0)), 0
            ),
            Segment(
                "Копия акта передана Смирнов Пётр Александрович.", Anchor("docx", ("body", 1)), 1
            ),
        ],
    )
    text0 = document.segments[0].text
    start0 = text0.index("Смирнов")
    end0 = start0 + len("Смирнов Пётр Александрович")
    ner = StubDetector(
        "natasha",
        Source.NER,
        50,
        [
            Entity(
                EntityType.PERSON, text0[start0:end0], 0, start0, end0, Source.NER, confidence=0.6
            )
        ],
    )

    result = DetectAgent(detectors=[ner]).detect(document)

    by_segment = {entity.segment_order: entity for entity in result.entities}
    assert by_segment[0].source is Source.NER
    assert by_segment[1].source is Source.RULE  # найдено sweep'ом
    assert by_segment[0].level == ConfidenceLevel.POSSIBLE
    assert by_segment[1].level == ConfidenceLevel.POSSIBLE
