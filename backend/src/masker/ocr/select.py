"""Выбор поставщика OCR по имени/переменной окружения.

По аналогии с ``masker.llm``: имя провайдера — либо явное (``select_ocr
("rapid")``), либо из ``MASKER_OCR``, либо дефолт ``tesseract``.

Цепочка приоритетов при явно не заданном провайдере:
  1. ``tesseract`` — дефолт (быстрый, лучший CER/WER на тестовом корпусе).
  2. ``rapid`` — автоматический фоллбек, если системный tesseract не установлен.

Фоллбек срабатывает **только** когда провайдер не задан ни аргументом, ни
переменной окружения ``MASKER_OCR``. При явном ``MASKER_OCR=tesseract``
или ``select_ocr("tesseract")`` ошибка поднимается без фоллбека — иначе
явный выбор будет тихо проигнорирован.

``fake`` — CI-провайдер без весов и сети; ставить ``MASKER_OCR=fake`` в
окружении ворот (gate.sh), если системный tesseract недоступен в CI.

Отсутствие пакета движка поднимается как :class:`OCRError` на этапе
создания провайдера, а не при первом ``recognize``.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from masker.ocr.fake import FakeOCR
from masker.ocr.provider import OCRError, OCRProvider

#: Имя переменной окружения, из которой читается провайдер по умолчанию.
ENV_VAR: str = "MASKER_OCR"

_DEFAULT: str = "tesseract"
_FALLBACK: str = "rapid"


def select_ocr(name: str | None = None) -> OCRProvider:
    """Вернуть провайдер OCR по имени (``name``) или ``MASKER_OCR`` или дефолту ``tesseract``.

    Имена нормализуются к нижнему регистру; неизвестное имя — ``OCRError``
    со списком доступных имён.

    Если имя не задано ни явно, ни через ``MASKER_OCR``, и дефолтный
    провайдер недоступен (нет системного бинаря) — автоматически
    пробуется фоллбек ``rapid``.
    """
    use_fallback = name is None and ENV_VAR not in os.environ
    key = (name if name is not None else os.environ.get(ENV_VAR, _DEFAULT)).strip().casefold()
    factory = _REGISTRY.get(key)
    if factory is None:
        available = ", ".join(sorted(_REGISTRY))
        raise OCRError(
            f"неизвестный OCR-провайдер {key!r}; доступные: {available}. "
            f"Задать через {ENV_VAR}=<имя> или аргументом select_ocr(name=...)"
        )
    try:
        return factory()
    except OCRError:
        if use_fallback and _FALLBACK and key != _FALLBACK:
            fallback_factory = _REGISTRY.get(_FALLBACK)
            if fallback_factory is not None:
                return fallback_factory()
        raise


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


def _make_paddle_vl() -> OCRProvider:
    from masker.ocr.paddle import PaddleVLProvider

    provider: OCRProvider = PaddleVLProvider()
    return provider


def _make_rapid() -> OCRProvider:
    """Ленивая инициализация RapidOCR. Модуль импортируется здесь, чтобы
    установка без extra ``ocr`` не падала на импорте."""
    try:
        from masker.ocr.rapid import RapidOCRProvider
    except ImportError as error:
        raise OCRError(
            "провайдер 'rapid' требует rapidocr-onnxruntime: "
            "`uv pip install --python .venv/bin/python rapidocr-onnxruntime`"
        ) from error
    provider: OCRProvider = RapidOCRProvider()
    return provider


def _make_easy() -> OCRProvider:
    """Ленивая инициализация EasyOCR. Модуль импортируется здесь, чтобы
    установка без extra ``ocr`` не падала на импорте (easyocr тянет torch)."""
    try:
        from masker.ocr.easy import EasyOCRProvider
    except ImportError as error:
        raise OCRError(
            "провайдер 'easy' требует easyocr: "
            "`uv pip install --python .venv/bin/python easyocr>=1.7`"
        ) from error
    provider: OCRProvider = EasyOCRProvider()
    return provider


#: Реестр фабрик провайдеров — единственное место, где перечислены имена
#: и их реализации. Расширяется добавлением строки, снаружи не изменяется.
_REGISTRY: dict[str, Callable[[], OCRProvider]] = {
    "easy": _make_easy,
    "fake": _make_fake,
    "paddle": _make_paddle,
    "paddle_vl": _make_paddle_vl,
    "rapid": _make_rapid,
    "tesseract": _make_tesseract,
}
