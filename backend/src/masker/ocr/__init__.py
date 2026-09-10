"""Слой OCR: единственная точка, где живут провайдеры распознавания.

По аналогии с ``masker.llm``: снаружи из слоя торчат только контракты
(:class:`OCRProvider`, :class:`OCRLine`, :class:`OCRError`) и селектор
:func:`select_ocr`. Никто вне ``masker.ocr`` не имеет права импортировать
``paddleocr``/``pytesseract`` напрямую — это ловится тестом
``tests/masker/ocr/test_layer_boundary.py``. Смена OCR-движка не должна
трогать логику узлов графа (та же гарантия, что для LLM — требование
заказчика №6, ``AGENTS.md``).
"""

from __future__ import annotations

from masker.ocr.provider import OCRError, OCRLine, OCRProvider
from masker.ocr.select import select_ocr

__all__ = ["OCRError", "OCRLine", "OCRProvider", "select_ocr"]
