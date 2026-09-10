"""Детерминированный OCR-провайдер для тестов и офлайн-ворот.

``FakeOCR`` не запускает ни одного движка и не тянет ``paddleocr``. Он
возвращает **предзаписанные** строки:

- глобальные строки, переданные в конструктор, — простой сценарий одной
  тестовой страницы;
- строки, привязанные к ключу ``(width, height)`` входного изображения,
  — сценарий смешанного PDF, где ingest хочет разные результаты OCR для
  разных страниц, а идентифицировать их не по счётчику вызовов, а по
  размеру рендера (детерминированно относительно порядка страниц);
- пустой список — валидная имитация «пустого скана», не исключение.

Файловое чтение (``*.ocr.json`` рядом с картинкой) сюда сознательно не
включено: фикстуры сканов появятся в O5, и подгрузка из файла — не
проблема провайдера, а фабрики фикстур. ``FakeOCR`` остаётся крошечным
и предсказуемым.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np

from masker.ocr.provider import OCRLine


class FakeOCR:
    """Возвращает заранее подготовленные строки без реального распознавания."""

    def __init__(
        self,
        lines: Iterable[OCRLine] = (),
        *,
        by_size: Mapping[tuple[int, int], Iterable[OCRLine]] | None = None,
    ) -> None:
        self._default: tuple[OCRLine, ...] = tuple(lines)
        self._by_size: dict[tuple[int, int], tuple[OCRLine, ...]] = {
            size: tuple(items) for size, items in (by_size or {}).items()
        }
        self.calls = 0

    def recognize(self, image: np.ndarray, dpi: int) -> tuple[OCRLine, ...]:
        del dpi  # fake не калибрует пороги, размер важнее
        self.calls += 1
        if image.ndim != 3 or image.shape[2] != 3:
            # Формат изображения — часть контракта: ingest готовит (H, W, 3)
            # BGR uint8, а не грейскейл; тестовая имитация должна поймать
            # регресс в ingest'е, а не молча вернуть пустой список.
            raise ValueError(
                f"FakeOCR ожидает изображение формы (H, W, 3), получил {image.shape!r}"
            )
        key = (int(image.shape[1]), int(image.shape[0]))
        if key in self._by_size:
            return self._by_size[key]
        return self._default
