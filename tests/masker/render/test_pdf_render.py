"""Тесты pdf_render: preview (highlight) и redacted (настоящее удаление)."""

from __future__ import annotations

import pathlib
import stat

import pymupdf

from masker.ingest.pdf_ingest import ingest_pdf
from masker.model import Entity, EntityType, Source
from masker.render.pdf_render import render_pdf_preview, render_pdf_redacted

_INN = "3662103003"
_AUTHOR = "Тест Автор"


def _make_pdf_with_inn(tmp_path: pathlib.Path, pages: int = 1) -> pathlib.Path:
    path = tmp_path / "source.pdf"
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100 + i * 20), f"ИНН {_INN}", fontsize=12)
    doc.set_metadata({"author": _AUTHOR})
    doc.save(str(path))
    doc.close()
    return path


def _entity_for_doc(document, text: str, etype: EntityType) -> Entity:
    seg = next(s for s in document.segments if text in s.text)
    start = seg.text.index(text)
    return Entity(
        type=etype,
        text=text,
        segment_order=seg.order,
        start=start,
        end=start + len(text),
        source=Source.RULE,
        confidence=1.0,
        normalized=text,
    )


# ── preview ──────────────────────────────────────────────────────────────────


def test_preview_adds_highlight_annotation(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "preview.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_preview(src, dest, document, [entity])
    doc = pymupdf.open(str(dest))
    annots = list(doc[0].annots())
    doc.close()
    assert len(annots) > 0


def test_preview_preserves_original_text(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "preview.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_preview(src, dest, document, [entity])
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert _INN in text


def test_preview_permissions(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "preview.pdf"
    document = ingest_pdf(src)
    render_pdf_preview(src, dest, document, [])
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600


def test_preview_entity_not_found_graceful(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "preview.pdf"
    document = ingest_pdf(src)
    seg = document.segments[0]
    entity = Entity(
        type=EntityType.INN,
        text="0000000000",  # нет в документе
        segment_order=seg.order,
        start=0,
        end=10,
        source=Source.RULE,
    )
    render_pdf_preview(src, dest, document, [entity])  # не должен бросать


# ── redacted ─────────────────────────────────────────────────────────────────


def test_redacted_text_absent_from_text_layer(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_redacted(src, dest, document, [entity])
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert _INN not in text


def test_redacted_text_absent_from_raw_bytes(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_redacted(src, dest, document, [entity])
    assert _INN.encode() not in dest.read_bytes()


def test_redacted_marker_appears_in_text(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_redacted(src, dest, document, [entity])
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert "[INN]" in text


def test_redacted_metadata_cleared(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    render_pdf_redacted(src, dest, document, [])
    doc = pymupdf.open(str(dest))
    author = doc.metadata.get("author", "")
    doc.close()
    assert author == ""


def test_redacted_page_count_preserved(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path, pages=3)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entities = [_entity_for_doc(document, _INN, EntityType.INN)]
    render_pdf_redacted(src, dest, document, entities)
    src_doc = pymupdf.open(str(src))
    dst_doc = pymupdf.open(str(dest))
    assert len(dst_doc) == len(src_doc)
    src_doc.close()
    dst_doc.close()


def test_redacted_permissions(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    render_pdf_redacted(src, dest, document, [])
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600


def test_redacted_entity_not_found_graceful(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    seg = document.segments[0]
    entity = Entity(
        type=EntityType.INN,
        text="0000000000",
        segment_order=seg.order,
        start=0,
        end=10,
        source=Source.RULE,
    )
    render_pdf_redacted(src, dest, document, [entity])  # не должен бросать


def test_blackbox_original_text_absent(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_redacted(src, dest, document, [entity], style="blackbox")
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert _INN not in text


def test_blackbox_no_marker_in_text(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_redacted(src, dest, document, [entity], style="blackbox")
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert "[INN]" not in text


def test_redacted_multipage_all_redacted(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path, pages=2)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    # Создаём по одной сущности для каждого сегмента, содержащего ИНН
    entities = [
        Entity(
            type=EntityType.INN,
            text=_INN,
            segment_order=seg.order,
            start=seg.text.index(_INN),
            end=seg.text.index(_INN) + len(_INN),
            source=Source.RULE,
            confidence=1.0,
            normalized=_INN,
        )
        for seg in document.segments
        if _INN in seg.text
    ]
    render_pdf_redacted(src, dest, document, entities)
    doc = pymupdf.open(str(dest))
    for page in doc:
        assert _INN not in page.get_text()
    doc.close()
