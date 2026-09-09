"""O3: пер-страничный роутинг скан/текст в ``ingest_pdf``.

Тесты создают PDF программно через PyMuPDF без внешних файлов.
``FakeOCR`` возвращает детерминированные строки; ``ingest_pdf`` при
``ocr=None`` работает как прежде — регрессия не допускается.
"""

from __future__ import annotations

import pathlib

import pymupdf

from masker.ingest.pdf_ingest import ingest_pdf
from masker.ingest.scan_ingest import _char_coverage_ratio, _page_is_scan
from masker.ocr.fake import FakeOCR
from masker.ocr.provider import OCRLine

# ── вспомогательные фабрики PDF ─────────────────────────────────────────────


def _make_text_pdf(path: pathlib.Path, text: str = "Привет мир") -> None:
    """PDF с одной текстовой страницей."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def _make_scan_pdf(path: pathlib.Path) -> None:
    """PDF с одной страницей-изображением (без текстового слоя)."""
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    # PyMuPDF не добавляет текстовый слой автоматически; страница без
    # insert_text будет иметь пустой get_text — достаточно для роутера.
    doc.save(str(path))
    doc.close()


def _make_mixed_pdf(path: pathlib.Path) -> None:
    """PDF: стр.1 — скан (без текста), стр.2 — текст."""
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)  # стр. 0 — пустая (скан)
    page1 = doc.new_page(width=595, height=842)  # стр. 1 — текст
    page1.insert_text((72, 100), "ИНН 7707083893", fontsize=12)
    doc.save(str(path))
    doc.close()


# ── роутер _page_is_scan ─────────────────────────────────────────────────────


def test_empty_page_is_scan(tmp_path: pathlib.Path) -> None:
    _make_scan_pdf(tmp_path / "scan.pdf")
    doc = pymupdf.open(str(tmp_path / "scan.pdf"))
    assert _page_is_scan(doc[0]) is True
    doc.close()


def test_text_page_is_not_scan(tmp_path: pathlib.Path) -> None:
    _make_text_pdf(tmp_path / "text.pdf")
    doc = pymupdf.open(str(tmp_path / "text.pdf"))
    assert _page_is_scan(doc[0]) is False
    doc.close()


def test_char_coverage_ratio_positive_on_text_page(tmp_path: pathlib.Path) -> None:
    _make_text_pdf(tmp_path / "text.pdf")
    doc = pymupdf.open(str(tmp_path / "text.pdf"))
    ratio = _char_coverage_ratio(doc[0])
    assert ratio > 0.0
    doc.close()


# ── ingest_pdf без OCR — регрессия ───────────────────────────────────────────


def test_ingest_pdf_without_ocr_unchanged(tmp_path: pathlib.Path) -> None:
    """Без аргумента ``ocr`` поведение как до T2.3."""
    _make_text_pdf(tmp_path / "text.pdf", "ИНН 7707083893")
    doc = ingest_pdf(tmp_path / "text.pdf")
    assert doc.fmt == "pdf"
    texts = " ".join(s.text for s in doc.segments)
    assert "7707083893" in texts
    # все сегменты — origin="text"
    assert all(s.origin == "text" for s in doc.segments)


# ── пер-страничный роутинг с FakeOCR ────────────────────────────────────────


def _fake_line(text: str) -> OCRLine:
    return OCRLine(
        text=text,
        bbox=(10.0, 10.0, 200.0, 30.0),
        polygon=((10.0, 10.0), (200.0, 10.0), (200.0, 30.0), (10.0, 30.0)),
        confidence=1.0,
    )


def test_scan_page_uses_ocr_segments(tmp_path: pathlib.Path) -> None:
    """Пустая страница → сегменты берутся из FakeOCR, origin='ocr'."""
    _make_scan_pdf(tmp_path / "scan.pdf")
    ocr = FakeOCR(lines=(_fake_line("Иванов ИНН 7707083893"),))
    doc = ingest_pdf(tmp_path / "scan.pdf", ocr=ocr)
    assert len(doc.segments) == 1
    assert doc.segments[0].origin == "ocr"
    assert "7707083893" in doc.segments[0].text
    # якорь содержит маркер "ocr"
    assert doc.segments[0].anchor.locator[2] == "ocr"


def test_mixed_pdf_routes_per_page(tmp_path: pathlib.Path) -> None:
    """Смешанный PDF: стр.0 — скан → origin='ocr', стр.1 — текст → origin='text'."""
    _make_mixed_pdf(tmp_path / "mixed.pdf")
    ocr = FakeOCR(lines=(_fake_line("Петров ОГРН 1027739227662"),))
    doc = ingest_pdf(tmp_path / "mixed.pdf", ocr=ocr)

    ocr_segs = [s for s in doc.segments if s.origin == "ocr"]
    text_segs = [s for s in doc.segments if s.origin == "text"]

    assert len(ocr_segs) >= 1, "скан-страница должна дать хотя бы один OCR-сегмент"
    assert len(text_segs) >= 1, "текстовая страница должна дать хотя бы один текстовый сегмент"

    assert "Петров" in ocr_segs[0].text
    assert "7707083893" in " ".join(s.text for s in text_segs)


def test_scan_segment_anchor_has_pt_coords(tmp_path: pathlib.Path) -> None:
    """Якорь OCR-сегмента содержит pt-координаты, а не пиксельные."""
    _make_scan_pdf(tmp_path / "scan.pdf")
    # bbox в пикселях при 400 dpi (DPI поднят в fbde4d6); pt = px * 72/400
    ocr = FakeOCR(lines=(_fake_line("тест"),))
    doc = ingest_pdf(tmp_path / "scan.pdf", ocr=ocr)
    assert len(doc.segments) == 1
    locator = doc.segments[0].anchor.locator
    # locator = ("page", page_num, "ocr", x0, y0, x1, y1)
    assert locator[0] == "page"
    assert locator[2] == "ocr"
    # координаты целочисленные (умножены на 100 и округлены)
    x0, y0, x1, y1 = locator[3], locator[4], locator[5], locator[6]
    assert isinstance(x0, int) and isinstance(y0, int)
    # pt_per_px = 72/400 = 0.18; bbox_px=(10,10,200,30) → pt=(1.8,1.8,36.0,5.4)
    # ×100 → (180, 180, 3600, 540)
    assert x0 == 180
    assert y0 == 180
    assert x1 == 3600
    assert y1 == 540


def test_ocr_calls_counted(tmp_path: pathlib.Path) -> None:
    """FakeOCR.calls растёт на количество обработанных скан-страниц."""
    _make_mixed_pdf(tmp_path / "mixed.pdf")
    ocr = FakeOCR(lines=(_fake_line("тест"),))
    ingest_pdf(tmp_path / "mixed.pdf", ocr=ocr)
    assert ocr.calls == 1  # только одна скан-страница
