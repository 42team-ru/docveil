"""Ингест одиночной картинки (JPEG/PNG/TIFF).

Одностраничная картинка → тот же граф, что и PDF. Внутри:

1. `probe()` из `image_meta` снимает WxH/DPI/ориентацию.
2. Гейт документа: если после OCR распознанных строк со значащим текстом
   меньше `_MIN_MEANINGFUL_LINES = 3` или суммарная длина < 20 символов —
   `NotADocumentError`. Порог калибруется на синтетике из fixtures.
3. Картинка конвертируется в одностраничный PDF через PyMuPDF (dpi
   берётся из EXIF или дефолт 300).
4. Управление отдаётся `ingest_pdf(tmp, ocr=ocr)`; результирующий
   `Document` переклеивает поля так, чтобы `path` показывал на исходный
   файл-картинку, а `meta` хранила `image_source`, `image_suffix`,
   `image_width`, `image_height`, `image_dpi_x`, `image_dpi_y`,
   `image_orientation`, `image_format`.

`meta["image_source"]` — маркер: рендер-узел ловит его и, если
`options.image_output_format == "original"`, конвертирует итоговый PDF
обратно в исходный формат картинки через `masker.render.image_export`.
"""

from __future__ import annotations

import pathlib
import tempfile
from typing import TYPE_CHECKING

from PIL import Image, ImageOps

from masker.ingest.image_meta import (
    ImageMetadata,
    MultiPageNotSupported,
    NotADocumentError,
    probe,
)
from masker.model import Document

if TYPE_CHECKING:
    from masker.ocr.provider import OCRProvider


#: Минимум распознанных содержательных строк, чтобы считать картинку
#: документом (гейт). Ниже — `NotADocumentError`. Порог грубый: фото
#: паспорта имеет десятки строк, «фото кота» — 0.
_MIN_MEANINGFUL_LINES: int = 3
#: Минимальная суммарная длина распознанного текста (символы без пробелов).
_MIN_MEANINGFUL_CHARS: int = 20


def _prepare_for_pdf(image: Image.Image) -> Image.Image:
    """Привести изображение к RGB с уважением EXIF-ориентации.

    `exif_transpose` физически поворачивает пиксели по `Orientation` (1..8)
    и сбрасывает тег в 1 — так экспорт в PDF не крутит картинку второй раз.
    RGBA → RGB через альфа-композит на белом фоне: без этого `get_pixmap`
    склеивает прозрачные пиксели в чёрные (см. «грабли» в плане).
    """
    oriented = ImageOps.exif_transpose(image)
    # ImageOps.exif_transpose гарантированно возвращает Image; None бывает
    # только на входе None — но mypy этого не знает без явного assert.
    assert oriented is not None
    if oriented.mode == "RGBA":
        background = Image.new("RGB", oriented.size, (255, 255, 255))
        background.paste(oriented, mask=oriented.split()[-1])
        return background
    if oriented.mode == "P":
        return oriented.convert("RGB")
    if oriented.mode != "RGB":
        return oriented.convert("RGB")
    return oriented


def _convert_to_single_page_pdf(
    source: pathlib.Path, meta: ImageMetadata, destination: pathlib.Path
) -> None:
    """Собрать одностраничный PDF из картинки: страница = pixels * 72 / dpi.

    Pillow сам умеет сохранять `Image.save(..., "PDF")` — используем его,
    чтобы не тянуть PyMuPDF на этап сборки (у него `open()` из pixmap
    страницу тоже строит, но точность DPI хуже: pymupdf приводит к целому
    pt через `pixmap.set_dpi`, а Pillow пишет размер страницы прямо).
    """
    with Image.open(str(source)) as image:
        prepared = _prepare_for_pdf(image)
        # `resolution` = DPI в points; Pillow пересчитает page-mediabox
        # автоматически как pixels / dpi (в дюймах) * 72.
        prepared.save(
            str(destination),
            format="PDF",
            resolution=float(meta.dpi_x),
        )


def _meaningful_text_stats(document: Document) -> tuple[int, int]:
    """Число «содержательных» сегментов и суммарная длина без пробелов."""
    line_count = 0
    total_chars = 0
    for segment in document.segments:
        text = segment.text.strip()
        if not text:
            continue
        line_count += 1
        total_chars += len("".join(text.split()))
    return line_count, total_chars


def ingest_image(
    path: str | pathlib.Path,
    ocr: OCRProvider | None = None,
) -> Document:
    """Разобрать одностраничную картинку через PDF-ветку OCR.

    ``ocr is None`` не допустим: у картинки текстового слоя нет по
    определению, вся детекция строится на OCR-сегментах. Без провайдера
    прогон бы завершился с пустым документом и Certificate бы прошёл, но
    ни одной сущности бы не нашлось — это молчаливая утечка, поэтому
    ``ValueError`` явно.

    Возвращает `Document` с `fmt="pdf"` (внутри графа документ живёт как
    одностраничный PDF), но `path` — исходной картинки, а в `meta` лежат
    `image_source=<basename>` и остальные размеры/DPI/ориентация.
    """
    src = pathlib.Path(path)
    if ocr is None:
        raise ValueError(
            f"{src.name}: OCR-провайдер обязателен для картинки — без него ни одна сущность"
            " не будет найдена"
        )
    meta = probe(src)

    # Импорт здесь, чтобы модуль-с-гейтом не тянул PyMuPDF на импорт (см.
    # тест `test_layer_boundary`, а также юниты для probe без сети).
    from masker.ingest.pdf_ingest import ingest_pdf

    # Промежуточный PDF не удаляется здесь: он нужен последующим узлам графа
    # (render, validate) как «настоящий source» — рендер PDF-редактора умеет
    # работать только с PDF, а `state["path"]` показывает на картинку.
    # Удаляет файл `image_export_node` после экспорта в целевой формат.
    with tempfile.NamedTemporaryFile(
        prefix=f"masker_image_{src.stem}_", suffix=".pdf", delete=False
    ) as handle:
        tmp_pdf = pathlib.Path(handle.name)
    try:
        _convert_to_single_page_pdf(src, meta, tmp_pdf)
        document = ingest_pdf(tmp_pdf, ocr=ocr)
    except BaseException:
        # Любая ошибка (в т.ч. `NotADocumentError` ниже — но она поднимется
        # ПОСЛЕ этого блока) не должна оставлять tempfile висеть; успешный
        # путь удаляет файл в `image_export_node`.
        tmp_pdf.unlink(missing_ok=True)
        raise

    lines, chars = _meaningful_text_stats(document)
    if lines < _MIN_MEANINGFUL_LINES or chars < _MIN_MEANINGFUL_CHARS:
        # Гейт не пройден — временного PDF никто дальше не увидит, удаляем.
        tmp_pdf.unlink(missing_ok=True)
        raise NotADocumentError(
            f"{src.name}: гейт документа не пройден — распознано {lines} строк"
            f" ({chars} символов), нужно ≥{_MIN_MEANINGFUL_LINES} строк"
            f" и ≥{_MIN_MEANINGFUL_CHARS} символов"
        )

    image_meta: dict[str, str] = {
        "image_source": meta.name,
        "image_suffix": meta.suffix,
        "image_format": meta.format,
        "image_width": str(meta.width),
        "image_height": str(meta.height),
        "image_dpi_x": str(meta.dpi_x),
        "image_dpi_y": str(meta.dpi_y),
        "image_orientation": str(meta.orientation),
        "image_mode": meta.mode,
        # Абсолютный путь к промежуточному PDF — рендер и валидация читают
        # именно его, потому что `state["path"]` показывает на исходную
        # картинку и `pymupdf.open` на .jpg падает с «is no PDF».
        "image_intermediate_pdf": str(tmp_pdf.resolve()),
    }
    # Метаданные, вытащенные из PDF-обёртки, для картинки бессмысленны
    # (Pillow пишет свои author/producer/creator в PDF) — их не тащим.
    return Document(
        path=str(src),
        fmt="pdf",
        segments=list(document.segments),
        meta=image_meta,
    )


__all__ = [
    "ImageMetadata",
    "MultiPageNotSupported",
    "NotADocumentError",
    "ingest_image",
]
