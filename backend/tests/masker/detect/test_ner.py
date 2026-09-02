from dataclasses import dataclass

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
