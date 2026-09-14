"""Р24: должность подписанта, раскрывающая сторону, маскируется целиком."""

from __future__ import annotations

from masker.detect.persons import find_identifying_signatory_positions
from masker.detect.requisite_blocks import find_requisite_block_candidates
from masker.model import Anchor, Document, Segment


def test_identifying_minister_position_in_preamble_is_complete() -> None:
    """Название ведомства входит в спан, а не остаётся перед замаскированным ФИО."""
    text = (
        "в лице заместителя Министра цифрового развития, связи и массовых "
        "коммуникаций Российской Федерации Угнивенко Дмитрия Константиновича, "
        "действующего на основании доверенности"
    )

    spans = find_identifying_signatory_positions(text)

    assert [text[start:end] for start, end in spans] == [
        "заместителя Министра цифрового развития, связи и массовых коммуникаций "
        "Российской Федерации"
    ]


def test_signatory_position_keeps_tail_after_name_mask_boundary() -> None:
    """«По работе с ...» — часть должности, а не текст после отдельного ФИО."""
    text = (
        "в лице Старшего Вице-Президента по работе с корпоративным и "
        "государственным сегментами ПАО «Ростелеком» Ермакова Валерия "
        "Викторовича, действующего на основании доверенности"
    )

    spans = find_identifying_signatory_positions(text)

    assert [text[start:end] for start, end in spans] == [
        "Старшего Вице-Президента по работе с корпоративным и государственным "
        "сегментами ПАО «Ростелеком»"
    ]


def test_generic_position_without_organization_is_not_masked() -> None:
    """Типовая должность не идентифицирует сторону и сохраняет читабельность."""
    text = "в лице Генерального директора Иванова Ивана Ивановича, действующего на основании Устава"

    assert find_identifying_signatory_positions(text) == []


def test_requisite_candidates_include_signature_position() -> None:
    """Строка подписи находится и без отдельного заголовка реквизитов."""
    text = (
        "от Исполнителя: Старший Вице-Президент по работе с корпоративным и "
        "государственным сегментами ПАО «Ростелеком» ______________ /В.В. Ермаков/"
    )
    document = Document(
        path="x.pdf",
        fmt="pdf",
        segments=[Segment(text=text, anchor=Anchor("pdf", ("page", 0)), order=0)],
    )

    found = find_requisite_block_candidates(document, [])

    assert [entity.text for entity in found] == [
        "Старший Вице-Президент по работе с корпоративным и государственным "
        "сегментами ПАО «Ростелеком»"
    ]


def test_abbreviation_person_filtered_by_detect_agent() -> None:
    """Р13: капс-строка без пробелов («МИК») не должна попасть в персоны."""
    from masker.detect import DetectAgent, default_detectors
    from masker.model import EntityType

    document = Document(
        path="x.docx",
        fmt="docx",
        segments=[
            Segment(text="Реквизиты Поставщика МИК.", anchor=Anchor("docx", ("body", 0)), order=0),
        ],
    )
    entities = DetectAgent(default_detectors()).detect(document).entities
    texts = [e.text for e in entities if e.type is EntityType.PERSON]
    assert "МИК" not in texts, f"Аббревиатура МИК не должна маскироваться: {texts}"


def test_real_name_not_filtered_as_abbreviation() -> None:
    """Р13: нормальное имя «Иванов Иван» содержит пробел — не аббревиатура, не фильтруется."""
    from masker.detect.agent import _is_abbreviation_person
    from masker.model import Entity, EntityType, Source

    entity = Entity(
        type=EntityType.PERSON,
        text="Иванов Иван",
        segment_order=0,
        start=0,
        end=11,
        source=Source.RULE,
        confidence=0.9,
        normalized="иванов иван",
    )
    assert not _is_abbreviation_person(entity)


def test_signatory_positions_skipped_when_morph_disabled() -> None:
    """М11: skip_signatory_positions=True не создаёт кандидатов из подписных строк."""

    text = (
        "от Исполнителя: Старший Вице-Президент по работе с корпоративным и "
        "государственным сегментами ПАО «Ростелеком» ______________ /В.В. Ермаков/"
    )
    document = Document(
        path="x.pdf",
        fmt="pdf",
        segments=[Segment(text=text, anchor=Anchor("pdf", ("page", 0)), order=0)],
    )

    found_with = find_requisite_block_candidates(document, [], skip_signatory_positions=False)
    found_without = find_requisite_block_candidates(document, [], skip_signatory_positions=True)

    assert found_with, "При skip=False должны быть кандидаты"
    assert found_without == [], "При skip=True (rules_only) подписные кандидаты не создаются"
