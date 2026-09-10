"""Логотип и имя продукта в терминале.

Щит рисуется не «нарисованной вручную картинкой из символов», а растром:
форма и цвета считаются по геометрии, затем каждая пара строк пикселей
складывается в один символ ``▀`` (верхний полублок) — цвет символа даёт
верхний пиксель, цвет фона нижний. Так вертикальное разрешение удваивается,
и на шестнадцати строках терминала помещается силуэт, который читается
как щит, а не как набор палочек.

Цвета сняты пипеткой с исходного логотипа, а не подобраны на глаз.
"""

from __future__ import annotations

import os
import sys

from rich.style import Style
from rich.text import Text

__all__ = [
    "PRODUCT",
    "TAGLINE",
    "banner",
    "logo_lines",
    "logo_text",
    "wordmark_text",
]

#: Имя продукта. Внутреннее имя пакета (`masker`) намеренно не трогаем:
#: переименование пакета задевает каждый импорт в проекте и ничего не даёт
#: пользователю, который видит только команду и заголовок.
PRODUCT = "DocVeil"
TAGLINE = "обезличивание тендерных документов, локально"

#: Пипетка по исходному логотипу (`PNG`, самые частые непрозрачные цвета).
PAPER = (0xF0, 0xF2, 0xF6)
PAPER_SHADE = (0xE0, 0xE6, 0xF0)
FOLD = (0x80, 0x90, 0xB0)
BAR = (0x70, 0x80, 0xA0)
NAVY = (0x20, 0x30, 0x60)
NAVY_LIGHT = (0x20, 0x40, 0x60)
STEEL = (0x50, 0x70, 0xA0)

#: Пропорции взяты с оригинала (1210×1300, ширина к высоте ≈ 0.93). Символ
#: терминала примерно вдвое выше своей ширины, а полублок даёт два пикселя
#: на строку — поэтому «пиксельные» _W и _H и есть видимые пропорции.
_W = 30
_H = 32


def _inside(x: int, y: int) -> bool:
    """Силуэт щита: сверху прямоугольник со скруглением, снизу — остриё."""
    shoulder = _H * 0.52
    if y < shoulder:
        left, right = 0.0, float(_W - 1)
        # Скругление верхних углов — четверть окружности радиусом 4.
        radius = 4
        if y < radius:
            dy = radius - y
            inset = radius - (radius * radius - dy * dy) ** 0.5
            left, right = inset, _W - 1 - inset
        return left <= x <= right
    # Ниже плеч стороны сходятся к центру: чем ниже, тем уже.
    progress = (y - shoulder) / (_H - shoulder)
    half = (_W / 2) * (1.0 - progress**1.6)
    center = (_W - 1) / 2
    return bool(abs(x - center) <= half)


def _colour(x: int, y: int) -> tuple[int, int, int] | None:
    if not _inside(x, y):
        return None
    center = (_W - 1) / 2
    fold = 8
    # Загнутый уголок листа — треугольник, срезающий правый верхний угол.
    if x >= _W - fold and y <= fold and (x - (_W - fold)) >= y:
        return FOLD
    # Лист лежит на щите не по прямой, а клином: в оригинале нижняя кромка
    # бумаги опускается к центру и поднимается к краям. Прямая граница
    # читалась бы как «лист обрезали», а не «лист поверх щита».
    edge = _H * 0.52 + _H * 0.14 * (1.0 - abs(x - center) / center)
    if y >= edge:
        # Сам щит: слева грань посветлее, справа тёмная — как на логотипе.
        facet = (y - edge) * 0.9
        return NAVY_LIGHT if x < center - facet else NAVY
    # Три строки текста на листе. Длины разные, как в оригинале: средняя
    # самая длинная — иначе блок читается как сплошной прямоугольник.
    thickness = max(2, round(_H * 0.09))
    for row, right in ((0.20, 0.66), (0.32, 0.78), (0.44, 0.64)):
        top = _H * row
        if top <= y < top + thickness and _W * 0.20 <= x <= _W * right:
            return BAR
    return PAPER if y > 1 else PAPER_SHADE


#: Плотность символа вместо цвета для NO_COLOR и монохромных терминалов.
_SHADE: dict[tuple[int, int, int], str] = {
    PAPER: "░",
    PAPER_SHADE: "░",
    FOLD: "▒",
    BAR: "▓",
    NAVY_LIGHT: "▓",
    NAVY: "█",
}


def _use_colour(stream: object = None) -> bool:
    """Цвет только в настоящем терминале и без явного запрета.

    `NO_COLOR` — устоявшееся соглашение; вывод в пайп обязан оставаться
    простым текстом, иначе логи и `grep` захлёбываются escape-кодами.
    """
    if os.environ.get("NO_COLOR"):
        return False
    target = stream if stream is not None else sys.stdout
    return bool(getattr(target, "isatty", lambda: False)())


def logo_lines(colour: bool = True) -> list[str]:
    """Строки логотипа: цветные с ANSI или монохромные из символов."""
    lines: list[str] = []
    for row in range(0, _H, 2):
        parts: list[str] = []
        for x in range(_W):
            top = _colour(x, row)
            bottom = _colour(x, row + 1) if row + 1 < _H else None
            if not colour:
                # Без цвета форма всё равно должна читаться: плотность
                # символа заменяет яркость, иначе щит вырождается в пятно.
                shade = top or bottom
                parts.append(_SHADE.get(shade, "█") if shade is not None else " ")
                continue
            if top is None and bottom is None:
                parts.append(" ")
            elif top is None:
                parts.append("\033[38;2;{};{};{}m▄\033[0m".format(*bottom))  # type: ignore[misc]
            elif bottom is None:
                parts.append("\033[38;2;{};{};{}m▀\033[0m".format(*top))
            else:
                parts.append("\033[38;2;{};{};{}m\033[48;2;{};{};{}m▀\033[0m".format(*top, *bottom))
        lines.append("".join(parts))
    return lines


#: Начертание имени продукта: та же техника, что у щита — пиксели, а не
#: набранные вручную строки псевдографики. Заглавные высотой десять пикселей,
#: строчные — семь, посаженные на общую базовую линию: иначе «DocVeil»
#: рассыпается на буквы разного роста и перестаёт читаться как одно слово.
_GLYPHS: dict[str, tuple[str, ...]] = {
    "D": (
        "██████ ",
        "██   ██",
        "██    █",
        "██    █",
        "██    █",
        "██    █",
        "██    █",
        "██    █",
        "██   ██",
        "██████ ",
    ),
    "o": (
        "      ",
        "      ",
        "      ",
        " ████ ",
        "██  ██",
        "██  ██",
        "██  ██",
        "██  ██",
        "██  ██",
        " ████ ",
    ),
    "c": (
        "      ",
        "      ",
        "      ",
        " ████ ",
        "██  ██",
        "██    ",
        "██    ",
        "██    ",
        "██  ██",
        " ████ ",
    ),
    "V": (
        "██   ██",
        "██   ██",
        "██   ██",
        "██   ██",
        "██   ██",
        " ██ ██ ",
        " ██ ██ ",
        "  ███  ",
        "  ███  ",
        "   █   ",
    ),
    "e": (
        "      ",
        "      ",
        "      ",
        " ████ ",
        "██  ██",
        "██  ██",
        "██████",
        "██    ",
        "██  ██",
        " ████ ",
    ),
    "i": (
        "██",
        "██",
        "  ",
        "██",
        "██",
        "██",
        "██",
        "██",
        "██",
        "██",
    ),
    "l": (
        "██",
        "██",
        "██",
        "██",
        "██",
        "██",
        "██",
        "██",
        "██",
        "██",
    ),
}

#: Ширина имени в столбцах вместе с пробелами между буквами.
WORDMARK_WIDTH = sum(len(_GLYPHS[ch][0]) for ch in PRODUCT) + len(PRODUCT) - 1


def wordmark_lines(colour: bool = True) -> list[str]:
    """Имя продукта крупными буквами — пять строк терминала."""
    rows = [""] * 10
    for index, char in enumerate(PRODUCT):
        glyph = _GLYPHS[char]
        gap = " " if index else ""
        rows = [row + gap + glyph[y] for y, row in enumerate(rows)]

    lines: list[str] = []
    for y in range(0, 10, 2):
        parts: list[str] = []
        for x in range(len(rows[0])):
            top = rows[y][x] != " "
            bottom = rows[y + 1][x] != " " if y + 1 < 10 else False
            if not colour:
                # Полублоки, а не сплошной «█»: без них «e» и «o» слипаются
                # в одинаковые кирпичи и слово перестаёт читаться.
                parts.append("█" if top and bottom else "▀" if top else "▄" if bottom else " ")
            elif top and bottom:
                parts.append("\033[38;2;{};{};{}m█\033[0m".format(*STEEL))
            elif top:
                parts.append("\033[38;2;{};{};{}m▀\033[0m".format(*STEEL))
            elif bottom:
                parts.append("\033[38;2;{};{};{}m▄\033[0m".format(*STEEL))
            else:
                parts.append(" ")
        lines.append("".join(parts))
    return lines


def banner(colour: bool | None = None, width: int | None = None) -> str:
    """Логотип с именем продукта сбоку — заставка запуска.

    В узком терминале имя набирается обычным текстом: крупные буквы,
    перенесённые на следующую строку, выглядят хуже отсутствия крупных букв.
    """
    use = _use_colour() if colour is None else colour
    art = logo_lines(use)
    accent = "\033[38;2;{};{};{}m".format(*STEEL) if use else ""
    bright = "\033[1m" if use else ""
    dim = "\033[2m" if use else ""
    reset = "\033[0m" if use else ""

    columns = width if width is not None else _terminal_width()
    roomy = columns >= _W + 2 + max(WORDMARK_WIDTH, len(TAGLINE))
    if roomy:
        side = [*wordmark_lines(use), "", f"{dim}{TAGLINE}{reset}"]
    else:
        side = [f"{bright}{accent}{PRODUCT}{reset}", f"{dim}{TAGLINE}{reset}"]

    top = max(0, (len(art) - len(side)) // 2)
    side = [""] * top + side + [""] * max(0, len(art) - len(side) - top)

    return "\n".join(
        f"{art_line}  {text}".rstrip() for art_line, text in zip(art, side[: len(art)], strict=True)
    )


def _terminal_width(default: int = 80) -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return default


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def logo_text() -> Text:
    """Логотип как ``rich.text.Text`` — для Textual и всего на Rich.

    Сырые ANSI-коды внутрь виджета Textual класть нельзя: он их экранирует,
    и вместо цветного щита получается монохромный. Стили нужно отдавать
    объектом, тогда цвет доезжает до экрана.
    """
    text = Text()
    for row in range(0, _H, 2):
        for x in range(_W):
            top = _colour(x, row)
            bottom = _colour(x, row + 1) if row + 1 < _H else None
            if top is None and bottom is None:
                text.append(" ")
            elif top is None:
                text.append("▄", style=Style(color=_hex(bottom)))  # type: ignore[arg-type]
            elif bottom is None:
                text.append("▀", style=Style(color=_hex(top)))
            else:
                text.append("▀", style=Style(color=_hex(top), bgcolor=_hex(bottom)))
        if row + 2 < _H:
            text.append("\n")
    return text


def wordmark_text() -> Text:
    """Имя продукта крупными буквами как ``rich.text.Text``."""
    style = Style(color=_hex(STEEL), bold=True)
    text = Text()
    for index, line in enumerate(wordmark_lines(colour=False)):
        if index:
            text.append("\n")
        text.append(line, style=style)
    return text


if __name__ == "__main__":  # pragma: no cover — ручной просмотр логотипа
    print(banner(colour=True))
