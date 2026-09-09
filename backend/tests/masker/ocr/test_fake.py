"""FakeOCR: детерминированный провайдер для юнит-тестов и офлайн-ворот."""

from __future__ import annotations

import numpy as np
import pytest

from masker.ocr import OCRLine
from masker.ocr.fake import FakeOCR


def _line(text: str) -> OCRLine:
    return OCRLine(
        text=text,
        bbox=(0.0, 0.0, 100.0, 20.0),
        polygon=((0.0, 0.0), (100.0, 0.0), (100.0, 20.0), (0.0, 20.0)),
        confidence=0.99,
    )


def _blank_image(width: int, height: int) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def test_default_lines_returned_and_calls_counted() -> None:
    provider = FakeOCR(lines=[_line("Иванов"), _line("ИНН 7707083893")])
    result = provider.recognize(_blank_image(200, 200), dpi=300)
    assert [line.text for line in result] == ["Иванов", "ИНН 7707083893"]
    assert provider.calls == 1


def test_empty_lines_are_valid_result() -> None:
    provider = FakeOCR()
    assert provider.recognize(_blank_image(200, 200), dpi=300) == ()


def test_size_specific_lines_beat_default() -> None:
    provider = FakeOCR(
        lines=[_line("default")],
        by_size={(300, 400): [_line("special")]},
    )
    result = provider.recognize(_blank_image(300, 400), dpi=300)
    assert [line.text for line in result] == ["special"]


def test_wrong_image_shape_raises() -> None:
    """Регресс защиты: grayscale-массив должен сразу упасть."""
    provider = FakeOCR()
    with pytest.raises(ValueError, match="ожидает изображение формы"):
        provider.recognize(np.zeros((100, 100), dtype=np.uint8), dpi=300)
