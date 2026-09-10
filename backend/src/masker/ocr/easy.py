"""EasyOCR-провайдер (JaidedAI EasyOCR поверх PyTorch).

Альтернатива ``RapidOCRProvider`` для случаев, когда RapidOCR путает
разрывы слов или мелкие цифры на плохих сканах. EasyOCR медленнее
(PyTorch на CPU против ONNX-инференса у RapidOCR), но иногда точнее на
русскоязычных сканах — предметный выбор делает пользователь через
``MASKER_OCR=easy``.

Веса скачиваются в ``~/.EasyOCR/model/`` при первом прогоне (~64 MB
детектор CRAFT + ~30 MB рекогнайзер для русского). В офлайн-среде их
надо предзагрузить один раз.

GPU включается флагом ``MASKER_OCR_GPU=1`` — по умолчанию CPU-режим,
чтобы не требовать CUDA на dev-машинах.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import numpy as np

from masker.ocr.provider import OCRError, OCRLine

_ENV_GPU: str = "MASKER_OCR_GPU"
_LANGUAGES: tuple[str, ...] = ("ru", "en")


class EasyOCRProvider:
    """OCR-провайдер поверх ``easyocr.Reader``.

    Ленивая инициализация модели: тяжёлые импорты и загрузка весов
    происходят при первом ``recognize``, а не при создании провайдера
    — это симметрично паттерну RapidOCR и позволяет ``select_ocr("easy")``
    работать без прогрева.
    """

    def __init__(self) -> None:
        try:
            import easyocr as _  # noqa: F401
        except ImportError as error:
            raise OCRError(
                "провайдер 'easy' требует easyocr: "
                "`uv pip install --python .venv/bin/python easyocr>=1.7`"
            ) from error
        self._reader: Any | None = None
        self._lock = threading.Lock()

    def _get_reader(self) -> Any:
        if self._reader is None:
            with self._lock:
                if self._reader is None:
                    self._reader = _load_easyocr_reader()
        return self._reader

    def recognize(self, image: np.ndarray, dpi: int) -> tuple[OCRLine, ...]:
        del dpi  # EasyOCR не калибрует пороги по DPI, масштаб задаёт ingest
        if image.dtype != np.uint8:
            raise ValueError(f"EasyOCRProvider ожидает uint8, получил dtype={image.dtype!r}")
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError(
                f"EasyOCRProvider ожидает изображение формы (H, W, 3), получил {image.shape!r}"
            )
        # Ingest готовит BGR (стандарт OpenCV/PyMuPDF pixmap), EasyOCR ждёт RGB.
        # ``[..., ::-1]`` даёт view без копии, ``ascontiguousarray`` — copy при
        # необходимости, чтобы под капотом numpy/torch не паниковали.
        rgb = np.ascontiguousarray(image[..., ::-1])
        reader = self._get_reader()
        try:
            result = reader.readtext(rgb, detail=1, paragraph=False)
        except Exception as exc:  # движок EasyOCR не декларирует исключения
            raise OCRError(f"EasyOCR не смог распознать изображение: {exc}") from exc
        if not result:
            return ()
        return _parse_results(result)


def _load_easyocr_reader() -> Any:
    """Создать ``easyocr.Reader`` с русским+английским словарём и GPU-флагом из env."""
    import easyocr

    use_gpu = os.environ.get(_ENV_GPU, "").strip() in {"1", "true", "TRUE", "yes"}
    try:
        return easyocr.Reader(list(_LANGUAGES), gpu=use_gpu, verbose=False)
    except Exception as exc:
        raise OCRError(f"не удалось инициализировать EasyOCR: {exc}") from exc


def _parse_results(result: list[Any]) -> tuple[OCRLine, ...]:
    """Преобразовать список ``(bbox_4pts, text, conf)`` в ``tuple[OCRLine, ...]``.

    EasyOCR возвращает полигон в порядке TL → TR → BR → BL — тот же обход
    по часовой стрелке от левого верхнего, что и у RapidOCR/PaddleOCR.
    ``bbox`` считаем axis-aligned min/max по всем углам — так безопаснее к
    возможному вращению страницы.
    """
    lines: list[OCRLine] = []
    for item in result:
        polygon_raw, text, conf = item
        pts = np.asarray(polygon_raw, dtype=float)  # (4, 2)
        x0 = float(pts[:, 0].min())
        y0 = float(pts[:, 1].min())
        x1 = float(pts[:, 0].max())
        y1 = float(pts[:, 1].max())
        polygon: tuple[
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
        ] = (
            (float(pts[0, 0]), float(pts[0, 1])),
            (float(pts[1, 0]), float(pts[1, 1])),
            (float(pts[2, 0]), float(pts[2, 1])),
            (float(pts[3, 0]), float(pts[3, 1])),
        )
        lines.append(
            OCRLine(
                text=str(text),
                bbox=(x0, y0, x1, y1),
                polygon=polygon,
                confidence=float(conf),
                order=len(lines),
            )
        )
    return tuple(lines)
