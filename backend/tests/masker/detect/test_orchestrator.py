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
    # `dates` (план T1.15) — рядом, приоритет 95, до `org_form`.
    # `contract_amount` / `money` / `delivery_period` / `payment_terms` — правила параметров.
    # `morph_person` (план Р4) — последним, приоритет 45, ниже `natasha` (50):
    # добирает морфологически опознанные ФИО там, где Natasha молчит.
    assert [detector.name for detector in agent.detectors] == [
        "rules",
        "address",
        "dates",
        "contract_amount",
        "money",
        "delivery_period",
        "payment_terms",
        "org_form",
        "natasha",
        "morph_person",
    ]


def test_default_detectors_add_llm_filter_when_specs_have_it() -> None:
    """Если среди пользовательских спеков есть `regex_llm_filter`, в набор
    добавляется `LlmFilterDetector` — иначе спека физически не отработает."""
    from masker.detect import default_detectors
    from masker.llm import FakeProvider
    from masker.typeconfig import load_type_config

    specs = load_type_config(
        {
            "version": 1,
            "types": [
                {
                    "id": "internal_code",
                    "title": "Внутренний код",
                    "marker": "[КОД-{n}]",
                    "critical": False,
                    "detect": {"kind": "regex_llm_filter", "pattern": r"\d{4}"},
                }
            ],
        }
    )
    detectors = default_detectors(specs, llm=FakeProvider([]))

    assert any(detector.name == "llm_filter" for detector in detectors)


def test_default_detectors_reject_llm_filter_specs_without_llm() -> None:
    """Тихий пропуск `regex_llm_filter`-спеки без LLM — та же утечка, что и
    молча непоискаемый GLiNER-тип (T1.13.1, решение Р2). Требуем явную
    ошибку с именами затронутых типов."""
    from masker.detect import default_detectors
    from masker.typeconfig import load_type_config

    specs = load_type_config(
        {
            "version": 1,
            "types": [
                {
                    "id": "internal_code",
                    "title": "Внутренний код",
                    "marker": "[КОД-{n}]",
                    "critical": False,
                    "detect": {"kind": "regex_llm_filter", "pattern": r"\d{4}"},
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="internal_code"):
        default_detectors(specs, llm=None)


def test_explicit_rules_do_not_load_natasha() -> None:
    import os
    import subprocess
    import sys
    from pathlib import Path

    # Эталонный путь к backend/src — editable install указывает на корневой
    # src (где нет .py-файлов), поэтому subprocess явно получает правильный
    # PYTHONPATH, иначе `masker.detect` разрешается как пустой namespace-пакет.
    backend_src = str(Path(__file__).resolve().parents[3] / "src")
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{backend_src}:{existing}" if existing else backend_src

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from masker.detect import DetectAgent; "
            "from masker.detect.rules import RuleDetector; "
            "DetectAgent([RuleDetector()]); assert 'natasha' not in sys.modules",
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
