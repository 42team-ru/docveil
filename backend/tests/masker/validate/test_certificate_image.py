"""Пункт сертификата `image_metadata_stripped` (план feat-image-ingest, инвариант 1)."""

from __future__ import annotations

import io
import pathlib

from PIL import Image

from masker.validate.certificate import (
    _check_image_metadata_stripped,
    _image_exif_findings,
)


def _clean_jpeg(path: pathlib.Path, size: tuple[int, int] = (300, 200), dpi: int = 300) -> None:
    """JPEG без посторонних EXIF — только DPI."""
    Image.new("RGB", size, (255, 255, 255)).save(str(path), format="JPEG", dpi=(dpi, dpi))


def _jpeg_with_software_tag(path: pathlib.Path) -> None:
    """JPEG с EXIF `Software` — типичная утечка происхождения файла."""
    image = Image.new("RGB", (100, 100), (255, 255, 255))
    exif = image.getexif()
    exif[0x0131] = "Adobe Photoshop 2024"  # Software
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif.tobytes(), dpi=(200, 200))
    path.write_bytes(buf.getvalue())


def test_check_passes_on_clean_jpeg(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "clean.jpg"
    _clean_jpeg(p)
    check = _check_image_metadata_stripped([p])
    assert check.ok, check.detail
    assert check.name == "image_metadata_stripped"
    # `detail` содержит явное указание количества проверенных картинок.
    assert "1" in check.detail


def test_check_flags_software_tag(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "leaky.jpg"
    _jpeg_with_software_tag(p)
    check = _check_image_metadata_stripped([p])
    assert not check.ok
    assert "Software" in check.detail or "Photoshop" in check.detail


def test_check_skipped_when_no_images(tmp_path: pathlib.Path) -> None:
    check = _check_image_metadata_stripped([])
    assert check.ok
    assert "не применимо" in check.detail


def test_image_exif_findings_flags_icc_profile(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "with_icc.png"
    image = Image.new("RGB", (100, 100), (255, 255, 255))
    # sRGB ICC-профиль (256 байт условно) — Pillow сохраняет его в PNG-`iCCP`.
    icc_bytes = b"\x00\x00\x00\x84acspAPPL\x00\x00\x00\x00" + b"\x00" * 100
    image.save(str(p), format="PNG", dpi=(200, 200), icc_profile=icc_bytes)
    findings = _image_exif_findings(p)
    assert any("ICC" in item for item in findings), findings
