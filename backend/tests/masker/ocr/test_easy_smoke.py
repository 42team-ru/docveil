"""Smoke-тест EasyOCRProvider на синтетическом PNG с русским текстом.

Тест помечен ``@pytest.mark.ocr`` — исключён из ``make gate`` (нужен
настоящий движок и веса в ``~/.EasyOCR/model/``). Запуск вручную:

    MASKER_OCR=easy pytest -m ocr

или через:

    pytest tests/masker/ocr/test_easy_smoke.py
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

pytestmark = pytest.mark.ocr


def _easyocr_available() -> bool:
    return importlib.util.find_spec("easyocr") is not None


@pytest.fixture(scope="module")
def provider() -> object:
    if not _easyocr_available():
        pytest.skip("easyocr не установлен, запустите `uv sync --extra ocr`")
    from masker.ocr.easy import EasyOCRProvider

    return EasyOCRProvider()


@pytest.fixture(scope="module")
def russian_text_image() -> np.ndarray:
    """300-dpi PNG 500×120 px с текстом «Иванов ИНН 7707083893»."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        pytest.skip("Pillow не установлен")

    img = Image.new("RGB", (500, 120), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    draw.text((10, 40), "Иванов ИНН 7707083893", fill=(0, 0, 0), font=font)
    # PIL RGB → numpy BGR (стандарт ingest, PyMuPDF pixmap отдаёт BGR)
    arr = np.array(img)
    return arr[:, :, ::-1].copy()


def test_easy_recognize_finds_inn(provider: object, russian_text_image: np.ndarray) -> None:
    """EasyOCR находит ИНН 7707083893 в синтетическом изображении с высоким confidence."""
    from masker.ocr.easy import EasyOCRProvider
    from masker.ocr.provider import OCRLine

    assert isinstance(provider, EasyOCRProvider)
    lines: tuple[OCRLine, ...] = provider.recognize(russian_text_image, dpi=300)

    assert len(lines) > 0, "EasyOCR не распознал ни одной строки"

    full_text = " ".join(line.text for line in lines)
    assert "7707083893" in full_text, (
        f"ИНН 7707083893 не найден в распознанном тексте: {full_text!r}"
    )

    inn_lines = [ln for ln in lines if "7707083893" in ln.text]
    assert any(ln.confidence >= 0.85 for ln in inn_lines), (
        f"ИНН найден, но confidence < 0.85: {[ln.confidence for ln in inn_lines]}"
    )


def test_easy_recognize_returns_valid_geometry(
    provider: object, russian_text_image: np.ndarray
) -> None:
    """Каждый OCRLine имеет валидный bbox (x0 < x1, y0 < y1) и polygon из 4 точек."""
    from masker.ocr.easy import EasyOCRProvider
    from masker.ocr.provider import OCRLine

    assert isinstance(provider, EasyOCRProvider)
    lines: tuple[OCRLine, ...] = provider.recognize(russian_text_image, dpi=300)

    for line in lines:
        x0, y0, x1, y1 = line.bbox
        assert x0 < x1, f"bbox x0 >= x1: {line.bbox}"
        assert y0 < y1, f"bbox y0 >= y1: {line.bbox}"
        assert len(line.polygon) == 4, f"polygon должен содержать 4 точки: {line.polygon}"
        assert 0.0 <= line.confidence <= 1.0, f"confidence вне [0,1]: {line.confidence}"
        # bbox должен покрывать все точки полигона (axis-aligned из тех же координат)
        for px, py in line.polygon:
            assert x0 <= px <= x1, f"точка {px} полигона вне bbox {line.bbox}"
            assert y0 <= py <= y1, f"точка {py} полигона вне bbox {line.bbox}"


def test_easy_recognize_deterministic(provider: object, russian_text_image: np.ndarray) -> None:
    """Два одинаковых вызова дают одинаковый результат (детерминизм на CPU)."""
    from masker.ocr.easy import EasyOCRProvider
    from masker.ocr.provider import OCRLine

    assert isinstance(provider, EasyOCRProvider)
    lines1: tuple[OCRLine, ...] = provider.recognize(russian_text_image, dpi=300)
    lines2: tuple[OCRLine, ...] = provider.recognize(russian_text_image, dpi=300)

    assert len(lines1) == len(lines2), "разное число строк при повторном вызове"
    for i, (a, b) in enumerate(zip(lines1, lines2, strict=True)):
        assert a.text == b.text, f"строка {i}: разный текст {a.text!r} vs {b.text!r}"


def test_easy_rejects_wrong_shape(provider: object) -> None:
    """Неверная форма/тип изображения — ValueError, а не молчаливый пустой tuple."""
    from masker.ocr.easy import EasyOCRProvider

    assert isinstance(provider, EasyOCRProvider)
    grayscale = np.zeros((100, 100), dtype=np.uint8)
    with pytest.raises(ValueError):
        provider.recognize(grayscale, dpi=300)

    wrong_dtype = np.zeros((100, 100, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        provider.recognize(wrong_dtype, dpi=300)
