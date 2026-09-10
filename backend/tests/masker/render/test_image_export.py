"""Round-trip PDF-артефакта в исходный формат картинки."""

from __future__ import annotations

import pathlib

import pymupdf
from PIL import Image

from masker.ingest.image_meta import ImageMetadata, probe
from masker.render.image_export import pdf_to_image


def _fake_meta(source: pathlib.Path) -> ImageMetadata:
    return probe(source)


def _make_pdf_from_image(src: pathlib.Path, dst: pathlib.Path) -> None:
    """Единичный шаг «картинка → одностраничный PDF» через Pillow."""
    with Image.open(str(src)) as image:
        image.convert("RGB").save(str(dst), format="PDF", resolution=float(300))


def test_round_trip_png_size_preserved(tmp_path: pathlib.Path) -> None:
    original = tmp_path / "src.png"
    Image.new("RGB", (600, 400), (200, 200, 200)).save(str(original), format="PNG", dpi=(300, 300))
    pdf = tmp_path / "artifact.pdf"
    _make_pdf_from_image(original, pdf)
    meta = _fake_meta(original)
    dst = tmp_path / "out.png"
    pdf_to_image(pdf, meta, dst)

    with Image.open(str(dst)) as restored:
        assert restored.width == 600
        assert restored.height == 400
        assert restored.format == "PNG"
        dpi = restored.info.get("dpi")
        assert dpi is not None
        # PNG хранит `pHYs` в пикселях/метр — при round-trip 300 dpi
        # получается 299.999… Разбежка не более 0.01.
        assert abs(dpi[0] - 300) < 0.1
        assert abs(dpi[1] - 300) < 0.1
        # EXIF-стриппинг: у нас не должно быть тега Software/Artist/Camera.
        exif = restored.getexif()
        # Разрешено только 0x0112 (Orientation) — Pillow может не писать
        # его вовсе, что тоже нормально.
        forbidden = {0x0131, 0x013B, 0x8298, 0x010E, 0x010F, 0x0110}
        assert not (set(exif) & forbidden), f"неожиданные EXIF-теги: {sorted(exif)}"


def test_round_trip_jpeg_deterministic(tmp_path: pathlib.Path) -> None:
    original = tmp_path / "src.jpg"
    Image.new("RGB", (400, 300), (255, 255, 255)).save(str(original), format="JPEG", dpi=(200, 200))
    pdf = tmp_path / "artifact.pdf"
    _make_pdf_from_image(original, pdf)
    meta = _fake_meta(original)

    dst1 = tmp_path / "out1.jpg"
    dst2 = tmp_path / "out2.jpg"
    pdf_to_image(pdf, meta, dst1)
    pdf_to_image(pdf, meta, dst2)
    # Два прогона с фиксированным quality/optimize должны давать
    # побайтово одинаковый JPEG (инвариант идемпотентности плана).
    assert dst1.read_bytes() == dst2.read_bytes()


def test_round_trip_rejects_multipage_pdf(tmp_path: pathlib.Path) -> None:
    src = tmp_path / "src.png"
    Image.new("RGB", (100, 100)).save(str(src), format="PNG", dpi=(200, 200))
    pdf = tmp_path / "multi.pdf"
    doc = pymupdf.open()
    doc.new_page(width=100, height=100)
    doc.new_page(width=100, height=100)
    doc.save(str(pdf))
    doc.close()

    meta = _fake_meta(src)
    try:
        pdf_to_image(pdf, meta, tmp_path / "out.png")
    except ValueError as e:
        assert "одностраничный" in str(e)
    else:  # pragma: no cover
        raise AssertionError("многостраничный PDF должен подниматься как ValueError")
