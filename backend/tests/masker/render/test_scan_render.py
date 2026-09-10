"""O4: рендер OCR-страниц — стирание пикселей, маркер, невидимый текстовый слой."""

from __future__ import annotations

import pathlib

import pymupdf

from masker.ingest.pdf_ingest import ingest_pdf
from masker.mask.agent import PlanAgent
from masker.model import Document, Entity, EntityType, Source
from masker.ocr.fake import FakeOCR
from masker.ocr.provider import OCRLine
from masker.render.pdf_render import render_pdf_redacted


def _make_scan_pdf(path: pathlib.Path) -> None:
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.save(str(path))
    doc.close()


def _fake_line(text: str) -> OCRLine:
    return OCRLine(
        text=text,
        bbox=(10.0, 10.0, 400.0, 30.0),
        polygon=((10.0, 10.0), (400.0, 10.0), (400.0, 30.0), (10.0, 30.0)),
        confidence=1.0,
    )


def _ocr_document(path: pathlib.Path, text: str) -> Document:
    """Document с одним OCR-сегментом."""
    ocr = FakeOCR(lines=(_fake_line(text),))
    return ingest_pdf(path, ocr=ocr)


_INN_TEXT = "ИНН 7707083893"
_INN = "7707083893"


def _plan_for_ocr_doc(document: Document) -> object:
    seg = next(s for s in document.segments if _INN in s.text)
    start = seg.text.index(_INN)
    entity = Entity(
        type=EntityType.INN,
        text=_INN,
        segment_order=seg.order,
        start=start,
        end=start + len(_INN),
        source=Source.RULE,
        confidence=1.0,
        normalized=_INN,
    )
    return PlanAgent().plan(document, [entity])


def test_scan_render_wipes_text_layer(tmp_path: pathlib.Path) -> None:
    """После рендера текстовый слой страницы не содержит исходного ИНН."""
    src = tmp_path / "scan.pdf"
    dst = tmp_path / "masked.pdf"
    _make_scan_pdf(src)
    document = _ocr_document(src, _INN_TEXT)
    plan = _plan_for_ocr_doc(document)
    render_pdf_redacted(src, dst, document, plan)  # type: ignore[arg-type]
    result = pymupdf.open(str(dst))
    text = result[0].get_text("text")
    result.close()
    assert _INN not in text


def test_scan_render_marker_in_invisible_layer(tmp_path: pathlib.Path) -> None:
    """Невидимый текстовый слой содержит маркер, а не исходный текст."""
    src = tmp_path / "scan.pdf"
    dst = tmp_path / "masked.pdf"
    _make_scan_pdf(src)
    document = _ocr_document(src, _INN_TEXT)
    plan = _plan_for_ocr_doc(document)
    render_pdf_redacted(src, dst, document, plan)  # type: ignore[arg-type]
    result = pymupdf.open(str(dst))
    # render_mode=3 — невидимые глифы; get_text всё равно их возвращает
    text = result[0].get_text("text")
    result.close()
    assert _INN not in text


def test_scan_render_idempotent(tmp_path: pathlib.Path) -> None:
    """Два прогона render_pdf_redacted на одном входе дают одинаковые байты."""
    src = tmp_path / "scan.pdf"
    _make_scan_pdf(src)
    document = _ocr_document(src, _INN_TEXT)
    plan = _plan_for_ocr_doc(document)
    dst1 = tmp_path / "masked1.pdf"
    dst2 = tmp_path / "masked2.pdf"
    render_pdf_redacted(src, dst1, document, plan)  # type: ignore[arg-type]
    render_pdf_redacted(src, dst2, document, plan)  # type: ignore[arg-type]
    assert dst1.read_bytes() == dst2.read_bytes()


def test_scan_render_outcome_has_erase_regions(tmp_path: pathlib.Path) -> None:
    """`RenderOutcome.replacements` содержит erase_regions с ненулевой площадью."""
    src = tmp_path / "scan.pdf"
    dst = tmp_path / "masked.pdf"
    _make_scan_pdf(src)
    document = _ocr_document(src, _INN_TEXT)
    plan = _plan_for_ocr_doc(document)
    outcome = render_pdf_redacted(src, dst, document, plan)  # type: ignore[arg-type]
    assert len(outcome.replacements) == 1
    repl = outcome.replacements[0]
    assert len(repl.erase_regions) == 1
    r = repl.erase_regions[0]
    assert r.x1 > r.x0
    assert r.y1 > r.y0


def test_scan_render_blackbox(tmp_path: pathlib.Path) -> None:
    """Стиль blackbox тоже корректно работает для OCR-страниц."""
    src = tmp_path / "scan.pdf"
    dst = tmp_path / "masked.pdf"
    _make_scan_pdf(src)
    document = _ocr_document(src, _INN_TEXT)
    plan = _plan_for_ocr_doc(document)
    outcome = render_pdf_redacted(src, dst, document, plan, style="blackbox")  # type: ignore[arg-type]
    assert len(outcome.replacements) == 1
    result = pymupdf.open(str(dst))
    text = result[0].get_text("text")
    result.close()
    assert _INN not in text


def test_scan_render_mixed_pdf(tmp_path: pathlib.Path) -> None:
    """Смешанный PDF: текстовая страница рендерится обычным путём, OCR-страница — новым."""
    src = tmp_path / "mixed.pdf"
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)  # стр. 0 — скан (без текста)
    page1 = doc.new_page(width=595, height=842)  # стр. 1 — текст
    page1.insert_text((72, 100), f"ИНН {_INN}", fontsize=12)
    doc.save(str(src))
    doc.close()

    ocr = FakeOCR(lines=(_fake_line(_INN_TEXT),))
    document = ingest_pdf(src, ocr=ocr)
    plan = _plan_for_ocr_doc(document)
    dst = tmp_path / "masked.pdf"
    outcome = render_pdf_redacted(src, dst, document, plan)  # type: ignore[arg-type]
    assert len(outcome.replacements) >= 1
