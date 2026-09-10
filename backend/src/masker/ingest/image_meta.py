"""Считывание метаданных одиночной картинки (JPEG/PNG/TIFF).

Отдельный модуль без зависимостей от PyMuPDF и графа — специально, чтобы
`probe()` можно было юнит-тестить без побочных эффектов конвертации в PDF.
Здесь только Pillow: снимаем размер, формат, каналы, DPI, ориентацию и
проверяем ключевые инварианты входа (одностраничность TIFF).

Дефолт DPI — 300, кэп сверху — 600, снизу — 72 (см. `MIN_DPI`/`MAX_DPI`).
EXIF врёт часто; без кэпов страница PDF, посчитанная как `pixels * 72 /
dpi`, становится либо микроскопической, либо гигантской.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from PIL import ExifTags, Image

#: Дефолт DPI, когда в файле нет ни `dpi`, ни EXIF `XResolution`.
DEFAULT_DPI: int = 300
#: Нижний кэп DPI — страница PDF из EXIF-`dpi=10` получилась бы 6120 pt.
MIN_DPI: int = 72
#: Верхний кэп DPI — 600 достаточно для любого канцелярского скана,
#: выше — только паразитные значения из EXIF.
MAX_DPI: int = 600
#: Расширения, которые парсер принимает как одностраничные картинки.
SUPPORTED_SUFFIXES: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff"})


class NotADocumentError(ValueError):
    """Гейт документа: картинка признана не документом (пустой/шумной)."""


class MultiPageNotSupported(ValueError):
    """Многостраничный TIFF: MVP работает только с одной страницей."""


@dataclass(frozen=True, slots=True)
class ImageMetadata:
    """Метаданные одиночной картинки.

    `name` — базовое имя исходного файла. `format` — как его назвал Pillow
    (`"JPEG"`, `"PNG"`, `"TIFF"`). `dpi_x`/`dpi_y` — уже приведённое к
    кэпам целое (см. `MIN_DPI`/`MAX_DPI`). `orientation` — значение EXIF
    `Orientation` (1..8) либо 1, если тега нет.

    `suffix` хранится отдельно, потому что Pillow `format="JPEG"` подходит
    и для `.jpg`, и для `.jpeg` — сохранять надо в исходное расширение,
    иначе `some.jpeg` превратится в `some.jpg` и это лишнее удивление.
    """

    name: str
    suffix: str  # ".jpg" | ".jpeg" | ".png" | ".tif" | ".tiff"
    width: int
    height: int
    format: str  # "JPEG" | "PNG" | "TIFF"
    mode: str  # "RGB" | "RGBA" | "L" | "1" | ...
    channels: int
    bit_depth: int
    dpi_x: int
    dpi_y: int
    orientation: int


def _clamp_dpi(value: float) -> int:
    """Привести DPI к целому в диапазоне ``[MIN_DPI, MAX_DPI]``."""
    if value <= 0:
        return DEFAULT_DPI
    return max(MIN_DPI, min(MAX_DPI, round(value)))


def _bit_depth_from_mode(mode: str) -> int:
    """Оценить глубину пикселя по режиму Pillow (без чтения бинарника)."""
    # Значения покрывают режимы, которые действительно приходят из JPEG/PNG/TIFF.
    depths: dict[str, int] = {
        "1": 1,
        "L": 8,
        "P": 8,
        "RGB": 24,
        "RGBA": 32,
        "CMYK": 32,
        "YCbCr": 24,
        "I": 32,
        "I;16": 16,
        "F": 32,
    }
    return depths.get(mode, 8)


def _orientation_from_exif(image: Image.Image) -> int:
    """Прочитать EXIF `Orientation` (тег 0x0112); 1, если тега нет."""
    exif = image.getexif()
    if not exif:
        return 1
    key: int | None = None
    for tag_id, tag_name in ExifTags.TAGS.items():
        if tag_name == "Orientation":
            key = tag_id
            break
    if key is None:
        return 1
    value = exif.get(key, 1)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1
    if parsed < 1 or parsed > 8:
        return 1
    return parsed


def _dpi_from_image(image: Image.Image) -> tuple[int, int]:
    """Достать DPI из `image.info["dpi"]` либо EXIF, дефолт — `DEFAULT_DPI`.

    Pillow кладёт DPI в `info["dpi"] = (x, y)` для PNG/JPEG/TIFF, но не
    всегда — TIFF без ResolutionUnit=inch приходит без ключа. Читаем EXIF
    `XResolution`/`YResolution` (0x011A/0x011B) как запасной вариант.
    """
    dpi_pair = image.info.get("dpi")
    if isinstance(dpi_pair, tuple) and len(dpi_pair) == 2:
        return _clamp_dpi(float(dpi_pair[0])), _clamp_dpi(float(dpi_pair[1]))
    exif = image.getexif()
    if exif:
        x_res = exif.get(0x011A)
        y_res = exif.get(0x011B)
        if x_res and y_res:
            try:
                return _clamp_dpi(float(x_res)), _clamp_dpi(float(y_res))
            except (TypeError, ValueError):
                pass
    return DEFAULT_DPI, DEFAULT_DPI


def probe(path: str | pathlib.Path) -> ImageMetadata:
    """Считать метаданные одиночной картинки без её загрузки в память целиком.

    Многостраничный TIFF (`n_frames > 1`) поднимает `MultiPageNotSupported`
    — MVP работает только с одной страницей.
    """
    p = pathlib.Path(path)
    suffix = p.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"неподдерживаемое расширение картинки: {suffix!r}")

    with Image.open(str(p)) as image:
        image.load()
        n_frames = getattr(image, "n_frames", 1)
        if n_frames and n_frames > 1:
            raise MultiPageNotSupported(
                f"{p.name}: многостраничный TIFF ({n_frames} страниц) в MVP не поддержан"
            )
        mode = image.mode
        channels = len(image.getbands())
        bit_depth = _bit_depth_from_mode(mode)
        dpi_x, dpi_y = _dpi_from_image(image)
        orientation = _orientation_from_exif(image)
        fmt = image.format or ""
        return ImageMetadata(
            name=p.name,
            suffix=suffix,
            width=int(image.width),
            height=int(image.height),
            format=fmt,
            mode=mode,
            channels=channels,
            bit_depth=bit_depth,
            dpi_x=dpi_x,
            dpi_y=dpi_y,
            orientation=orientation,
        )
