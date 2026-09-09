"""Нормализация общего для PDF и DOCX фона читаемой маски."""

from __future__ import annotations

import re

DEFAULT_HIGHLIGHT_BACKGROUND = "#FFDE66"
"""Нынешний янтарный фон PDF в привычной для пользователя hex-записи."""

# В старом PDF этот цвет был задан десятичными числами. Оставляем именно их
# для default, чтобы отсутствие нового параметра не меняло байты артефакта.
DEFAULT_PDF_HIGHLIGHT_FILL: tuple[float, float, float] = (1.0, 0.87, 0.40)

_HEX_COLOR_RE = re.compile(r"#?([0-9a-fA-F]{6})\Z")


def parse_highlight_background(value: str | None) -> str | None:
    """Вернуть канонический ``#RRGGBB`` либо ``None`` для ``none``.

    ``none`` отключает только фон: маркер в квадратных скобках и точки-
    заполнители остаются, поэтому замену всё ещё можно найти глазами.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("фон подсветки: ожидается #RRGGBB, RRGGBB или none")
    normalized = value.strip()
    if normalized.casefold() == "none":
        return None
    match = _HEX_COLOR_RE.fullmatch(normalized)
    if match is None:
        raise ValueError(
            f"некорректный фон подсветки {value!r}: ожидается #RRGGBB, RRGGBB или none"
        )
    return f"#{match.group(1).upper()}"


def pdf_fill_color(background: str | None) -> tuple[float, float, float] | None:
    """Перевести канонический фон в RGB PyMuPDF, сохранив legacy default."""
    if background is None:
        return None
    if background == DEFAULT_HIGHLIGHT_BACKGROUND:
        return DEFAULT_PDF_HIGHLIGHT_FILL
    red, green, blue = (int(background[index : index + 2], 16) / 255 for index in (1, 3, 5))
    return red, green, blue


def docx_fill_color(background: str | None) -> str | None:
    """Перевести канонический фон в ``w:shd/@w:fill``."""
    return background[1:] if background is not None else None
