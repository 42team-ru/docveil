"""Smoke-тест PaddleOCRProvider на синтетическом PNG с русским текстом.

Тест помечен ``@pytest.mark.ocr`` — исключён из ``make gate`` (нужен
настоящий движок и веса в ``~/.paddleocr/``). Запуск вручную:

    MASKER_OCR=paddle pytest -m ocr

или через:

    pytest tests/masker/ocr/test_paddle_smoke.py
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

pytestmark = pytest.mark.ocr


def _paddleocr_available() -> bool:
    return importlib.util.find_spec("paddleocr") is not None


@pytest.fixture(scope="module")
def provider() -> object:
    if not _paddleocr_available():
        pytest.skip("paddleocr не установлен, запустите `uv sync --extra ocr`")
    from masker.ocr.paddle import PaddleOCRProvider

    return PaddleOCRProvider()


@pytest.fixture(scope="module")
def russian_text_image() -> np.ndarray:
    """300-dpi PNG 400×100 px с текстом «Иванов ИНН 7707083893»."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        pytest.skip("Pillow не установлен")

    img = Image.new("RGB", (400, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Рисуем простым шрифтом без кириллики, если системный недоступен.
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
    draw.text((10, 35), "Иванов ИНН 7707083893", fill=(0, 0, 0), font=font)
    # PIL RGB → numpy BGR (OpenCV/Paddle convention)
    arr = np.array(img)
    return arr[:, :, ::-1].copy()


def test_paddle_recognize_finds_inn(provider: object, russian_text_image: np.ndarray) -> None:
    """PaddleOCR находит ИНН 7707083893 в синтетическом изображении."""
    from masker.ocr.paddle import PaddleOCRProvider
    from masker.ocr.provider import OCRLine

    assert isinstance(provider, PaddleOCRProvider)
    lines: tuple[OCRLine, ...] = provider.recognize(russian_text_image, dpi=300)

    assert len(lines) > 0, "PaddleOCR не распознал ни одной строки"

    full_text = " ".join(line.text for line in lines)
    assert "7707083893" in full_text, (
        f"ИНН 7707083893 не найден в распознанном тексте: {full_text!r}"
    )

    # Хотя бы одна строка содержит ИНН с confidence ≥ 0.9
    inn_lines = [ln for ln in lines if "7707083893" in ln.text]
    assert any(ln.confidence >= 0.9 for ln in inn_lines), (
        f"ИНН найден, но confidence < 0.9: {[ln.confidence for ln in inn_lines]}"
    )


def test_paddle_recognize_returns_valid_bbox(
    provider: object, russian_text_image: np.ndarray
) -> None:
    """Каждый OCRLine имеет валидный bbox (x0 < x1, y0 < y1) и polygon из 4 точек."""
    from masker.ocr.paddle import PaddleOCRProvider
    from masker.ocr.provider import OCRLine

    assert isinstance(provider, PaddleOCRProvider)
    lines: tuple[OCRLine, ...] = provider.recognize(russian_text_image, dpi=300)

    for line in lines:
        x0, y0, x1, y1 = line.bbox
        assert x0 < x1, f"bbox x0 >= x1: {line.bbox}"
        assert y0 < y1, f"bbox y0 >= y1: {line.bbox}"
        assert len(line.polygon) == 4, f"polygon должен содержать 4 точки: {line.polygon}"
        assert 0.0 <= line.confidence <= 1.0, f"confidence вне [0,1]: {line.confidence}"


def test_paddle_recognize_deterministic(provider: object, russian_text_image: np.ndarray) -> None:
    """Два одинаковых вызова дают одинаковый результат (детерминизм на CPU)."""
    from masker.ocr.paddle import PaddleOCRProvider
    from masker.ocr.provider import OCRLine

    assert isinstance(provider, PaddleOCRProvider)
    lines1: tuple[OCRLine, ...] = provider.recognize(russian_text_image, dpi=300)
    lines2: tuple[OCRLine, ...] = provider.recognize(russian_text_image, dpi=300)

    assert len(lines1) == len(lines2), "разное число строк при повторном вызове"
    for i, (a, b) in enumerate(zip(lines1, lines2, strict=True)):
        assert a.text == b.text, f"строка {i}: разный текст {a.text!r} vs {b.text!r}"
