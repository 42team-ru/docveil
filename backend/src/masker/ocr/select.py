"""Выбор поставщика OCR: аргумент → окружение → YAML → дефолт.

По аналогии с ``masker.llm``. Порядок приоритетов, от сильного к слабому:

  1. явный аргумент ``select_ocr("tesseract")``;
  2. переменная окружения ``MASKER_OCR``;
  3. ``ocr.provider`` из YAML-конфига проекта;
  4. дефолт ``tesseract`` — самый быстрый и с лучшим CER/WER на нашем корпусе.

Если провайдер не был задан ни одним из первых трёх способов и дефолтный
движок недоступен (нет системного бинаря tesseract), автоматически
пробуется ``rapid``. Фоллбек срабатывает **только** для неявного выбора:
при явном ``MASKER_OCR=tesseract`` ошибка поднимается как есть, иначе
явное указание человека было бы тихо проигнорировано.

``fake`` — CI-провайдер без весов и сети. В воротах он берётся из
`masker.yaml` (`ocr.provider: fake`), а не из дефолта кода: `make gate`
обязан работать одинаково на любой машине, независимо от того, установлен
ли там системный tesseract.

Отсутствие пакета движка поднимается как :class:`OCRError` на этапе
создания провайдера, а не при первом ``recognize``: вызов падает до
открытия PDF, и сразу понятно, что чинить.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from masker.config import project_section
from masker.ocr.fake import FakeOCR
from masker.ocr.provider import OCRError, OCRProvider

#: Имя переменной окружения, из которой читается провайдер по умолчанию.
ENV_VAR: str = "MASKER_OCR"

_DEFAULT: str = "tesseract"
_FALLBACK: str = "rapid"


def select_ocr(name: str | None = None) -> OCRProvider:
    """Вернуть провайдер OCR по аргументу, ``MASKER_OCR``, YAML или дефолту.

    Имена нормализуются к нижнему регистру; неизвестное имя — ``OCRError``
    со списком доступных, а не молчаливый откат на ``fake``: опечатка в
    переменной окружения иначе тихо отключила бы настоящий OCR.
    """
    configured_name = project_section("ocr").get("provider", _DEFAULT)
    if not isinstance(configured_name, str):
        raise ValueError("ocr.provider в YAML-конфиге должен быть строкой")

    # Фоллбек уместен только тогда, когда провайдера не выбирал человек:
    # ни аргументом, ни окружением, ни строкой в YAML. Иначе подмена
    # выбранного движка на другой пройдёт незаметно.
    explicit = name is not None or ENV_VAR in os.environ or configured_name != _DEFAULT
    selected_name = name
    if selected_name is None:
        selected_name = os.environ.get(ENV_VAR, configured_name)
    key = selected_name.strip().casefold()

    factory = _REGISTRY.get(key)
    if factory is None:
        available = ", ".join(sorted(_REGISTRY))
        raise OCRError(
            f"неизвестный OCR-провайдер {key!r}; доступные: {available}. "
            f"Задать через {ENV_VAR}=<имя>, ocr.provider в YAML или аргументом select_ocr(name=...)"
        )
    try:
        return factory()
    except OCRError:
        if not explicit and _FALLBACK and key != _FALLBACK:
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
