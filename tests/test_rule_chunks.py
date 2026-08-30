"""Агрегация формальных PII в контекстные чанки."""

from masker.detect.result import CHUNK_MAX, CHUNK_MIN, build_pii_chunks
from masker.detect.rules import detect_by_rules
from masker.model import Anchor, EntityType, Segment


def _segment(text: str, order: int = 0) -> Segment:
    return Segment(text=text, anchor=Anchor(fmt="docx", locator=("body", order)), order=order)


def test_requisites_in_one_window_form_one_chunk() -> None:
    text = (
        "Реквизиты поставщика: ИНН 7707083893, КПП 770301001, "
        "ОГРН 1027700132195, БИК 042007681, счёт 40702810100000000002."
    )
    segment = _segment(text)

    entities = detect_by_rules([segment])
    chunks = build_pii_chunks([segment], entities)

    assert len(chunks) == 1
    assert [entity.type for entity in chunks[0].entities] == [
        EntityType.INN,
        EntityType.KPP,
        EntityType.OGRN,
        EntityType.BIK,
        EntityType.BANK_ACCOUNT,
    ]
    assert chunks[0].start == 0
    assert chunks[0].end == len(text)


def test_distant_entities_produce_separate_chunks_within_limit() -> None:
    text = f"ИНН 7707083893 {'x' * 700} ОГРН 1027700132195"
    segment = _segment(text)

    chunks = build_pii_chunks([segment], detect_by_rules([segment]))

    assert len(chunks) == 2
    assert all(chunk.end - chunk.start <= CHUNK_MAX for chunk in chunks)
    assert chunks[0].end <= chunks[1].start


def test_short_segment_is_returned_whole() -> None:
    text = "ИНН 7707083893"
    segment = _segment(text)

    chunks = build_pii_chunks([segment], detect_by_rules([segment]))

    assert len(text) < CHUNK_MIN
    assert [(chunk.start, chunk.end) for chunk in chunks] == [(0, len(text))]


def test_chunks_do_not_cross_segment_boundary() -> None:
    first = _segment("ИНН 7707083893", 0)
    second = _segment("ОГРН 1027700132195", 1)

    chunks = build_pii_chunks([first, second], detect_by_rules([first, second]))

    assert [chunk.segment_order for chunk in chunks] == [0, 1]
