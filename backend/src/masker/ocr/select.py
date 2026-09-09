"""Выбор поставщика OCR по имени/переменной окружения.

По аналогии с ``masker.llm``: имя провайдера — либо явное (``select_ocr
("paddle")``), либо из ``MASKER_OCR``, либо дефолт ``fake``. Дефолт
именно ``fake``, а не ``paddle``: `make gate` в CI обязан работать без
весов и сети (инвариант «не тащить веса на импорте», см. план
``docs/plans/T2.3-ocr-paddleocr.md``).

Отсутствие пакета движка (например, `paddleocr` не установлен, т.к.
пользователь не поставил extra `ocr`) поднимается как :class:`OCRError`
на этапе создания провайдера, а не при первом ``recognize``. Так вызов
падает сразу, до открытия PDF, — понятно, что чинить (``pip install
triema-masker[ocr]``).
"""

from __future__ import annotations

import os
from collections.abc import Callable

from masker.ocr.fake import FakeOCR
from masker.ocr.provider import OCRError, OCRProvider

#: Имя переменной окружения, из которой читается провайдер по умолчанию.
ENV_VAR: str = "MASKER_OCR"

_DEFAULT: str = "fake"


def select_ocr(name: str | None = None) -> OCRProvider:
    """Вернуть провайдер OCR по имени (``name``) или ``MASKER_OCR`` или дефолту ``fake``.

    Имена нормализуются к нижнему регистру; неизвестное имя — ``OCRError``
    со списком доступных имён, а не молчаливый фолбэк на ``fake`` (иначе
    опечатка в переменной окружения тихо отключит настоящий OCR).
    """
    key = (name if name is not None else os.environ.get(ENV_VAR, _DEFAULT)).strip().casefold()
    factory = _REGISTRY.get(key)
    if factory is None:
        available = ", ".join(sorted(_REGISTRY))
        raise OCRError(
            f"неизвестный OCR-провайдер {key!r}; доступные: {available}. "
            f"Задать через {ENV_VAR}=<имя> или аргументом select_ocr(name=...)"
        )
    return factory()


def _make_fake() -> OCRProvider:
    return FakeOCR()


def _make_paddle() -> OCRProvider:
    """Ленивая инициализация PaddleOCR. Модуль импортируется здесь, а не в
    верхней шапке, чтобы установка без extra ``ocr`` не падала на импорте."""
    try:
        from masker.ocr.paddle import PaddleOCRProvider
    except ImportError as error:  # paddleocr не установлен
        raise OCRError(
            "провайдер 'paddle' требует установки extra 'ocr': "
            "`pip install triema-masker[ocr]` или `uv sync --extra ocr`"
        ) from error
    provider: OCRProvider = PaddleOCRProvider()
    return provider


def _make_tesseract() -> OCRProvider:
    try:
        from masker.ocr.tesseract import TesseractOCRProvider
    except ImportError as error:  # pytesseract/бинарь tesseract не найдены
        raise OCRError(
            "провайдер 'tesseract' требует установки pytesseract и системного tesseract"
        ) from error
    provider: OCRProvider = TesseractOCRProvider()
    return provider


#: Реестр фабрик провайдеров — единственное место, где перечислены имена
#: и их реализации. Расширяется добавлением строки, снаружи не изменяется.
_REGISTRY: dict[str, Callable[[], OCRProvider]] = {
    "fake": _make_fake,
    "paddle": _make_paddle,
    "tesseract": _make_tesseract,
}
