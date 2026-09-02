"""Контракт подключаемых детекторов и централизованный merge."""

from dataclasses import dataclass

import pytest

from masker.detect.agent import DetectAgent
from masker.model import Anchor, Document, Entity, EntityType, Segment, Source


def _document(text: str = "ООО Ромашка, ИНН 7707083893") -> Document:
    return Document(
        path="document.docx",
        fmt="docx",
        segments=[Segment(text=text, anchor=Anchor(fmt="docx", locator=("body", 0)), order=0)],
    )


@dataclass
class StubDetector:
    name: str
    source: Source
    priority: int
    entities: list[Entity]
    calls: list[str]

    def detect(self, document: Document) -> list[Entity]:
        self.calls.append(self.name)
        return self.entities


def test_injected_detectors_are_called_and_share_a_chunk() -> None:
    document = _document()
    calls: list[str] = []
    org_start = document.segments[0].text.index("ООО")
    inn_start = document.segments[0].text.index("7707083893")
    first = StubDetector(
        "first",
        Source.NER,
        1,
        [
            Entity(EntityType.ORG_NAME, "ООО Ромашка", 0, org_start, org_start + 11, Source.NER),
        ],
        calls,
    )
    second = StubDetector(
        "second",
        Source.RULE,
        2,
        [Entity(EntityType.INN, "7707083893", 0, inn_start, inn_start + 10, Source.RULE)],
        calls,
    )

    result = DetectAgent([first, second]).detect(document)

    assert calls == ["first", "second"]
    assert len(result.chunks) == 1
    assert [entity.type for entity in result.chunks[0].entities] == [
        EntityType.ORG_NAME,
        EntityType.INN,
    ]


def test_rule_priority_carves_overlapping_model_entity() -> None:
    document = _document()
    text = document.segments[0].text
    inn_start = text.index("7707083893")
    model = StubDetector(
        "model",
        Source.NER,
        1,
        [Entity(EntityType.ORG_NAME, text, 0, 0, len(text), Source.NER)],
        [],
    )
    rules = StubDetector(
        "rules",
        Source.RULE,
        100,
        [Entity(EntityType.INN, "7707083893", 0, inn_start, inn_start + 10, Source.RULE)],
        [],
    )

    result = DetectAgent([model, rules]).detect(document)

    assert [(entity.type, entity.text) for entity in result.entities] == [
        (EntityType.ORG_NAME, "ООО Ромашка"),
        (EntityType.INN, "7707083893"),
    ]


def test_invalid_plugin_span_fails_with_detector_name() -> None:
    document = _document()
    broken = StubDetector(
        "broken-detector",
        Source.NER,
        1,
        [Entity(EntityType.PERSON, "wrong", 0, 0, 4, Source.NER)],
        [],
    )

    with pytest.raises(ValueError, match="broken-detector"):
        DetectAgent([broken]).detect(document)


def test_default_detectors_include_rules_then_natasha() -> None:
    agent = DetectAgent()

    # `org_form` (план T2.2.2, шаг 6, Д11) — между `address` и `natasha`:
    # приоритет 60 ниже правил/адреса, выше локальной NER-модели.
    assert [detector.name for detector in agent.detectors] == [
        "rules",
        "address",
        "org_form",
        "natasha",
    ]


def test_explicit_rules_do_not_load_natasha() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from masker.detect import DetectAgent; "
            "from masker.detect.rules import RuleDetector; "
            "DetectAgent([RuleDetector()]); assert 'natasha' not in sys.modules",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
