"""Экспорт одностраничного PDF-артефакта обратно в исходный формат картинки.

Финальный шаг для прогонов, начавшихся с картинки: рендер собрал
`masked_highlight.pdf`/`masked_black.pdf`, а на выходе пользователь хочет
получить `.jpg`/`.png`/`.tif` — не второй раз PDF. Конвертер держит
инварианты плана:

* **EXIF-стриппинг.** Сохраняем только `dpi` и `orientation` (последний
  всегда 1: `ImageOps.exif_transpose` физически повернул пиксели ещё на
  этапе ingest'а). Никаких `Software`/`Artist`/GPS/thumbnail/ICC.
* **Детерминизм.** JPEG-кодек Pillow при фиксированных
  `quality`/`optimize` побайтово одинаков (см. `_JPEG_QUALITY`).
* **Ровно одна страница.** Мы работаем с картинкой — PDF-артефакт по
  построению одностраничный. Если это не так — `ValueError`, а не
  «первая страница молча».
"""

from __future__ import annotations

import pathlib

import pymupdf
from PIL import Image

from masker.ingest.image_meta import ImageMetadata

#: Фиксированное качество JPEG — детерминизм важнее последнего процента веса.
_JPEG_QUALITY: int = 95
#: Pillow-имя формата по расширению. Ключи — те же `.suffix.lower()`, что и
#: в `SUPPORTED_SUFFIXES`; TIFF пишем без сжатия — так гарантированно
#: побайтово одинаково между прогонами.
_PILLOW_FORMAT_BY_SUFFIX: dict[str, str] = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".tif": "TIFF",
    ".tiff": "TIFF",
}


def _pixmap_to_image(pixmap: pymupdf.Pixmap) -> Image.Image:
    """Перегнать PyMuPDF-Pixmap в Pillow-Image (без альфы, RGB)."""
    if pixmap.alpha:
        # Плоский белый фон вместо прозрачности — картинки-документы не
        # держат альфу; PDF-рендер выдаёт RGB, но защищаемся на случай.
        no_alpha = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
        pixmap = no_alpha
    mode = "RGB"
    return Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)


def _save_kwargs(suffix: str, meta: ImageMetadata) -> dict[str, object]:
    """Аргументы для `Image.save`, детерминированные и без лишних метаданных.

    `dpi` пишется как `(x, y)`. EXIF не передаётся вовсе — тем самым не
    попадают Software/Artist/GPS/ICC-профиль исходной сцены.
    """
    fmt = _PILLOW_FORMAT_BY_SUFFIX[suffix]
    dpi = (meta.dpi_x, meta.dpi_y)
    if fmt == "JPEG":
        return {
            "format": "JPEG",
            "quality": _JPEG_QUALITY,
            "optimize": False,
            "dpi": dpi,
            # Явный отказ от сохранения EXIF/ICC/thumbnail:
            # Pillow не пишет их сам, если не передавать, но проговариваем.
        }
    if fmt == "PNG":
        return {
            "format": "PNG",
            "optimize": False,
            "dpi": dpi,
        }
    if fmt == "TIFF":
        return {
            "format": "TIFF",
            "dpi": dpi,
            "compression": "raw",
        }
    raise ValueError(f"неизвестный формат вывода картинки: {suffix!r}")


def pdf_to_image(
    pdf_path: pathlib.Path,
    meta: ImageMetadata,
    dst_path: pathlib.Path,
    *,
    target_suffix: str | None = None,
) -> None:
    """Собрать картинку из одностраничного PDF-артефакта.

    `target_suffix` — целевое расширение (`.jpg`/`.png`/`.tif`/`.tiff`);
    по умолчанию берётся из `meta.suffix` (исходный формат). DPI и
    ориентация в EXIF — только те, что нужны для корректного отображения,
    ничего больше (инвариант EXIF-стриппинга).
    """
    suffix = (target_suffix or meta.suffix).lower()
    if suffix not in _PILLOW_FORMAT_BY_SUFFIX:
        raise ValueError(f"неподдерживаемое целевое расширение: {suffix!r}")

    doc = pymupdf.open(str(pdf_path))
    try:
        if doc.page_count != 1:
            raise ValueError(
                f"{pdf_path.name}: ожидался одностраничный PDF, получено {doc.page_count} страниц"
            )
        page = doc[0]
        # DPI строго из метаданных исходной картинки — так «round-trip»
        # даёт картинку того же размера в пикселях (pixels = dpi * pt / 72).
        pixmap = page.get_pixmap(dpi=meta.dpi_x, colorspace=pymupdf.csRGB, alpha=False)
    finally:
        doc.close()

    image = _pixmap_to_image(pixmap)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(dst_path), **_save_kwargs(suffix, meta))


__all__ = ["pdf_to_image"]
