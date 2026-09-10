"""Юниты `ingest_image` и `image_meta.probe`.

Тесты работают только с FakeOCR — реальные движки не поднимаем: гейт и
метаданные проверяются на синтетических картинках, собранных Pillow.
"""

from __future__ import annotations

import io
import pathlib

import pytest
from PIL import Image

from masker.ingest.image_ingest import ingest_image
from masker.ingest.image_meta import (
    DEFAULT_DPI,
    MAX_DPI,
    MIN_DPI,
    MultiPageNotSupported,
    NotADocumentError,
    probe,
)
from masker.ocr.fake import FakeOCR
from masker.ocr.provider import OCRLine

# --- probe -----------------------------------------------------------------


def _make_png(
    path: pathlib.Path, *, size: tuple[int, int] = (200, 100), dpi: int | None = 150
) -> None:
    """Собрать простой RGB-PNG заданного размера и DPI."""
    image = Image.new("RGB", size, (255, 255, 255))
    kwargs: dict[str, object] = {"format": "PNG"}
    if dpi is not None:
        kwargs["dpi"] = (dpi, dpi)
    image.save(str(path), **kwargs)


def _make_jpeg(path: pathlib.Path, *, size: tuple[int, int], dpi: int) -> None:
    image = Image.new("RGB", size, (255, 255, 255))
    image.save(str(path), format="JPEG", dpi=(dpi, dpi))


def test_probe_reads_size_format_and_dpi(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "small.png"
    _make_png(p, size=(300, 200), dpi=200)
    meta = probe(p)
    assert meta.name == "small.png"
    assert meta.suffix == ".png"
    assert meta.width == 300
    assert meta.height == 200
    assert meta.format == "PNG"
    assert meta.dpi_x == 200
    assert meta.dpi_y == 200
    assert meta.orientation == 1
    assert meta.mode == "RGB"
    assert meta.channels == 3
    assert meta.bit_depth == 24


def test_probe_falls_back_to_default_dpi(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "no_dpi.png"
    _make_png(p, size=(100, 100), dpi=None)
    meta = probe(p)
    assert meta.dpi_x == DEFAULT_DPI
    assert meta.dpi_y == DEFAULT_DPI


def test_probe_clamps_absurd_dpi(tmp_path: pathlib.Path) -> None:
    """EXIF врёт DPI — приводим к диапазону `[MIN_DPI, MAX_DPI]`."""
    p = tmp_path / "huge_dpi.png"
    _make_png(p, size=(50, 50), dpi=9999)
    meta = probe(p)
    assert meta.dpi_x == MAX_DPI
    p2 = tmp_path / "tiny_dpi.png"
    _make_png(p2, size=(50, 50), dpi=10)
    meta2 = probe(p2)
    assert meta2.dpi_x >= MIN_DPI


def test_probe_rejects_unknown_suffix(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "x.bmp"
    Image.new("RGB", (10, 10)).save(str(p), format="BMP")
    with pytest.raises(ValueError, match="неподдерживаемое расширение"):
        probe(p)


def test_probe_rejects_multipage_tiff(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "multi.tif"
    frames = [Image.new("RGB", (20, 20), (255, 0, 0)), Image.new("RGB", (20, 20), (0, 255, 0))]
    frames[0].save(str(p), format="TIFF", save_all=True, append_images=frames[1:])
    with pytest.raises(MultiPageNotSupported):
        probe(p)


# --- ingest_image гейт -----------------------------------------------------


def _bbox_for_line(text: str, y: int) -> OCRLine:
    """Простой OCRLine на условной строке `y` — координаты пиксельные."""
    return OCRLine(
        text=text,
        bbox=(50.0, float(y), 50.0 + 10.0 * len(text), float(y + 20)),
        polygon=(
            (50.0, float(y)),
            (50.0 + 10.0 * len(text), float(y)),
            (50.0 + 10.0 * len(text), float(y + 20)),
            (50.0, float(y + 20)),
        ),
        confidence=1.0,
    )


def test_ingest_image_gate_rejects_empty_recognition(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "blank.png"
    _make_png(p, size=(400, 400), dpi=300)
    fake = FakeOCR(lines=())
    with pytest.raises(NotADocumentError):
        ingest_image(p, ocr=fake)


def test_ingest_image_gate_rejects_one_pixel(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "one_pixel.png"
    _make_png(p, size=(1, 1), dpi=72)
    fake = FakeOCR(lines=())
    with pytest.raises(NotADocumentError):
        ingest_image(p, ocr=fake)


def test_ingest_image_gate_rejects_too_short_text(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "shortish.png"
    _make_png(p, size=(400, 400), dpi=300)
    # Две коротких строки — недобираем и по числу строк, и по символам.
    fake = FakeOCR(lines=(_bbox_for_line("да", 40), _bbox_for_line("нет", 80)))
    with pytest.raises(NotADocumentError):
        ingest_image(p, ocr=fake)


def test_ingest_image_gate_passes_real_document(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "doc.jpg"
    _make_jpeg(p, size=(800, 1100), dpi=300)
    fake = FakeOCR(
        lines=(
            _bbox_for_line("Договор поставки товара № 42", 100),
            _bbox_for_line("ИНН 7707083893 КПП 770701001", 200),
            _bbox_for_line("Стороны: ООО Ромашка и ИП Иванов", 300),
        )
    )
    document = ingest_image(p, ocr=fake)
    assert document.fmt == "pdf"
    assert document.path.endswith("doc.jpg")
    assert document.meta["image_source"] == "doc.jpg"
    assert document.meta["image_suffix"] == ".jpg"
    assert document.meta["image_format"] == "JPEG"
    assert document.meta["image_width"] == "800"
    assert document.meta["image_height"] == "1100"
    assert document.meta["image_dpi_x"] == "300"
    assert document.meta["image_orientation"] == "1"
    # Все сегменты — из OCR-ветки (см. `Segment.origin`).
    assert all(seg.origin == "ocr" for seg in document.segments)
    joined = " ".join(seg.text for seg in document.segments)
    assert "7707083893" in joined


def test_ingest_image_requires_ocr(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "no_ocr.png"
    _make_png(p, size=(400, 400), dpi=300)
    with pytest.raises(ValueError, match="OCR-провайдер обязателен"):
        ingest_image(p, ocr=None)


def test_ingest_image_survives_rgba(tmp_path: pathlib.Path) -> None:
    """RGBA-PNG с альфой не должен падать при конвертации в PDF (граблья
    `get_pixmap alpha=False → чёрный фон`)."""
    p = tmp_path / "with_alpha.png"
    image = Image.new("RGBA", (600, 400), (255, 255, 255, 0))
    image.save(str(p), format="PNG", dpi=(300, 300))
    fake = FakeOCR(
        lines=(
            _bbox_for_line("Заявление на регистрацию", 40),
            _bbox_for_line("Реквизиты сторон договора", 100),
            _bbox_for_line("Приложение № 1 к контракту", 200),
        )
    )
    document = ingest_image(p, ocr=fake)
    assert document.meta["image_mode"] == "RGBA"
    assert len(document.segments) >= 3


def test_probe_reads_orientation_from_exif(tmp_path: pathlib.Path) -> None:
    """Симулируем EXIF `Orientation=6` через ручной exif-байтпак Pillow."""
    p = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (200, 100), (255, 255, 255))
    exif = image.getexif()
    exif[0x0112] = 6  # Orientation
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif.tobytes(), dpi=(150, 150))
    p.write_bytes(buf.getvalue())
    meta = probe(p)
    assert meta.orientation == 6
