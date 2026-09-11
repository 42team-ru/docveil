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
