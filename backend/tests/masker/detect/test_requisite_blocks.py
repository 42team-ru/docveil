"""Тесты `detect.requisite_blocks` — блоки реквизитов/подписей как источник
кандидатов детекции (Р6, TASKS.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from masker.detect.agent import DetectAgent
from masker.detect.requisite_blocks import find_requisite_block_candidates
from masker.ingest.docx_ingest import ingest_docx
from masker.model import (
    Anchor,
    ConfidenceLevel,
    Document,
    Entity,
    EntityType,
    Segment,
    Source,
)


def _document(texts: list[str]) -> Document:
    return Document(
        path="test.docx",
        fmt="docx",
        segments=[
            Segment(text=text, anchor=Anchor("docx", ("body", order)), order=order)
            for order, text in enumerate(texts)
        ],
    )


def test_capitalized_run_inside_requisites_heading_block_becomes_candidate() -> None:
    """Заглавная последовательность под заголовком «Реквизиты X», не найденная
    ни одним детектором, обязана попасть в кандидаты Р6."""
    document = _document(
        [
            "1. Реквизиты Поставщика",
            "Контактное лицо: Особая Персонова.",
        ]
    )

    found = find_requisite_block_candidates(document, entities=[])

    assert len(found) == 1
    candidate = found[0]
    assert candidate.text == "Особая Персонова"
    assert candidate.type == EntityType.PERSON
    assert candidate.segment_order == 1


def test_block_candidate_is_attributed_to_structure_not_to_the_ner_model() -> None:
    """Кандидат из блока реквизитов пришёл от структурного признака, а не от
    локальной модели. ``Source.NER`` в отчёте утверждал бы про происхождение
    сущности то, чего не было, — отчёт обязан быть честным про провенанс."""
    document = _document(
        [
            "1. Реквизиты Поставщика",
            "Контактное лицо: Особая Персонова.",
        ]
    )

    found = find_requisite_block_candidates(document, entities=[])

    assert [item.source for item in found] == [Source.BLOCK]


def test_requisites_heading_line_itself_is_not_a_candidate() -> None:
    """«Реквизиты Поставщика» — название раздела, а не ФИО: у самой строки
    заголовка тоже два заглавных слова подряд, и без явного исключения
    заголовка кандидат получился бы из названия раздела."""
    document = _document(
        [
            "1. Реквизиты Поставщика",
            "Телефон: 8-910-347-51-07",
        ]
    )

    found = find_requisite_block_candidates(document, entities=[])

    assert found == []


def test_run_overlapping_existing_entity_is_not_duplicated() -> None:
    """Значение, которое уже нашёл любой другой детектор, — не кандидат Р6:
    без проверки перекрытия по `entities` появился бы дубль той же сущности."""
    document = _document(
        [
            "1. Реквизиты Поставщика",
            "Контактное лицо: Особая Персонова.",
        ]
    )
    segment = document.segments[1]
    start = segment.text.index("Особая Персонова")
    end = start + len("Особая Персонова")
    already_found = [
        Entity(
            type=EntityType.PERSON,
            text="Особая Персонова",
            segment_order=1,
            start=start,
            end=end,
            source=Source.NER,
            confidence=0.9,
        )
    ]

    found = find_requisite_block_candidates(document, already_found)

    assert found == []


def test_signature_line_without_heading_still_yields_candidate() -> None:
    """Строка подписи («Роль: ФИО») образует блок БЕЗ заголовка
    (`build_context_blocks` обрывает блок на смене метки роли) — без
    отдельной ветки по `SIGNATURE` подписной блок вовсе не стал бы
    источником кандидатов, вопреки прямому требованию задачи Р6."""
    document = _document(["Поставщик: ______________ Особая Персонова"])

    found = find_requisite_block_candidates(document, entities=[])

    assert len(found) == 1
    assert found[0].text == "Особая Персонова"


def test_footer_mentioning_signed_document_is_not_a_signature_section() -> None:
    """«Документ подписан...» — обычный футер PDF (реальный кейс
    `contract_pdf_02_school.pdf`), не заголовок раздела подписей: у слова
    «подписан» тот же корень, что у «подписи», но другая словоформа. Слепая
    подстрочная проверка `"подпис" in heading` ложно приняла бы этот футер за
    раздел подписей и вынесла бы в кандидаты «РТС-тендер»/«Договор»."""
    document = _document(
        ['Документ подписан на ЭП "РТС-тендер" Договор №2025.334807 Страница 1 из 44']
    )

    found = find_requisite_block_candidates(document, entities=[])

    assert found == []


def test_capitalized_run_outside_any_requisite_or_signature_block_is_ignored() -> None:
    """Обычный абзац преамбулы без метки реквизитов/подписи — не источник
    кандидатов Р6: иначе любое двухсловное заглавное сочетание в тексте
    договора (не только в реквизитах) стало бы кандидатом, взорвав точность."""
    document = _document(
        [
            "Общие положения",
            "Особая Персонова упомянута в преамбуле как контактное лицо.",
        ]
    )

    found = find_requisite_block_candidates(document, entities=[])

    assert found == []


def test_role_word_next_to_unrelated_capitalized_word_is_not_a_candidate() -> None:
    """Реальный дефект на `contract_pdf_02_school.pdf`: метаданные сертификата
    ЭП склеены в одну строку без переносов — «Должность: Директор Сертификат
    ЭП действителен с:». «Директор» (должность) вплотную к «Сертификат»
    (слово следующего поля) даёт заглавную пару без единого настоящего
    имени; без среза ведущей должности это стало бы ложным кандидатом."""
    document = _document(
        [
            "1. Реквизиты Поставщика",
            "Должность: Директор Сертификат ЭП действителен с: 01.01.2026",
        ]
    )

    found = find_requisite_block_candidates(document, entities=[])

    assert found == []


def test_negative_corpus_document_yields_no_requisite_candidates() -> None:
    """На негативном корпусе (`fixtures/negative`, ни одной PII) в документе
    нет ни блока реквизитов, ни подписного блока — Р6 обязана молчать."""
    fixture = Path(__file__).parents[3] / "fixtures" / "negative" / "negative_01_gost.docx"
    document = ingest_docx(fixture)

    found = find_requisite_block_candidates(document, entities=[])

    assert found == []


@dataclass
class _StubDetector:
    name: str
    source: Source
    priority: int
    types: frozenset[str]
    entities: list[Entity]

    def detect(self, document: Document) -> list[Entity]:
        return self.entities


def test_block_candidate_reaches_possible_level_via_detect_agent() -> None:
    """Приёмка Р6: заглавная последовательность в блоке реквизитов, не
    опознанная ни одним детектором, доезжает через `DetectAgent.detect()` до
    уровня `ConfidenceLevel.POSSIBLE` — того же уровня, что уже определён в
    Р8, без отдельной жёстко прибитой метки."""
    document = _document(
        [
            "1. Реквизиты Поставщика",
            "Контактное лицо: Особая Персонова.",
        ]
    )
    # Ни один детектор ничего не находит — сущность появляется только
    # благодаря блокам реквизитов (Р6).
    empty_detector = _StubDetector("stub", Source.RULE, 100, frozenset({EntityType.INN}), [])

    result = DetectAgent(detectors=[empty_detector]).detect(document)

    candidates = [entity for entity in result.entities if entity.type == EntityType.PERSON]
    assert len(candidates) == 1
    assert candidates[0].text == "Особая Персонова"
    assert candidates[0].level == ConfidenceLevel.POSSIBLE


def test_critical_type_untouched_by_requisite_block_candidates() -> None:
    """Критичный тип, уже найденный обычным детектором внутри блока
    реквизитов, не переоткрывается и не переопределяется кандидатом Р6 —
    рядом стоящее заглавное имя не должно задеть уже принятую сущность ИНН."""
    text = "ИНН 7707083893 контактное лицо Особая Персонова."
    document = _document(["1. Реквизиты Поставщика", text])
    segment = document.segments[1]
    start = segment.text.index("7707083893")
    end = start + len("7707083893")
    rule_detector = _StubDetector(
        "rule",
        Source.RULE,
        100,
        frozenset({EntityType.INN}),
        [
            Entity(
                type=EntityType.INN,
                text="7707083893",
                segment_order=1,
                start=start,
                end=end,
                source=Source.RULE,
                confidence=1.0,
            )
        ],
    )

    result = DetectAgent(detectors=[rule_detector]).detect(document)

    inn_entities = [entity for entity in result.entities if entity.type == EntityType.INN]
    assert len(inn_entities) == 1
    assert inn_entities[0].level == ConfidenceLevel.CONFIRMED
    assert inn_entities[0].text == "7707083893"
    person_candidates = [entity for entity in result.entities if entity.type == EntityType.PERSON]
    assert len(person_candidates) == 1
    assert person_candidates[0].text == "Особая Персонова"
    assert person_candidates[0].level == ConfidenceLevel.POSSIBLE
