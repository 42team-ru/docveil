"""Тесты pdf_ingest: разбор текстового слоя PDF в Document."""

from __future__ import annotations

import hashlib
import pathlib

import pymupdf

from masker.ingest.pdf_ingest import ingest_pdf

_FONT = str(
    pathlib.Path(__file__).parent.parent.parent.parent
    / "src"
    / "masker"
    / "data"
    / "DejaVuSans.ttf"
)


def _make_pdf(tmp_path: pathlib.Path, pages: list[list[str]]) -> pathlib.Path:
    """Создать PDF с заданным текстом; pages[i] — список строк на странице i."""
    path = tmp_path / "test.pdf"
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        page.insert_font(fontname="dvu", fontfile=_FONT)
        y = 72.0
        for line in lines:
            page.insert_text((72, y), line, fontname="dvu", fontsize=12)
            y += 20
    doc.save(str(path))
    doc.close()
    return path


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_segment_count_equals_nonempty_lines(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["Строка 1", "", "Строка 2", "   ", "Строка 3"]])
    doc = ingest_pdf(path)
    assert len(doc.segments) == 3


def test_order_is_dense_from_zero(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["А", "Б", "В"]])
    doc = ingest_pdf(path)
    assert [s.order for s in doc.segments] == list(range(len(doc.segments)))


def test_anchor_fmt_is_pdf(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["Текст"]])
    doc = ingest_pdf(path)
    assert all(s.anchor.fmt == "pdf" for s in doc.segments)


def test_anchor_locator_structure(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["Текст"]])
    doc = ingest_pdf(path)
    loc = doc.segments[0].anchor.locator
    assert loc[0] == "page"
    assert len(loc) == 6
    assert all(isinstance(v, float) for v in loc[2:])


def test_blank_lines_are_skipped(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["", "   ", "\t"]])
    doc = ingest_pdf(path)
    assert len(doc.segments) == 0


def test_image_blocks_are_skipped(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "img.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    # Вставить прямоугольник — это vector drawing block, не text block (type!=0)
    page.draw_rect(pymupdf.Rect(10, 10, 100, 100), color=(0, 0, 0))
    doc.save(str(path))
    doc.close()
    result = ingest_pdf(path)
    assert len(result.segments) == 0


def test_multipage_order(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["А"], ["Б"], ["В"]])
    doc = ingest_pdf(path)
    texts = [s.text.strip() for s in sorted(doc.segments, key=lambda s: s.order)]
    assert texts == ["А", "Б", "В"]


def test_multipage_page_nums_in_locators(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["А"], ["Б"]])
    doc = ingest_pdf(path)
    page_nums = [int(s.anchor.locator[1]) for s in doc.segments]
    assert page_nums == [0, 1]


def test_meta_extraction(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "meta.pdf"
    src = pymupdf.open()
    src.new_page()
    src.set_metadata({"author": "Иван Иванов", "title": "Тест"})
    src.save(str(path))
    src.close()
    doc = ingest_pdf(path)
    assert doc.meta.get("author") == "Иван Иванов"
    assert doc.meta.get("title") == "Тест"


def test_empty_meta_gives_empty_dict(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["Текст"]])
    doc = ingest_pdf(path)
    assert doc.meta == {}


def test_deterministic(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["ИНН 3662103003", "Петров Иван"]])
    doc1 = ingest_pdf(path)
    doc2 = ingest_pdf(path)
    locs1 = [(s.order, s.anchor.locator, s.text) for s in doc1.segments]
    locs2 = [(s.order, s.anchor.locator, s.text) for s in doc2.segments]
    assert locs1 == locs2


def test_source_not_modified(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["Текст"]])
    before = _sha256(path)
    ingest_pdf(path)
    assert _sha256(path) == before


def test_label_contains_page_number(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["А"], ["Б"]])
    doc = ingest_pdf(path)
    labels = [s.anchor.label for s in doc.segments]
    assert "стр. 1" in labels
    assert "стр. 2" in labels
