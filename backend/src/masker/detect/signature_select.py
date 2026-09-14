"""Выбор детектора подписей по имени/переменной окружения (S1).

По аналогии с :mod:`masker.ocr.select`: имя провайдера — либо явное
(``select_signature("detr")``), либо из ``MASKER_SIGNATURE``, либо дефолт
``cv``. Дефолт — ``cv`` (не ``fake``!), потому что CV не требует ни
внешних весов, ни сети: он должен работать в ``make gate`` из коробки на
любой машине с установленным ``opencv-python``.

Отсутствие пакета движка (``transformers``/``torch`` для ``detr``)
поднимается как :class:`SignatureDetectionError` на этапе создания
провайдера, а не при первом ``detect``: пользователь сразу видит, что
чинить, не открывая PDF.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from masker.detect.signature_detector import (
    FakeSignatureDetector,
    SignatureCVDetector,
    SignatureDetectionError,
    SignatureDetector,
    SignatureHybridDetector,
)

#: Имя переменной окружения, из которой читается провайдер по умолчанию.
ENV_VAR: str = "MASKER_SIGNATURE"

_DEFAULT: str = "cv"


def select_signature(name: str | None = None) -> SignatureDetector:
    """Вернуть детектор подписей по имени/``MASKER_SIGNATURE``/дефолту ``cv``.

    Имена нормализуются к нижнему регистру; неизвестное имя —
    ``SignatureDetectionError`` со списком доступных имён (не молчаливый
    фолбэк на ``cv``, иначе опечатка в переменной окружения тихо
    отключит DETR).
    """
    key = (name if name is not None else os.environ.get(ENV_VAR, _DEFAULT)).strip().casefold()
    factory = _REGISTRY.get(key)
    if factory is None:
        available = ", ".join(sorted(_REGISTRY))
        raise SignatureDetectionError(
            f"неизвестный детектор подписей {key!r}; доступные: {available}. "
            f"Задать через {ENV_VAR}=<имя> или аргументом select_signature(name=...)"
        )
    return factory()


def _make_cv() -> SignatureDetector:
    return SignatureCVDetector()


def _make_detr() -> SignatureDetector:
    """Гибрид DETR ∪ CV. Ленивый импорт ``transformers`` — внутри
    :class:`SignatureDETRDetector._load`, чтобы установка без extra
    ``signature`` не роняла процесс на импорте модуля.

    Возможные ошибки при отсутствии пакета — :class:`SignatureDetectionError`
    с install-hint, а не сырой :class:`ModuleNotFoundError`.
    """
    provider: SignatureDetector = SignatureHybridDetector()
    return provider


def _make_fake() -> SignatureDetector:
    return FakeSignatureDetector()


#: Реестр фабрик — единственное место, где перечислены имена. Расширяется
#: добавлением строки, снаружи не изменяется.
_REGISTRY: dict[str, Callable[[], SignatureDetector]] = {
    "cv": _make_cv,
    "detr": _make_detr,
    "fake": _make_fake,
}


__all__ = ["ENV_VAR", "select_signature"]
