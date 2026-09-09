"""Тесты растровой проверки страниц PDF (план К4-1, `src/masker/validate/raster.py`).

Эталон в репозиторий не кладём (это отдельный шаг К4-2, ждёт зафиксированной
геометрии подсветки/подписи из М6). Поэтому тест дифференциальный: строит
минимальную синтетическую страницу — прямоугольник подсветки и подпись поверх
него, — рендерит её нормально и с намеренно испорченным параметром (мутация
вносится здесь, монки-патчем/параметром сборки страницы, а не правкой
`src/masker/render/pdf_render.py`, который в это же время правит другой
кодер) и доказывает, что `diff_ratio`/`phash` отличают одно от другого.
Два обязательных сценария — из приёмки задачи К4 (`TASKS.md`, коммит
``195067d``): подсветка, вернувшаяся в белую (то есть отсутствующая), и
подпись, уехавшая на другую строку и далеко влево.
"""

from __future__ import annotations

import pathlib

import pymupdf
import pytest

from masker.validate.raster import (
    DIFF_RATIO_THRESHOLD,
    RENDER_DPI,
    diff_ratio,
    hamming_distance,
    phash,
    render_page_png,
)

_FONT = str(pathlib.Path(__file__).parent.parent.parent.parent / "src/masker/data/DejaVuSans.ttf")
_FONT_NAME = "dvu"

#: Синтетическая страница нарочно маленькая (не A4): дефекты К4 —
#: пропавшая заливка и переехавшая подпись — локальны, на полноразмерной
#: странице их доля в общем числе пикселей тонет в пороге `DIFF_RATIO_THRESHOLD`
#: и в огрублении 8×8-миниатюры `phash`. Маленькая страница, где подсветка и
#: подпись занимают заметную долю кадра, — тот же тест, без хрупкой
#: подгонки порогов под размер артефакта.
_PAGE_WIDTH = 220.0
_PAGE_HEIGHT = 120.0
_HIGHLIGHT_RECT = pymupdf.Rect(10, 40, 200, 60)
_LABEL_TEXT = "[ОРГАНИЗАЦИЯ-3]"
_LABEL_POSITION = (15.0, 55.0)
_LABEL_FONT_SIZE = 10.0

#: Цвет подсветки в норме — заведомо не белый и не совпадает с фоном
#: страницы. Дефект К4 — заливка, вернувшаяся именно в белую (то есть
#: подсветки нет вовсе), поэтому мутация ниже — не «другой цвет», а именно
#: белый.
_HIGHLIGHT_FILL = (1.0, 0.85, 0.4)
_WHITE_FILL = (1.0, 1.0, 1.0)

#: Реальный дефект (`TASKS.md`, задача К4) — подпись уехала на 455 pt влево
#: и на строку вниз. Синтетическая страница меньше настоящего договора, но
#: соотношение важно: сдвиг больше ширины подсветки по X и на одну строку
#: (кегль × 1.4, тот же межстрочный интервал, что измерен для
#: `insert_textbox` в М5 — `pdf_render._LABEL_LINE_HEIGHT`) по Y, то есть
#: подпись гарантированно покидает область подсветки и попадает в область,
#: где её в нормальном рендере нет.
_MOVED_LABEL_OFFSET = (-90.0, _LABEL_FONT_SIZE * 1.4)

#: Порог гаммингова расстояния между `phash` двух рендеров одной и той же
#: страницы: детерминированный рендер (см. `test_render_is_byte_identical`)
#: обязан давать побайтово идентичный PNG и, соответственно, тождественный
#: хэш — 0 бит расхождения, без запаса на шум.
_PHASH_HAMMING_MATCH = 0


def _build_document(
    *,
    highlight_fill: tuple[float, float, float] = _HIGHLIGHT_FILL,
    label_offset: tuple[float, float] = (0.0, 0.0),
) -> pymupdf.Document:
    """Строит синтетическую страницу: подсветка + подпись поверх неё.

    ``highlight_fill``/``label_offset`` — единственные параметры, которыми
    тест вносит мутацию (белая заливка, сдвиг подписи). Правка
    `src/masker/render/pdf_render.py` в этом не участвует.
    """
    document = pymupdf.open()
    page = document.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    page.draw_rect(_HIGHLIGHT_RECT, color=None, fill=highlight_fill, fill_opacity=1)
    page.insert_font(fontname=_FONT_NAME, fontfile=_FONT)
    x = _LABEL_POSITION[0] + label_offset[0]
    y = _LABEL_POSITION[1] + label_offset[1]
    page.insert_text(
        (x, y),
        _LABEL_TEXT,
        fontname=_FONT_NAME,
        fontsize=_LABEL_FONT_SIZE,
        fontfile=_FONT,
    )
    return document


def _render_first_page(document: pymupdf.Document) -> bytes:
    return render_page_png(document, 0, dpi=RENDER_DPI)


def _assert_rasters_match(reference: bytes, candidate: bytes) -> None:
    """Мини-версия сравнения с эталоном из К4-2, но без хранения эталона:
    здесь ``reference`` — второй рендер той же «правильной» страницы, а не
    файл из репозитория. Используется, чтобы показать, что при отсутствии
    мутации метрика не поднимает ложную тревогу, и в паре с
    ``pytest.raises`` — что при внесённой мутации она обязана её поднять.
    """
    ratio = diff_ratio(reference, candidate)
    assert ratio <= DIFF_RATIO_THRESHOLD, (
        f"растры разошлись на {ratio:.4%} пикселей (порог {DIFF_RATIO_THRESHOLD:.4%})"
    )
    distance = hamming_distance(phash(reference), phash(candidate))
    assert distance <= _PHASH_HAMMING_MATCH, f"перцептивный хэш разошёлся на {distance} бит из 64"


def test_render_is_byte_identical_across_runs() -> None:
    """Два рендера одной и той же страницы — побайтово одинаковый PNG.

    Без этого дифференциальные тесты ниже были бы построены на песке:
    если бы рендер сам по себе был недетерминирован (случайный порядок
    сглаживания, недетерминированное сжатие PNG), `diff_ratio`/`phash`
    ловили бы шум рендера, а не настоящую мутацию.
    """
    document = _build_document()
    first = _render_first_page(document)
    second = _render_first_page(document)
    assert first == second

    # Тот же документ, перечитанный из байтов (второй "прогон" в терминах
    # К4-1: не тот же объект в памяти, а то же содержимое с диска) —
    # рендер обязан совпасть и с ним.
    reopened = pymupdf.open(stream=document.tobytes(), filetype="pdf")
    third = _render_first_page(reopened)
    assert first == third


def test_white_highlight_is_detected() -> None:
    """Заливка подсветки, вернувшаяся в белую (то есть отсутствующая),
    обязана быть видна метрике — иначе она не поймает дефект `TASKS.md` К4
    (первая страница школьного договора, подсветка отсутствовала).
    """
    good = _render_first_page(_build_document())

    # На двух рендерах без мутации метрика не должна ложно сработать.
    same = _render_first_page(_build_document())
    _assert_rasters_match(good, same)

    # Мутация: заливка подсветки стала белой — сама подсветка исчезла.
    white = _render_first_page(_build_document(highlight_fill=_WHITE_FILL))
    with pytest.raises(AssertionError):
        _assert_rasters_match(good, white)

    # То же самое явно через оба примитива по отдельности — чтобы падение
    # выше нельзя было списать на случайность одной из двух проверок.
    assert diff_ratio(good, white) > DIFF_RATIO_THRESHOLD
    assert hamming_distance(phash(good), phash(white)) > _PHASH_HAMMING_MATCH


def test_label_moved_to_another_line_is_detected() -> None:
    """Подпись, уехавшая на другую строку и далеко влево (`TASKS.md` К4:
    `[ОРГАНИЗАЦИЯ-3]` на 455 pt влево и на строку вниз), обязана быть видна
    метрике.
    """
    good = _render_first_page(_build_document())

    same = _render_first_page(_build_document())
    _assert_rasters_match(good, same)

    moved = _render_first_page(_build_document(label_offset=_MOVED_LABEL_OFFSET))
    with pytest.raises(AssertionError):
        _assert_rasters_match(good, moved)

    assert diff_ratio(good, moved) > DIFF_RATIO_THRESHOLD
    assert hamming_distance(phash(good), phash(moved)) > _PHASH_HAMMING_MATCH
