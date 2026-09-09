"""PaddleOCR-провайдер (PP-OCR v5/v6 через PaddleOCR 3.x).

Ленивая инициализация модели: веса загружаются в `~/.paddleocr/` при
первом вызове :meth:`PaddleOCRProvider.recognize`. Последующие вызовы
используют уже загруженный объект (thread-safe через `threading.Lock`).

Все параметры конструктора зафиксированы в соответствии с планом O2:
  - `use_doc_orientation_classify=True` — автодескью 0/90/180/270°;
  - `use_textline_orientation=True` — определение ориентации строки;
  - `use_doc_unwarping=False` — геометрическая правка перспективы отключена
    (даёт нестабильные результаты на обычных офисных сканах).

:class:`PaddleVLProvider` — заглушка для будущего VL-движка; вся архитектура
слоя уже предусматривает его появление в отдельной итерации.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from masker.ocr.provider import OCRError, OCRLine


class PaddleOCRProvider:
    """PP-OCR провайдер поверх ``paddleocr>=3.0``."""

    def __init__(self) -> None:
        # Проверяем наличие пакета сразу — понятная ошибка вместо AttributeError
        # при первом recognize().
        try:
            import paddleocr as _  # noqa: F401
        except ImportError as error:
            raise OCRError(
                "провайдер 'paddle' требует установки extra 'ocr': "
                "`pip install triema-masker[ocr]` или `uv sync --extra ocr`"
            ) from error
        self._model: Any | None = None
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    self._model = _load_paddle_model()
        return self._model

    def recognize(self, image: np.ndarray, dpi: int) -> tuple[OCRLine, ...]:
        if image.ndim != 3 or image.shape[2] != 3:
            raise OCRError(
                f"ожидается изображение формы (H, W, 3) uint8, получено shape={image.shape}"
            )
        model = self._get_model()
        raw = model.predict(image)
        return _parse_results(raw)


def _load_paddle_model() -> Any:
    from paddleocr import PaddleOCR

    # Пробуем язык "ru" (модели PP-OCR v5/v6 поддерживают кириллицу);
    # если модель с таким именем не найдена — фолбэк на "cyrillic".
    for lang in ("ru", "cyrillic"):
        try:
            return PaddleOCR(
                lang=lang,
                use_doc_orientation_classify=True,
                use_textline_orientation=True,
                use_doc_unwarping=False,
            )
        except Exception:
            if lang == "cyrillic":
                raise
    # unreachable, но нужно для mypy
    raise OCRError("не удалось инициализировать PaddleOCR ни с ru, ни с cyrillic")


def _parse_results(raw: list[Any]) -> tuple[OCRLine, ...]:
    """Преобразовать список результатов ``predict()`` в ``tuple[OCRLine, ...]``."""
    lines: list[OCRLine] = []
    for res in raw:
        texts: list[str] = list(res["rec_texts"])
        scores: list[float] = list(res["rec_scores"])
        polys: Any = res["rec_polys"]  # shape (N, 4, 2), dtype int16 или float

        for i, text in enumerate(texts):
            pts = np.asarray(polys[i], dtype=float)  # (4, 2)
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
                    confidence=float(scores[i]),
                    order=len(lines),
                )
            )
    return tuple(lines)


class PaddleVLProvider:
    """Заглушка PaddleOCR-VL (SGLang 1.7B).

    Реализация отложена до отдельной итерации. Зарегистрирован в реестре
    провайдеров, чтобы структура кода не переворачивалась при появлении
    реального VL-движка.
    """

    def recognize(self, image: np.ndarray, dpi: int) -> tuple[OCRLine, ...]:
        raise OCRError("PaddleVL провайдер ещё не реализован")
