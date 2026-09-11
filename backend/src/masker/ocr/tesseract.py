"""Tesseract-провайдер OCR через pytesseract.

Требует системный tesseract-ocr и пакет pytesseract:
    sudo apt install tesseract-ocr tesseract-ocr-rus
    uv pip install --python .venv/bin/python pytesseract

Включить через ``MASKER_OCR=tesseract``.
"""

from __future__ import annotations

import re
import threading
from typing import Any

import numpy as np

from masker.ocr.provider import OCRError, OCRLine

# Визуально неотличимые латинские буквы → кириллические эквиваленты.
# Tesseract с lang=rus+eng иногда выбирает Latin-кодпоинт вместо Cyrillic
# для строчных/прописных букв, внешне идентичных (A/А, E/Е, B/В и т.д.).
# Это ломает NER: паттерн «[А-ЯЁ]\.» не матчит латинскую «E.».
_UPPER_TABLE = str.maketrans(
    "ABCEHKMOPTXY",
    "АВСЕНКМОРТХУ",
)
_FULL_TABLE = str.maketrans(
    "ABCEHKMOPTXYaceopx",
    "АВСЕНКМОРТХУасеорх",
)
_HAS_CYRILLIC = re.compile(r"[А-ЯЁа-яё]")


def _fix_homoglyphs(word: str) -> str:
    """Заменить латинские омоглифы на кириллицу в контексте русского слова.

    Прописные заменяются безусловно. Строчные — только если слово уже
    содержит кириллицу: так не ломаются латинские URL и аббревиатуры.
    """
    if _HAS_CYRILLIC.search(word):
        return word.translate(_FULL_TABLE)
    return word.translate(_UPPER_TABLE)


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
    """Преобразовать вывод image_to_data в строчные OCRLine.

    pytesseract возвращает слова (level=5) с полями block_num/par_num/line_num.
    Группируем слова по (block_num, par_num, line_num) в одну строку, чтобы
    NER получал «Пеков Е.В.» как единый сегмент, а не три разрозненных слова.
    Порядок строк — порядок их первого слова в выводе Tesseract.
    """
    from collections import OrderedDict

    levels: list[int] = data["level"]
    texts: list[str] = data["text"]
    confs: list[int | float] = data["conf"]
    lefts: list[int] = data["left"]
    tops: list[int] = data["top"]
    widths: list[int] = data["width"]
    heights: list[int] = data["height"]
    block_nums: list[int] = data["block_num"]
    par_nums: list[int] = data["par_num"]
    line_nums: list[int] = data["line_num"]

    # OrderedDict сохраняет порядок первого появления ключа.
    groups: OrderedDict[
        tuple[int, int, int],
        list[tuple[float, float, float, float, float]],  # x0, y0, x1, y1, conf
    ] = OrderedDict()
    group_words: OrderedDict[tuple[int, int, int], list[str]] = OrderedDict()

    for i, (level, text, conf) in enumerate(zip(levels, texts, confs, strict=True)):
        if level != 5:
            continue
        if int(conf) < 0 or not str(text).strip():
            continue

        key = (block_nums[i], par_nums[i], line_nums[i])
        x0 = float(lefts[i])
        y0 = float(tops[i])
        x1 = float(lefts[i] + widths[i])
        y1 = float(tops[i] + heights[i])
        c = max(0.0, min(1.0, float(conf) / 100.0))

        if key not in groups:
            groups[key] = []
            group_words[key] = []
        groups[key].append((x0, y0, x1, y1, c))
        group_words[key].append(_fix_homoglyphs(str(text)))

    result: list[OCRLine] = []
    for key, word_boxes in groups.items():
        words = group_words[key]
        bx0 = min(b[0] for b in word_boxes)
        by0 = min(b[1] for b in word_boxes)
        bx1 = max(b[2] for b in word_boxes)
        by1 = max(b[3] for b in word_boxes)
        conf_val = min(b[4] for b in word_boxes)
        polygon: tuple[
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
        ] = ((bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1))
        result.append(
            OCRLine(
                text=" ".join(words),
                bbox=(bx0, by0, bx1, by1),
                polygon=polygon,
                confidence=conf_val,
                order=len(result),
            )
        )

    return tuple(result)
