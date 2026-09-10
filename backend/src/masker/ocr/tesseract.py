"""Tesseract-провайдер OCR через pytesseract.

Требует системный tesseract-ocr и пакет pytesseract:
    sudo apt install tesseract-ocr tesseract-ocr-rus
    uv pip install --python .venv/bin/python pytesseract

Включить через ``MASKER_OCR=tesseract``.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from masker.ocr.provider import OCRError, OCRLine


class TesseractOCRProvider:
    """OCR поверх Tesseract (pytesseract → subprocess tesseract-ocr)."""

    def __init__(self) -> None:
        try:
            import pytesseract as _  # noqa: F401
        except ImportError as error:
            raise OCRError(
                "провайдер 'tesseract' требует pytesseract: "
                "`uv pip install --python .venv/bin/python pytesseract` "
                "и системный tesseract-ocr (sudo apt install tesseract-ocr tesseract-ocr-rus)"
            ) from error
        self._checked = False
        self._lock = threading.Lock()

    def _ensure_binary(self) -> None:
        if self._checked:
            return
        with self._lock:
            if self._checked:
                return
            import shutil

            if shutil.which("tesseract") is None:
                raise OCRError(
                    "бинарь tesseract не найден в PATH; "
                    "установите: sudo apt install tesseract-ocr tesseract-ocr-rus"
                )
            self._checked = True

    def recognize(self, image: np.ndarray, dpi: int) -> tuple[OCRLine, ...]:
        if image.ndim != 3 or image.shape[2] != 3:
            raise OCRError(f"ожидается изображение (H, W, 3) uint8, получено shape={image.shape}")

        self._ensure_binary()

        import pytesseract
        from PIL import Image
        from pytesseract import Output

        rgb = image[:, :, ::-1]
        pil_img = Image.fromarray(rgb.astype(np.uint8))

        try:
            data: dict[str, Any] = pytesseract.image_to_data(
                pil_img,
                lang="rus+eng",
                config="--oem 3 --psm 3",
                output_type=Output.DICT,
            )
        except Exception as exc:
            raise OCRError(f"Tesseract не смог распознать изображение: {exc}") from exc

        return _parse_results(data)


def _parse_results(data: dict[str, Any]) -> tuple[OCRLine, ...]:
    """Преобразовать вывод image_to_data (уровень 5 = слово) в tuple[OCRLine, ...]."""
    lines: list[OCRLine] = []
    levels: list[int] = data["level"]
    texts: list[str] = data["text"]
    confs: list[int | float] = data["conf"]
    lefts: list[int] = data["left"]
    tops: list[int] = data["top"]
    widths: list[int] = data["width"]
    heights: list[int] = data["height"]

    for i, (level, text, conf) in enumerate(zip(levels, texts, confs, strict=True)):
        if level != 5:
            continue
        if int(conf) < 0 or not str(text).strip():
            continue

        x0 = float(lefts[i])
        y0 = float(tops[i])
        x1 = float(lefts[i] + widths[i])
        y1 = float(tops[i] + heights[i])

        polygon: tuple[
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
        ] = (
            (x0, y0),
            (x1, y0),
            (x1, y1),
            (x0, y1),
        )

        lines.append(
            OCRLine(
                text=str(text),
                bbox=(x0, y0, x1, y1),
                polygon=polygon,
                confidence=max(0.0, min(1.0, float(conf) / 100.0)),
                order=len(lines),
            )
        )

    return tuple(lines)
