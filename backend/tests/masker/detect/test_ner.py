from dataclasses import dataclass

import pytest

from masker.detect.ner import NatashaDetector, NerSpan
from masker.model import Anchor, Document, EntityType, Segment


@dataclass
class FakeTagger:
    result: dict[str, list[NerSpan]]

    def spans(self, text: str) -> list[NerSpan]:
        return self.result[text]


def _document(*texts: str) -> Document:
    return Document(
        path="test.docx",
        fmt="docx",
        segments=[
            Segment(text, Anchor("docx", ("body", index)), index)
            for index, text in enumerate(texts)
        ],
    )


def test_loc_span_produces_no_entity() -> None:
    document = _document("Воронеж, ООО Вектор")
    tagger = FakeTagger({document.segments[0].text: [NerSpan(0, 7, "LOC"), NerSpan(9, 19, "ORG")]})

    entities = NatashaDetector(tagger).detect(document)

    assert [(entity.type, entity.text) for entity in entities] == [
        (EntityType.ORG_NAME, "ООО Вектор")
    ]
    assert all(entity.type is not EntityType.ADDRESS for entity in entities)


def test_spans_are_local_to_segment() -> None:
    document = _document("Иванов Иван", "ООО Вектор")
    tagger = FakeTagger(
        {"Иванов Иван": [NerSpan(0, 11, "PER")], "ООО Вектор": [NerSpan(0, 10, "ORG")]}
    )

    entities = NatashaDetector(tagger).detect(document)

    assert [(entity.segment_order, entity.start, entity.end) for entity in entities] == [
        (0, 0, 11),
        (1, 0, 10),
    ]


def test_role_word_is_dropped() -> None:
    document = _document("Поставщика")
    tagger = FakeTagger({"Поставщика": [NerSpan(0, 10, "PER")]})

    assert NatashaDetector(tagger).detect(document) == []


def test_single_uppercase_abbreviation_is_not_person() -> None:
    """Р13: даже триггер должности не превращает «МИК» в фамилию."""
    text = "Директор МИК"
    document = _document(text)
    start = text.index("МИК")
    tagger = FakeTagger({text: [NerSpan(start, start + len("МИК"), "PER")]})

    assert NatashaDetector(tagger).detect(document) == []


def test_overlong_model_span_is_shrunk() -> None:
    text = 'ООО "Ромашка" (ОКПО 12345678'
    document = _document(text)
    tagger = FakeTagger({text: [NerSpan(0, len(text), "ORG")]})

    [entity] = NatashaDetector(tagger).detect(document)

    assert entity.text == 'ООО "Ромашка"'
    assert entity.normalized == "ромашка"


def test_public_body_is_dropped() -> None:
    text = "Арбитражного суда"
    document = _document(text)
    tagger = FakeTagger({text: [NerSpan(0, len(text), "ORG")]})

    assert NatashaDetector(tagger).detect(document) == []


@pytest.mark.parametrize(
    "text",
    (
        "Федерального закона",
        "В соответствии с Федеральным законом",
    ),
)
def test_federal_law_reference_is_not_organization(text: str) -> None:
    """Р19: название нормативного акта не является стороной договора."""
    document = _document(text)
    tagger = FakeTagger({text: [NerSpan(0, len(text), "ORG")]})

    assert NatashaDetector(tagger).detect(document) == []


def test_organization_name_without_law_reference_is_still_detected() -> None:
    text = "АО «Триема»"
    document = _document(text)
    tagger = FakeTagger({text: [NerSpan(0, len(text), "ORG")]})

    assert [(entity.type, entity.text) for entity in NatashaDetector(tagger).detect(document)] == [
        (EntityType.ORG_NAME, text)
    ]


def test_single_token_org_without_evidence_is_dropped() -> None:
    text = "Резистор МЛТ-0,25"
    document = _document(text)
    tagger = FakeTagger({text: [NerSpan(0, len("Резистор"), "ORG")]})

    assert NatashaDetector(tagger).detect(document) == []


def test_org_with_form_or_quotes_survives() -> None:
    texts = (
        "АО «Триема»",
        "Общество с ограниченной ответственностью «Вектор»",
        "ООО «Мойдодыр»",
    )
    first_start = texts[0].index("Триема")
    second_start = texts[1].index("Вектор")
    third_start = texts[2].index("Мойдодыр")
    document = _document(*texts)
    tagger = FakeTagger(
        {
            "АО «Триема»": [NerSpan(first_start, first_start + len("Триема"), "ORG")],
            "Общество с ограниченной ответственностью «Вектор»": [
                NerSpan(second_start, second_start + len("Вектор"), "ORG")
            ],
            "ООО «Мойдодыр»": [NerSpan(third_start, third_start + len("Мойдодыр"), "ORG")],
        }
    )

    entities = NatashaDetector(tagger).detect(document)

    assert [(entity.type, entity.text) for entity in entities] == [
        (EntityType.ORG_NAME, "АО «Триема»"),
        (EntityType.ORG_NAME, "Общество с ограниченной ответственностью «Вектор»"),
        (EntityType.ORG_NAME, "ООО «Мойдодыр»"),
    ]


def test_formula_variable_with_multiplication_sign_is_not_organization() -> None:
    """11.09.2026: ``ДК `` в формуле пени не должен стать названием организации."""
    text = "ДП К = 100% ДК "
    document = _document(text)
    start = text.index("ДК")
    tagger = FakeTagger({text: [NerSpan(start, len(text), "ORG")]})

    assert NatashaDetector(tagger).detect(document) == []


def test_short_quoted_organization_name_survives() -> None:
    """Парные кавычки остаются достаточным признаком короткого названия."""
    text = "«ДОУ»"
    document = _document(text)
    tagger = FakeTagger({text: [NerSpan(0, len(text), "ORG")]})

    assert [(entity.type, entity.text) for entity in NatashaDetector(tagger).detect(document)] == [
        (EntityType.ORG_NAME, "«ДОУ»"),
    ]
