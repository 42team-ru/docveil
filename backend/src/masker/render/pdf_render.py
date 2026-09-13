"""Рендер PDF: неразрушающий preview и настоящее редактирование.

Локализация замены — по символьным смещениям якоря (``anchor.locator`` =
``("page", page_num, char_start, char_end)``, план T2.2.1, шаг 9), а не
повторным поиском строки по странице. Такой поиск был источником сразу
двух дефектов: маркер вставлялся в каждое найденное на странице вхождение
строки, а не в то одно, которое реально было заменено (Д1 — дубли
маркеров), и мог попасть не в то вхождение вовсе, если одна и та же
строка встречалась на странице несколько раз (Д2). Символьные боксы и
номера строк строит ``page_chars`` (``ingest/pdf_ingest.py``) — тот же
строитель, что и ingest, чтобы обход страницы не разъехался в две
независимые реализации (риск Р4).

Прямоугольник редакции, построенный из боксов одной строки, по вертикали
иногда залезает на соседнюю строку — шаг строк в реальном документе бывает
меньше высоты бокса глифа (боксы включают выносные элементы шрифта), и
соседние строки перекрываются на несколько пунктов. ``apply_redactions``
удаляет глиф по пересечению его бокса с прямоугольником, а не по
вложенности, поэтому такой прямоугольник стирал текст соседней строки по
всей своей ширине (Д10 плана T2.2.2). Лечение — обрезать прямоугольник
серединой полосы перекрытия со соседней строкой (``_trim_to_own_line``);
строка берётся из ``line_ids``, а не угадывается по координате — угадывание
на реальном документе один раз уже схлопнуло прямоугольник в нулевую
высоту и сущность утекла (``Ивановны`` в диагностике плана T2.2.2).

Контракт читаемой маски (план М1) разделяет три вещи, смешанные в одном
прямоугольнике раньше — что удалить, что закрасить, что подписать:

- ``erase_regions`` — прямоугольники, по которым реально стёрт текст
  (``add_redact_annot``/``apply_redactions``). Строятся **только** из
  символьных боксов самой сущности, обрезанных по своей строке
  (``_trim_to_own_line``), и никогда не раздвигаются ради подписи — иначе
  ``apply_redactions`` стирал бы текст соседа (план М1, правило 3). Ширина
  затем квантуется вверх по сетке 12 pt (``_quantize_erase_rect``, план М1,
  правило 5) — без этого ширина прямоугольника один в один повторяет длину
  удалённого текста, доказанный канал утечки (PoPETs 2023, ≈13 бит о
  фамилии). Расширение кванта, как и расширение подписи, никогда не заходит
  на чужой непробельный символ — граница та же ``_free_extension_right``.
- ``paint_regions`` — области, закрашенные фоном (эрейз-регионы плюс,
  если подпись расширилась, полоса расширения — она тоже красится, но не
  редактируется, потому что заведомо пуста).
- ``label_region`` — куда физически вписан текст подписи. Может быть шире
  своего эрейз-региона: расширяется **вправо по той же строке**, и только
  до первого чужого символа (``_free_extension_right``) — доказанно
  свободное место, не «на глаз». Отступ на воздух под глифы (сверху и
  снизу) — тем же приёмом (``_free_extension_vertical``): край поля
  подписи может отступить от эрейз-прямоугольника только до первого чужого
  непробельного символа соседней строки, а не безусловно на фиксированное
  число пунктов — план М5 (баг «заливка заезжает на № сразу за датой», см.
  ``docs/TASKS.md``, найдено заказчиком глазами 08.09.2026): старый код
  добавлял отступ **сверх** уже посчитанной безопасной границы, а не
  зажимал его ею, и ровно эти лишние пункты заезжали на живой символ.

Место для подписи больше не отмеряется по ширине удалённого текста
(корневая причина жалоб заказчика на мелкий шрифт): подпись подбирается
лестницей отступления (``mask.labels.marker_ladder``) с полом читаемости
**8 pt** — ниже этого текст не пробуется вовсе, вместо него берётся более
короткая ступень лестницы. Строка для подписи у многострочной
сущности выбирается строго в порядке документа: подпись должна стоять
там, где стоял оригинал. На каждом кандидате отрабатывает вся лестница, и
на следующую строку рендер уходит, только если не влезла даже самая
короткая ступень. Сокращение на месте лучше переезда — позиция в договоре
несёт смысл (кто из сторон где упомянут), а расшифровка сокращения стоит
одной строки легенды в отчёте.

Стиль ``blackbox`` не запускает лестницу отступления вовсе (план T2.2.2,
шаг 1, решение заказчика): чёрный прямоугольник — просто чёрный, без
текста на любой ступени.
"""

from __future__ import annotations

import dataclasses
import math
import os
import pathlib
from collections import defaultdict
from dataclasses import dataclass

import pymupdf

from masker.highlight import (
    DEFAULT_HIGHLIGHT_BACKGROUND,
    DEFAULT_PDF_HIGHLIGHT_FILL,
    parse_highlight_background,
    pdf_fill_color,
)
from masker.ingest.pdf_ingest import PageChars, page_chars
from masker.mask.labels import marker_ladder
from masker.model import (
    Document,
    Entity,
    MarkerRenderResult,
    MaskGroup,
    MaskPlan,
    PdfRegion,
    Replacement,
)

_FONT_FILE: pathlib.Path = pathlib.Path(__file__).parent.parent / "data" / "DejaVuSans.ttf"
_FONT_NAME = "cyr"
#: Кандидаты размера шрифта, от крупного к минимальному. Пол читаемости —
#: 8 pt (план М1, правило 1): ниже этого порога подпись не пробуется вовсе,
#: рендер спускается на следующую ступень лестницы отступления текста, а не
#: на более мелкий шрифт. Раньше здесь были размеры вплоть до 2 pt — именно
#: это порождало жалобу заказчика «мелкий шрифт».
_MARKER_FONT_SIZES: tuple[float, ...] = (10.0, 9.0, 8.0)
#: 12.09.2026: подпись рисуется ``insert_text``, поэтому ей нужна высота
#: реального глифа, а не служебный интервал ``insert_textbox`` в 1.4 кегля.
#: Старое ограничение без причины уменьшало кегль даже у короткой метки,
#: которая свободно помещалась на исходной строке.
_LABEL_GLYPH_HEIGHT = 1.2
#: Шаг сетки квантования ширины `erase_regions` (план М1, правило 5).
#: Ширина прямоугольника, повторяющая ширину удалённого текста, — доказанный
#: канал утечки длины фамилии (PoPETs 2023, ≈13 бит, один человек из 8000):
#: округление вверх до кратного 12 pt схлопывает много разных длин в одну
#: и ту же наблюдаемую геометрию.
_ERASE_WIDTH_GRID = 12.0
#: Общий допуск сравнения геометрии с плавающей точкой — боксы глифов из
#: PyMuPDF накапливают шум значительно больше "учебного" `1e-6` (реально
#: наблюдалось расхождение ~6e-5pt между границей объединённого прямоугольника
#: сущности и боксом следующего символа на той же координате). Старое значение
#: `1e-6` пропускало символ-сосед как «уже внутри прямоугольника» и давало
#: расширению вправо ложную безопасную границу дальше настоящего соседа —
#: `apply_redactions`/квантование стирали часть соседнего слова (диагностика
#: на `contract_pdf_02_school.pdf`, план М1). `0.01pt` на три порядка больше
#: наблюдаемого шума и на два порядка меньше ширины любого реального глифа.
_GEOMETRY_EPS = 0.01
#: Доля высоты собственной строки, начиная с которой пересечение по
#: вертикали с другим прямоугольником строки считается «это та же физическая
#: строка» (остаток собственной строки после ``apply_redactions``), а не
#: соседняя строка сверху/снизу (``_free_extension_vertical``, план М6-1).
#: Настоящие соседние строки перекрываются лишь на 1–2pt выносными
#: элементами шрифта (Д10) — доля от полной высоты строки (обычно
#: 10–15pt) далеко меньше половины; остаток собственной строки после
#: редактирования, наоборот, занимает весь тот же вертикальный диапазон
#: (сама строка никуда не движется, редактирование только убирает часть
#: символов из неё) — отсюда порог `0.5`, с большим запасом между двумя
#: случаями. Сравнение на точное равенство прямоугольников (``other ==
#: own_line``), которое было здесь раньше, не срабатывает на настоящей
#: редакции вовсе: `own_line` — это `pre_line_boxes[line_id]`, включающий
#: боксы самой (ещё не стёртой) сущности, а построенный по `post_chars`
#: остаток той же строки этих боксов уже не содержит — прямоугольники
#: даже в тривиальном случае отличаются по `x0`. Без этой замены остаток
#: собственной строки ложно считался чужой строкой снизу/сверху и обрезал
#: вертикальный отступ до долей пункта там, где настоящего соседа нет
#: вовсе (регресс, найденный при разборе `highlight_overlaps` 315 → 1090,
#: `fix/r9-span-boundaries`).
_OWN_LINE_OVERLAP_RATIO = 0.5

#: Нулевой прямоугольник — сигнатура символа-склейки строк, который
#: `page_chars`/`ingest_pdf` вставляют строго на границе физической строки
#: внутри блока (план T2.2.1, шаг 8). Настоящие пробелы получают от
#: PyMuPDF собственный ненулевой бокс — совпадение с этим сигналом
#: означает «здесь линия обрывается», а не «здесь пробел».
_LINE_BREAK_RECT = pymupdf.Rect(0.0, 0.0, 0.0, 0.0)
#: Строки не бывает — сигнатура «ещё не начали накапливать прямоугольник»,
#: чтобы не заводить `int | None` там, где это мешает статической типизации.
_NO_LINE = -1


#: Третий элемент локатора-bbox: ``"ocr"`` — строка со скан-страницы,
#: ``"user"`` — искусственный сегмент bbox-правки оператора (план
#: feat/highlight-coords-edits, К2). Обе формы несут готовый прямоугольник
#: вместо символьного диапазона и обрабатываются рендером одинаково —
#: у сегмента bbox-правки нет текстового слоя PDF, который можно искать.
_BBOX_LOCATOR_TAGS = frozenset({"ocr", "user"})


def _is_ocr_locator(locator: tuple[str | int | float, ...]) -> bool:
    return len(locator) == 7 and locator[2] in _BBOX_LOCATOR_TAGS


def _parse_ocr_locator(
    locator: tuple[str | int | float, ...],
) -> tuple[int, float, float, float, float]:
    _, page_num, _tag, x0, y0, x1, y1 = locator
    return int(page_num), int(x0) / 100.0, int(y0) / 100.0, int(x1) / 100.0, int(y1) / 100.0


def _entity_rect_ocr(
    seg_rect: pymupdf.Rect,
    seg_text_len: int,
    entity_start: int,
    entity_end: int,
) -> pymupdf.Rect:
    """Rect сущности из OCR-сегмента — линейная интерполяция по ширине строки."""
    if seg_text_len <= 0 or seg_rect.width <= 0:
        return seg_rect
    w = seg_rect.width
    x0 = seg_rect.x0 + w * entity_start / seg_text_len
    x1 = seg_rect.x0 + w * entity_end / seg_text_len
    return pymupdf.Rect(x0, seg_rect.y0, x1, seg_rect.y1)


#: Цвет текста лестницы отступления — только стиль `marker` держит светлый
#: фон и вставляет текст (тёмный текст на светлом); `blackbox` текста не
#: вставляет вовсе (план T2.2.2, шаг 1, отменяет решение пачки 5 плана
#: T2.2.1), поэтому цвет ему не нужен.
_MARKER_TEXT_COLOR: tuple[float, float, float] = (0.20, 0.20, 0.20)

#: Заливка подсвеченного варианта. Файл называется ``masked_highlight``, а
#: продуктовое требование — «заменены на маркеры и **подсвечены**»
#: (AGENTS.md, постановка). Белая заливка не подсвечивает ничего: на белой
#: странице область удаления неотличима от пустого места, и человек не
#: видит ни что было замаскировано, ни насколько длинным был оригинал.
#: Янтарный фон делает удалённую область видимой, а тёмно-серый текст
#: маркера (``_MARKER_TEXT_COLOR``) читается на нём без потери контраста.
_HIGHLIGHT_FILL = DEFAULT_PDF_HIGHLIGHT_FILL


class MarkerDoesNotFitError(ValueError):
    """Прямоугольник вырожденной площади — деградировать некуда.

    Поднимается только на прямоугольник нулевой или отрицательной площади
    — сигнал, что боксы посчитаны неверно выше по стеку, а не что место
    физически кончилось: любой настоящей площади прямоугольник разрешает
    лестница отступления текста (план М1) без падения.
    """


@dataclass(frozen=True, slots=True)
class RenderCollision:
    """Обрезка прямоугольника отменена — соседние строки перекрываются
    целиком (наложенный текст, штамп), план T2.2.2, шаг 3, п. 4.

    Текст всё равно удалён исходным (необрезанным) прямоугольником: утечка
    исходных данных дороже вёрстки, но молчать о том, что вёрстка могла
    пострадать, нельзя — отсюда отдельная запись, а не тихий фолбэк.
    """

    page: int
    line_id: int
    entity_type: str
    marker: str


@dataclass(frozen=True, slots=True)
class RenderOutcome:
    """Результат ``render_pdf_redacted`` целиком (план М1).

    ``replacements`` — те же замены плана, но с заполненной геометрией
    читаемой маски (``erase_regions``/``paint_regions``/``label_region``);
    для ``blackbox`` заполнены только ``erase_regions``/``paint_regions``
    — подпись для этого стиля не строится вовсе.
    ``markers`` — фактический результат вставки подписи, один элемент на
    каждую ``Replacement`` стиля ``marker`` (пусто для ``blackbox``).
    ``collisions`` — прямоугольники, для которых обрезка по соседней
    строке была отменена из-за полного перекрытия строк.
    """

    replacements: tuple[Replacement, ...]
    markers: tuple[MarkerRenderResult, ...]
    collisions: tuple[RenderCollision, ...]


@dataclass(frozen=True, slots=True)
class _LabelCandidate:
    """Безопасное поле подписи, baseline и кегль исходной строки."""

    erase_rect: pymupdf.Rect
    label_box: pymupdf.Rect
    line_y0: float
    source_font_size: float

    def __iter__(self):  # type: ignore[no-untyped-def]
        """Сохранить старый внутренний контракт распаковки пары rect/box."""
        return iter((self.erase_rect, self.label_box))

    def __getitem__(self, index: int) -> pymupdf.Rect:
        return (self.erase_rect, self.label_box)[index]


def _line_font_sizes(page: pymupdf.Page) -> dict[int, float]:
    """Вернуть обычный кегль каждой физической строки PDF.

    12.09.2026: метка обязана наследовать кегль заменённого текста, а не
    подстраиваться под ширину свободного поля. У строки с несколькими
    спанами берём медиану, чтобы один надстрочный индекс не менял кегль
    всей подписи.
    """
    sizes: dict[int, float] = {}
    line_id = 0
    for block in page.get_text("rawdict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            span_sizes = sorted(float(span["size"]) for span in line["spans"] if span["chars"])
            if span_sizes:
                sizes[line_id] = span_sizes[len(span_sizes) // 2]
            line_id += 1
    return sizes


@dataclass(slots=True)
class _PreparedMarkerBase:
    """Очищенный PDF до рисования marker-подписей для второго стиля.

    Копия сохраняется только на пару вызовов одного ``render_node``: сначала
    создаётся ``masked_highlight``, затем из той же уже отредактированной
    основы — ``masked_black``. Исходные глифы к этому моменту удалены именно
    ``apply_redactions()``, а не закрыты графикой.
    """

    source: pathlib.Path
    plan: MaskPlan
    pdf: bytes
    replacements: tuple[Replacement, ...]
    collisions: tuple[RenderCollision, ...]


# 11.09.2026: на 35-страничном edukirovsk оба стиля повторяли полный
# ``apply_redactions()``; второй стиль получает уже очищенную основу.
# Ровно один последний элемент ограничивает память и не смешивает документы
# разных запусков графа.
_PREPARED_MARKER_BASE: _PreparedMarkerBase | None = None


class _PageCharsCache:
    """Кэш ``page_chars`` и производных от него полос строк на один прогон
    рендера — план T2.2.2, шаги 2–3: страницы не меняются между заменами
    одного документа, а оба вызова небесплатные."""

    def __init__(self, doc: pymupdf.Document) -> None:
        self._doc = doc
        self._chars: dict[int, PageChars] = {}
        self._line_boxes: dict[int, dict[int, pymupdf.Rect]] = {}

    def chars(self, page_num: int) -> PageChars:
        if page_num not in self._chars:
            self._chars[page_num] = page_chars(self._doc[page_num])
        return self._chars[page_num]

    def line_boxes(self, page_num: int) -> dict[int, pymupdf.Rect]:
        if page_num not in self._line_boxes:
            self._line_boxes[page_num] = _line_boxes(self.chars(page_num))
        return self._line_boxes[page_num]


def _line_boxes(chars: PageChars, *, skip_space: bool = False) -> dict[int, pymupdf.Rect]:
    """Полоса каждой строки страницы — объединение боксов **всех** её
    символов, не только символов сущности (план T2.2.2, шаг 3, п. 2): так
    полоса не зависит от того, какой кусок строки маскируется.

    ``skip_space=True`` (план М6-1) исключает из результата строки, целиком
    состоящие из пробелов, — нужно только пост-редакционным «чужим» строкам
    в ``_free_extension_vertical``. ``apply_redactions`` умеет разрезать
    один физический ряд текста на несколько ``line_id`` при переписывании
    потока (диагностика: «ИНН <стёрто>          » — хвост из одних пробелов
    после стирания получает отдельный ``line_id`` с тем же вертикальным
    диапазоном, что и у собственной строки). Полоса, целиком состоящая из
    пробелов, не несёт ни одного видимого символа — преградой её считать
    нельзя, а без фильтра она давала вертикальный центр, совпадающий с
    центром собственной строки, и обрезала отступ пополам без единого
    настоящего соседа рядом (регресс на тесте с «И» перед «Незыблемовна» и
    на приёмочном сценарии ИНН — обе диагностики привели к этому фильтру).

    Фильтр отбрасывает строку **целиком**, а не отдельные пробельные
    символы внутри строки с настоящим текстом (регресс, найденный при
    разборе ``fix/r9-span-boundaries``, ``highlight_overlaps`` 315 → 1090:
    хвостовой пробел строки с реальным текстом нередко имеет более высокий
    или низкий бокс, чем у соседних букв — артефакт метрик шрифта PyMuPDF,
    не признак «здесь нет текста». Вырезание такого пробела из объединения
    укорачивало полосу строки с реальным текстом ниже её настоящей видимой
    границы, и середина полосы перекрытия (``_free_extension_vertical``)
    придвигалась к собственной строке ближе, чем позволяет последняя
    настоящая буква соседа — подпись заезжала на неё). Ни один из
    до-редакционных путей (``_trim_to_own_line``/``_quantize_erase_rect``)
    этот фильтр не запрашивает — они обязаны остаться на прежней геометрии
    побайтово (план М6-1, эталонный дамп ``compute_erase_geometry``)."""
    boxes: dict[int, pymupdf.Rect] = {}
    has_visible: dict[int, bool] = {}
    for index, (box, line_id) in enumerate(zip(chars.boxes, chars.line_ids, strict=True)):
        if box == _LINE_BREAK_RECT:
            continue
        boxes[line_id] = box if line_id not in boxes else boxes[line_id] | box
        if not chars.text[index].isspace():
            has_visible[line_id] = True
    if skip_space:
        boxes = {line_id: box for line_id, box in boxes.items() if has_visible.get(line_id, False)}
    return boxes


def _entity_rects(
    chars: PageChars, char_start: int, char_end: int
) -> list[tuple[int, pymupdf.Rect]]:
    """Прямоугольники сущности по срезу символьных боксов, один Rect на
    строку, со своим ``line_id`` (план T2.2.2, шаг 3, п. 1).

    Строка берётся из ``line_ids``, а не угадывается по координате: на
    реальном документе (Д10, диагностика по ``Ивановны``) угадывание по
    координате один раз уже схлопнуло прямоугольник в нулевую высоту, и
    сущность утекла.
    """
    groups: list[tuple[int, pymupdf.Rect]] = []
    current_line = _NO_LINE
    current_rect: pymupdf.Rect | None = None
    for box, line_id in zip(
        chars.boxes[char_start:char_end], chars.line_ids[char_start:char_end], strict=True
    ):
        if box == _LINE_BREAK_RECT:
            continue
        if current_rect is None or current_line != line_id:
            if current_rect is not None:
                groups.append((current_line, current_rect))
            current_line = line_id
            current_rect = pymupdf.Rect(box)
        else:
            current_rect |= box
    if current_rect is not None:
        groups.append((current_line, current_rect))
    return groups


def _rects_for_entity(
    cache: _PageCharsCache, page_num: int, seg_char_start: int, replacement: Replacement
) -> list[tuple[int, pymupdf.Rect]]:
    chars = cache.chars(page_num)
    abs_start = seg_char_start + replacement.entity.start
    abs_end = seg_char_start + replacement.entity.end
    return _entity_rects(chars, abs_start, abs_end)


def _trim_to_own_line(
    rect: pymupdf.Rect, own_line_id: int, line_boxes: dict[int, pymupdf.Rect]
) -> tuple[pymupdf.Rect, bool]:
    """Обрезать прямоугольник редакции серединой полосы перекрытия с
    соседними строками (Д10, план T2.2.2, шаг 3, пп. 3–4).

    Для каждой другой строки страницы, чей прямоугольник пересекается с
    ``rect`` и по горизонтали, и по вертикали, граница обрезаемого
    прямоугольника со стороны этой строки отодвигается до середины полосы
    перекрытия. Обход строк — по возрастанию ``line_id``, не по множеству
    (детерминизм).

    Возвращает ``(rect, collided)``. ``collided`` истинно, если после
    обрезки высота ушла в ноль или отрицательную величину — строки
    перекрываются целиком (наложенный текст, штамп): тогда обрезка
    отменяется и возвращается исходный (необрезанный) прямоугольник, а
    вызывающий обязан записать факт коллизии, а не промолчать о нём.
    """
    own_line = line_boxes[own_line_id]
    own_center = (own_line.y0 + own_line.y1) / 2
    y0, y1 = rect.y0, rect.y1
    for other_line_id in sorted(line_boxes):
        if other_line_id == own_line_id:
            continue
        other = line_boxes[other_line_id]
        if other.x1 <= rect.x0 or other.x0 >= rect.x1:
            continue  # не пересекается по горизонтали — не соседняя строка
        if other.y1 <= rect.y0 or other.y0 >= rect.y1:
            continue  # не пересекается по вертикали — не соседняя строка
        other_center = (other.y0 + other.y1) / 2
        if other_center < own_center:
            y0 = max(y0, (other.y1 + own_line.y0) / 2)
        else:
            y1 = min(y1, (other.y0 + own_line.y1) / 2)
    if y1 - y0 <= 0:
        return rect, True
    return pymupdf.Rect(rect.x0, y0, rect.x1, y1), False


def _free_extension_right(
    chars: PageChars,
    line_id: int,
    rect: pymupdf.Rect,
    abs_start: int,
    abs_end: int,
    line_box: pymupdf.Rect,
) -> float:
    """Самая правая граница, до которой подпись может продлиться вправо по
    той же строке, не задев ни одного чужого символа (план М1, правило 3).

    ``rect`` — уже обрезанный по своей строке эрейз-прямоугольник сущности.
    Преградой считается любой **непробельный** символ той же строки правее
    ``rect``, кроме символов самой сущности (``[abs_start, abs_end)``) — то
    есть и обычный сосед по строке, и другая сущность, ещё не обработанная
    в этом прогоне: геометрия строится по боксам исходного (ещё не
    изменённого) текста, поэтому такой сосед всегда виден. Пробелы
    преградой не считаются — это и есть то самое доказанно свободное
    место, ради которого функция существует, а не текст, который нельзя
    задевать. Без преграды граница — конец полосы строки (``line_box.x1``),
    не дальше физического текста строки (сами пробелы в объединение полосы
    уже вошли — дальше них строка не продолжается).

    «Та же строка» — не только тот же ``line_id``: два блока PyMuPDF на
    одной визуальной строке (соседние ячейки таблицы, форма с несколькими
    полями подряд) нумеруются как **разные** физические строки (план М5,
    диагностика на ``contract_pdf_02_school.pdf``, замена ``E223``, «ул.
    Банникова, 2»): счётчик строк в ``_walk_page`` сквозной по странице, но
    сбрасывается на границе блока, поэтому символ соседнего блока на той
    же высоте получает другой ``line_id``, хотя визуально стоит в упор
    справа. Расширение, отфильтрованное только по ``line_id``, такого
    соседа не видело и заезжало на него.

    Преградой поэтому считается и чужой ``line_id``, если его бокс
    пересекается по вертикали с самим прямоугольником ``rect`` — не с
    полосой всей строки (``line_box``): полоса строки шире прямоугольника
    сущности (включает выносные элементы других символов той же строки) и
    у неё, как и у соседних строк вообще (Д10, план T2.2.2), почти всегда
    находится сосед снизу или сверху со сравнимой высотой — их пересечение
    с полосой ловило бы соседнюю физическую строку целиком, а не соседний
    блок на **этой** строке (регресс на ``E19`` — символ следующей строки
    «и» ложно считался преградой). Прямоугольник сущности — куда более
    узкая и точная мера «эта строка», её боксом и сверяется независимая
    проверка сертификата (``validate/certificate.py::_has_real_neighbor_at``),
    поэтому граница здесь не должна расходиться с тем, что эта проверка
    считает объяснённым соседом.
    """
    limit = line_box.x1
    for index, box in enumerate(chars.boxes):
        if box == _LINE_BREAK_RECT:
            continue
        box_line = chars.line_ids[index]
        if box_line != line_id and (
            box.y1 <= rect.y0 + _GEOMETRY_EPS or box.y0 >= rect.y1 - _GEOMETRY_EPS
        ):
            continue  # другая строка PDF и другая визуальная высота — не преграда
        if abs_start <= index < abs_end:
            continue  # символ самой сущности — не преграда для расширения
        if chars.text[index].isspace():
            continue  # пробел — свободное место, а не преграда
        if box.x0 < rect.x1 - _GEOMETRY_EPS:
            continue  # символ левее прямоугольника — не мешает расширению вправо
        limit = min(limit, box.x0)
    return max(limit, rect.x1)


def _free_extension_vertical(
    line_boxes: dict[int, pymupdf.Rect],
    own_line: pymupdf.Rect,
    x0: float,
    x1: float,
    other_erase_rects: list[pymupdf.Rect] | tuple[pymupdf.Rect, ...] = (),
) -> tuple[float, float]:
    """Границы, до которых поле подписи может раздвинуться вверх и вниз, не
    заходя за середину полосы перекрытия с соседней строкой (план М5,
    вертикальная симметрия ``_free_extension_right``).

    ``own_line`` передаётся уже готовым прямоугольником, а не ``line_id`` для
    поиска в ``line_boxes`` (план М6-1): вызывающий (``_label_box_candidates``)
    строит ``line_boxes`` для соседей заново по **уже отредактированной**
    странице — ``apply_redactions`` перенумеровывает ``line_id`` (71→75 строк
    на ``contract_pdf_02_school.pdf``), поэтому старый ``own_line_id``,
    посчитанный до редактирования, не индексирует новый словарь. Собственная
    строка при этом не меняет положения от редактирования — она передаётся
    той же, что была посчитана в проходе 1 (``pre_line_boxes[line_id]``).

    ``line_boxes`` (пост-редакционные «чужие» строки) обязаны быть построены
    с ``_line_boxes(chars, skip_space=True)`` (план М6-1): полоса, целиком
    состоящая из пробелов — например, разрезанный ``apply_redactions`` хвост
    из одних пробелов, доставшийся отдельному ``line_id`` с тем же
    вертикальным диапазоном, что и у собственной строки, — не преграда и не
    должна участвовать в этом поиске вовсе; такая строка отбрасывается ещё в
    ``_line_boxes`` (не попадает в словарь).

    Остаток самой собственной строки (реальный текст той же физической
    строки, оставшийся после того, как сущность стёрта) отсеивается здесь —
    по доле пересечения с ``own_line`` по вертикали (``_OWN_LINE_OVERLAP_RATIO``),
    а не по точному равенству прямоугольников: `own_line` включает боксы ещё
    не стёртой сущности, а построенный по `post_chars` остаток той же строки
    их уже не содержит, поэтому прямоугольники не совпадают побайтово даже в
    простейшем случае.

    Раньше отступ на воздух под глифы (``-1`` сверху, ``+2`` снизу) считался
    безусловно, без единой проверки соседних строк — дефект, найденный
    заказчиком глазами 08.09.2026: жёлтая заливка заезжала на символ ``№``
    сразу за замаскированной датой, потому что расширение вправо
    (``_free_extension_right``) честно останавливалось у самой границы
    соседа, а этот отступ добавлялся **сверх** уже посчитанной безопасной
    границы.

    Граница строится по **полосам строк** (``line_boxes`` — объединение
    боксов всех символов строки, ``_line_boxes``), а не по отдельным
    символьным боксам, как расширение вправо: бокс глифа в PyMuPDF включает
    выносные элементы шрифта (ascender/descender), и у настоящих соседних
    строк документа они рутинно перекрываются на один-два пункта даже без
    какого-либо расширения подписи — та же причина, что и у Д10 (план
    T2.2.2, шаг 3), где обрезка эрейз-прямоугольника по отдельному символу
    неверна ровно по этой причине. Посимвольная проверка на реальном
    корпусе (``contract_pdf_02_school.pdf``) находила сотни таких «пересечений»
    там, где визуально ничего не видно — кончик выносного элемента чужой,
    физически далёкой строки, а не наш текст, наехавший на неё. Середина
    полосы перекрытия — тот же компромисс, что уже принят для
    ``erase_regions`` (``_trim_to_own_line``): не математическая гарантия
    нулевого перекрытия боксов глифов (она недостижима на реальном шаге
    строк), а гарантия того, что поле подписи не заходит на **чужую
    половину** промежутка — ровно то, что нужно, чтобы отступ не рос за
    счёт соседней строки, как раньше.

    ``other_erase_rects`` (план М6-1, регресс на ``contract_pdf_02_school.pdf``,
    стр. 26) — эрейз-регионы **других** замен той же страницы: к моменту
    вызова текст других замен ещё не вписан, их регион в ``post_chars``
    пуст, но не свободен — туда скоро впишется чужой маркер (см.
    докстринг ``_label_box_candidates``). Участвуют в поиске преград той же
    формулой, что и строки из ``line_boxes`` — включая фильтр «тот же
    физический ряд»: чужая замена на одной строке с нашей не должна
    ограничивать вертикальный отступ (это забота горизонтального
    расширения, не этой функции), только настоящая замена на другой строке.

    Возвращает ``(top_limit, bottom_limit)`` — абсолютные координаты,
    дальше которых заходить нельзя. Преграды сверху нет — ``-inf``
    (отступ вверх ничем не ограничен), преграды снизу нет — ``+inf``.
    """
    own_center = (own_line.y0 + own_line.y1) / 2
    own_height = own_line.y1 - own_line.y0
    top_limit = -math.inf
    bottom_limit = math.inf
    for other in (*line_boxes.values(), *other_erase_rects):
        vertical_overlap = min(other.y1, own_line.y1) - max(other.y0, own_line.y0)
        if own_height > 0 and vertical_overlap > own_height * _OWN_LINE_OVERLAP_RATIO:
            continue  # тот же физический ряд (остаток собственной строки
            # после редактирования) — не преграда сама себе
        if other.x1 <= x0 + _GEOMETRY_EPS or other.x0 >= x1 - _GEOMETRY_EPS:
            continue  # не пересекается по горизонтали с полем подписи
        other_center = (other.y0 + other.y1) / 2
        if other_center < own_center:
            top_limit = max(top_limit, (other.y1 + own_line.y0) / 2)  # преграда выше
        else:
            bottom_limit = min(bottom_limit, (other.y0 + own_line.y1) / 2)  # преграда ниже
    return top_limit, bottom_limit


def _quantize_erase_rect(
    chars: PageChars,
    line_id: int,
    rect: pymupdf.Rect,
    abs_start: int,
    abs_end: int,
    line_box: pymupdf.Rect,
) -> pymupdf.Rect:
    """Расширить прямоугольник удаления вправо до ближайшего кратного
    ``_ERASE_WIDTH_GRID`` (план М1, правило 5).

    Ширина прямоугольника редакции раньше один в один повторяла ширину
    удалённого текста — доказанный канал утечки (PoPETs 2023): по ширине
    закраски восстанавливается длина фамилии, ≈13 бит, один человек из
    8 000. Квант всегда округляется **вверх**: прямоугольник не имеет права
    стать уже оригинала, иначе виден незакрашенный хвост исходного текста.

    Верхняя граница расширения — та же безопасная граница, что и для
    подписи (``_free_extension_right``), построенная по боксам исходного
    (ещё не изменённого) текста: она никогда не заходит на чужой
    непробельный символ, будь то обычный сосед по строке или другая
    сущность, ещё не обработанная в этом прогоне. Если свободного места не
    хватает до полного кванта, прямоугольник останавливается на границе
    соседа — недостающий квант приносится в жертву целостности соседнего
    текста, а не наоборот: расширенный `erase_regions` идёт в
    ``add_redact_annot``/``apply_redactions``, и лишний захват стёр бы
    соседа безвозвратно.
    """
    width = rect.width
    if width <= 0:
        return rect
    quanta = math.ceil((width - _GEOMETRY_EPS) / _ERASE_WIDTH_GRID)
    target_x1 = rect.x0 + quanta * _ERASE_WIDTH_GRID
    safe_x1 = _free_extension_right(chars, line_id, rect, abs_start, abs_end, line_box)
    new_x1 = max(rect.x1, min(target_x1, safe_x1))
    return pymupdf.Rect(rect.x0, rect.y0, new_x1, rect.y1)


def _delete_annotations_in_redaction_regions(
    page: pymupdf.Page, redaction_regions: list[pymupdf.Rect]
) -> None:
    """Удалить виджеты и аннотации, чьё содержимое попало под редакцию.

    ``Page.apply_redactions()`` вычищает только content stream страницы.
    Текст в appearance-словаре PDF-виджета или аннотации при этом остаётся
    извлекаемым: в частности, электронная подпись хранит там ФИО и email.
    Геометрически корректная редакция такого текста поэтому не меняет файл
    вовсе. Если хотя бы одна запланированная область редакции пересекает
    прямоугольник виджета либо аннотации, удаляем объект целиком: частичная
    редакция его appearance stream не поддерживается PyMuPDF и оставила бы
    утечку. Сохранение с ``garbage=4`` ниже физически вычищает объект.

    Виджеты и обычные аннотации обходятся отдельно: PyMuPDF не включает
    виджет подписи в ``page.annots()``, но включает его текст в
    ``page.get_text()`` и, следовательно, в план и валидатор.
    """
    if not redaction_regions:
        return

    def overlaps(region: pymupdf.Rect) -> bool:
        return any(region.intersects(redaction) for redaction in redaction_regions)

    for widget in tuple(page.widgets() or ()):
        if overlaps(widget.rect):
            page.delete_widget(widget)
    for annot in tuple(page.annots() or ()):
        if overlaps(annot.rect):
            page.delete_annot(annot)


def compute_erase_geometry(
    source_path: str | pathlib.Path, plan: MaskPlan
) -> dict[str, tuple[PdfRegion, ...]]:
    """Пересчитать финальную (уже квантованную) геометрию ``erase_regions``
    по исходному PDF и плану, не открывая и не редактируя ни одного
    артефакта (план М3, сертификат обезличивания, пункт 3).

    Тот же путь вычисления, что и внутри ``render_pdf_redacted`` (группировка
    по странице → ``_rects_for_entity`` → ``_trim_to_own_line`` →
    ``_quantize_erase_rect``) — детерминированная функция только от
    ``(source_path, plan)``, поэтому её можно позвать заново уже после
    рендера, не читая геометрию из самого артефакта: ``apply_redactions``
    необратимо потребляет аннотацию редакции, восстановить прямоугольник из
    готового файла нельзя. Единственное игнорируемое поле —
    ``replacement.anchor.fmt != "pdf"`` (DOCX-замены плана пропускаются: у
    них нет координатной геометрии).

    Возвращает только ``erase_regions`` (не ``paint_regions``/``label_region``
    — те зависят от стиля рендера и лестницы отступления подписи, здесь не
    нужны). Ключ — ``Replacement.ref``, значение — один ``PdfRegion`` на
    строку сущности (обычно один, больше — только у сущности, перенесённой
    на новую строку).
    """
    doc = pymupdf.open(str(source_path))
    try:
        cache = _PageCharsCache(doc)
        by_page: dict[int, list[_PageJob]] = defaultdict(list)
        for replacement in plan.replacements:
            if replacement.anchor.fmt != "pdf":
                continue
            if _is_ocr_locator(replacement.anchor.locator):
                continue
            page_num, seg_start, _seg_end = _parse_locator(replacement.anchor.locator)
            rects = _rects_for_entity(cache, page_num, seg_start, replacement)
            by_page[page_num].append(
                _PageJob(replacement=replacement, seg_char_start=seg_start, rects=rects)
            )

        result: dict[str, tuple[PdfRegion, ...]] = {}
        for page_num in sorted(by_page):
            line_boxes = cache.line_boxes(page_num)
            chars = cache.chars(page_num)
            for job in by_page[page_num]:
                abs_start = job.seg_char_start + job.replacement.entity.start
                abs_end = job.seg_char_start + job.replacement.entity.end
                regions: list[PdfRegion] = []
                for line_id, rect in job.rects:
                    trimmed_rect, _collided = _trim_to_own_line(rect, line_id, line_boxes)
                    quantized_rect = _quantize_erase_rect(
                        chars, line_id, trimmed_rect, abs_start, abs_end, line_boxes[line_id]
                    )
                    regions.append(
                        PdfRegion(
                            page=page_num,
                            x0=quantized_rect.x0,
                            y0=quantized_rect.y0,
                            x1=quantized_rect.x1,
                            y1=quantized_rect.y1,
                        )
                    )
                result[job.replacement.ref] = tuple(regions)
        return result
    finally:
        doc.close()


def _fitting_size(
    font: pymupdf.Font,
    text: str,
    box: pymupdf.Rect,
    source_font_size: float,
    fallback_reason: str = "",
) -> float | None:
    """Первый кегль лестницы размеров (от крупного к минимальному), в
    который ``text`` помещается в ``box`` — та же формула, что и
    ``_ladder_fits``, только возвращает конкретный кегль, а не булево:
    ``compute_label_geometry`` обязана знать, каким именно кеглем реальный
    рендер напечатал бы текст, чтобы воспроизвести ровно ту же вставку на
    черновой странице (``count_highlight_overlaps``), а не гадать."""
    if box.width <= 0 or box.height <= 0:
        return None
    for size in _font_size_candidates(source_font_size):
        if (
            font.text_length(text, fontsize=size) <= box.width
            and box.height >= size * _LABEL_GLYPH_HEIGHT
        ):
            return size
    return None


def _font_size_candidates(source_font_size: float) -> tuple[float, ...]:
    """Сначала кегль источника, затем только допустимые ступени уменьшения.

    12.09.2026: уменьшение — именно аварийная деградация, а не обычный
    способ вписать метку в прямоугольник. Повтор не добавляем, когда
    исходный кегль уже равен одной из ступеней.
    """
    return (
        source_font_size,
        *tuple(size for size in _MARKER_FONT_SIZES if size != source_font_size),
    )


def compute_label_geometry(
    source_path: str | pathlib.Path, plan: MaskPlan
) -> dict[str, tuple[PdfRegion, str, float]]:
    """Пересчитать ``label_region``, фактически показанный текст и кегль
    каждой замены стиля ``marker`` по исходному PDF и плану, не открывая
    страницу на запись (план М5, метрика читаемости в воротах,
    ``eval.highlight_overlap_count``).

    Тот же путь вычисления, что и ``render_pdf_redacted`` при
    ``style="marker"`` (группировка по странице → ``_rects_for_entity`` →
    ``_trim_to_own_line`` → ``_quantize_erase_rect`` → ``add_redact_annot`` +
    ``apply_redactions`` → ``_label_box_candidates`` по уже отредактированной
    странице → ``_choose_group_rungs`` → тот же выбор конкретного кандидата,
    что и ``_place_label_fixed`` — первый по порядку документа, где выбранная
    ступень группы влезает) — детерминированная функция только от
    ``(source_path, plan)``, как и ``compute_erase_geometry``. Текст здесь не
    вставляется, но редактирование — да (план М6-1): страница открыта на
    **собственной** копии документа в памяти (``pymupdf.open(source_path)``
    внутри этой функции, ни разу не сохранённой на диск), поэтому
    редактирование этой копии не трогает ни файл на диске, ни артефакт,
    построенный отдельным вызовом ``render_pdf_redacted``. Без этого прохода
    граница подписи считалась бы по символам, которых уже нет на бумаге:
    ``apply_redactions`` при удалении части кернингового рана перерисовывает
    выживший хвост со смещением (доказано на ``contract_pdf_02_school.pdf``
    — «(далее» уезжает на 7 pt влево), и посчитанная по старым координатам
    граница накрывала соседа, реально сдвинувшегося на 12 pt ближе. Именно
    поэтому эту геометрию можно (и нужно) проверять против уже готового
    ВЫХОДНОГО артефакта отдельно — здесь она пересчитана тем же путём, что
    и сам рендер, а не подсмотрена в нём.

    Кегль возвращается вместе с регионом и текстом не просто для справки:
    ``count_highlight_overlaps`` воспроизводит ровно эту вставку
    (``box``, ``text``, ``fontsize``) на черновой странице, чтобы получить
    боксы настоящих глифов подписи — искать литеральную строку
    (``page.search_for``) в готовом артефакте нельзя, она не находит
    перенос длинного маркера на вторую визуальную строку внутри поля
    (легальный перенос, если высота поля позволяет).

    Возвращает по одному элементу ``(label_region, shown_text, font_size)``
    на ``Replacement``, для которой рендер печатает непустой текст. Замены
    со ступенью ``"blank"`` (печатать нечего) и DOCX-замены (``anchor.fmt
    != "pdf"``) в результат не попадают.
    """
    doc = pymupdf.open(str(source_path))
    try:
        font = pymupdf.Font(fontfile=str(_FONT_FILE))
        cache = _PageCharsCache(doc)
        by_page: dict[int, list[_PageJob]] = defaultdict(list)
        for replacement in plan.replacements:
            if replacement.anchor.fmt != "pdf":
                continue
            if _is_ocr_locator(replacement.anchor.locator):
                continue
            page_num, seg_start, _seg_end = _parse_locator(replacement.anchor.locator)
            rects = _rects_for_entity(cache, page_num, seg_start, replacement)
            by_page[page_num].append(
                _PageJob(replacement=replacement, seg_char_start=seg_start, rects=rects)
            )

        candidates_by_group: dict[str, list[list[_LabelCandidate]]] = defaultdict(list)
        candidates_by_ref: dict[str, list[_LabelCandidate]] = {}
        page_by_ref: dict[str, int] = {}

        for page_num in sorted(by_page):
            page = doc[page_num]
            pre_line_boxes = cache.line_boxes(page_num)
            pre_chars = cache.chars(page_num)
            line_font_sizes = _line_font_sizes(page)
            trimmed_jobs: list[tuple[_PageJob, list[tuple[int, pymupdf.Rect]]]] = []
            for job in by_page[page_num]:
                abs_start = job.seg_char_start + job.replacement.entity.start
                abs_end = job.seg_char_start + job.replacement.entity.end
                trimmed_rects: list[tuple[int, pymupdf.Rect]] = []
                for line_id, rect in job.rects:
                    trimmed_rect, _collided = _trim_to_own_line(rect, line_id, pre_line_boxes)
                    quantized_rect = _quantize_erase_rect(
                        pre_chars,
                        line_id,
                        trimmed_rect,
                        abs_start,
                        abs_end,
                        pre_line_boxes[line_id],
                    )
                    trimmed_rects.append((line_id, quantized_rect))
                trimmed_jobs.append((job, trimmed_rects))
            _delete_annotations_in_redaction_regions(
                page,
                [rect for _job, rects in trimmed_jobs for _line_id, rect in rects],
            )
            # Виджеты и аннотации удалены до добавления наших redaction
            # annotations: ``page.annots()`` включает последние, и обратный
            # порядок удалил бы запланированные области вместе с виджетом.
            for _job, rects in trimmed_jobs:
                for _line_id, rect in rects:
                    page.add_redact_annot(rect, fill=_HIGHLIGHT_FILL)
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)

            post_chars = page_chars(page)
            post_line_boxes = _line_boxes(post_chars, skip_space=True)
            suppressed_label_refs = _redundant_label_refs(
                [job for job, _rects in trimmed_jobs],
                {group.id: group for group in plan.groups},
            )
            for job, trimmed_rects in trimmed_jobs:
                other_erase_rects = _other_jobs_erase_rects(trimmed_jobs, job)
                candidates = _label_box_candidates(
                    post_chars,
                    pre_line_boxes,
                    post_line_boxes,
                    trimmed_rects,
                    other_erase_rects,
                    line_font_sizes,
                )
                candidates_by_group[job.replacement.group_id].append(candidates)
                if job.replacement.ref not in suppressed_label_refs:
                    candidates_by_ref[job.replacement.ref] = candidates
                    page_by_ref[job.replacement.ref] = page_num

        rung_by_group = _choose_group_rungs(font, plan.groups, candidates_by_group)

        result: dict[str, tuple[PdfRegion, str, float]] = {}
        for replacement in plan.replacements:
            candidates = candidates_by_ref.get(replacement.ref)
            if candidates is None:
                continue
            text, reason = rung_by_group.get(replacement.group_id, ("", "blank"))
            if not text:
                continue
            for candidate in candidates:
                erase_rect, label_box = candidate
                # Рендер выбирает узкую область, если уже выбранная общая
                # ступень в ней читаема. Расширение справа — резерв для
                # реального дефицита места, а не часть каждой подсветки.
                tight_box = pymupdf.Rect(erase_rect.x0, label_box.y0, erase_rect.x1, label_box.y1)
                tight_size = _fitting_size(
                    font, text, tight_box, candidate.source_font_size, reason
                )
                if tight_size is not None:
                    label_box, size = tight_box, tight_size
                else:
                    size = _fitting_size(font, text, label_box, candidate.source_font_size, reason)
                if size is None:
                    continue
                result[replacement.ref] = (
                    PdfRegion(
                        page=page_by_ref[replacement.ref],
                        x0=label_box.x0,
                        y0=label_box.y0,
                        x1=label_box.x1,
                        y1=label_box.y1,
                    ),
                    text,
                    size,
                )
                break
        return result
    finally:
        doc.close()


def _rects_overlap(a: pymupdf.Rect, b: pymupdf.Rect) -> bool:
    """Пересекаются ли ``a`` и ``b`` по площади, а не только по границе
    (план М5): символ, чей бокс лишь касается границы области подсветки в
    одной точке/по нулевой полосе, — не преграда, преграда — только
    настоящее перекрытие."""
    ix0, iy0 = max(a.x0, b.x0), max(a.y0, b.y0)
    ix1, iy1 = min(a.x1, b.x1), min(a.y1, b.y1)
    return (ix1 - ix0) > _GEOMETRY_EPS and (iy1 - iy0) > _GEOMETRY_EPS


#: Черновая страница для перепроверки настоящих боксов глифов подписи
#: (``_scratch_marker_boxes``) — заведомо больше любого разумного размера
#: страницы реального документа, чтобы ``insert_textbox`` ни на одном
#: ``label_region`` не наткнулась на край черновой страницы и не обрезала
#: текст там, где на настоящей странице обрезки не было бы.
_SCRATCH_PAGE_SIZE = 5000.0


def _scratch_marker_boxes(
    font: pymupdf.Font,
    box: pymupdf.Rect,
    text: str,
    size: float,
    *,
    align: int = pymupdf.TEXT_ALIGN_CENTER,
) -> list[pymupdf.Rect]:
    """Настоящие боксы глифов, которые оставит ``insert_text`` маркера.

    Ни поиск литеральной строки (``page.search_for``), ни сравнение по
    имени шрифта не годятся, чтобы отличить текст маркера от текста
    документа в уже готовом артефакте:

    - ``page.search_for`` ищет строку целиком и не находит её, если
      ``insert_textbox`` законно перенесла длинный маркер на вторую
      визуальную строку внутри поля (высота поля это разрешает) — реальный
      случай на ``contract_pdf_02_school.pdf`` («Сторона 32 Адрес»).
    - Имя шрифта в ``rawdict`` — внутреннее имя файла шрифта (PyMuPDF не
      сохраняет алиас, переданный ``insert_font``/``insert_textbox``), а
      не наш ``_FONT_NAME``: документ, набранный тем же файлом шрифта
      (например, синтетические PDF в тестах этого модуля), дал бы то же
      самое имя и для своего текста, и для нашей подписи.

    Надёжнее — воспроизвести ровно ту же вставку на черновой странице
    (тот же ``box`` в абсолютных координатах страницы, тот же ``text``,
    тот же ``size``, тот же файл шрифта) и прочитать её собственный
    ``rawdict``: черновая страница пуста, кроме этой одной вставки, поэтому
    всё, что на ней нашлось внутри ``box``, — заведомо наш текст, вне
    зависимости от того, на сколько визуальных строк он перенёсся.
    """
    scratch = pymupdf.open()
    try:
        page = scratch.new_page(width=_SCRATCH_PAGE_SIZE, height=_SCRATCH_PAGE_SIZE)
        page.insert_font(fontname=_FONT_NAME, fontfile=str(_FONT_FILE))
        text_width = font.text_length(text, fontsize=size)
        x0 = box.x0 if align == pymupdf.TEXT_ALIGN_LEFT else box.x0 + (box.width - text_width) / 2
        # `_try_ladder` вставляет текст по baseline исходной строки. Обычно
        # label_box начинается на 1pt выше неё; это именно тот безопасный
        # вертикальный отступ, а не baseline. Воспроизводим его здесь,
        # иначе край собственного глифа метрика ошибочно считает чужим.
        page.insert_text(
            (x0, box.y0 + 1.0 + size * font.ascender),
            text,
            fontname=_FONT_NAME,
            fontfile=str(_FONT_FILE),
            fontsize=size,
            color=_MARKER_TEXT_COLOR,
        )
        data = page.get_text("rawdict", clip=box)
        boxes: list[pymupdf.Rect] = []
        for block in data["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    boxes.extend(pymupdf.Rect(ch["bbox"]) for ch in span["chars"])
        return boxes
    finally:
        scratch.close()


def count_highlight_overlaps(
    plan: MaskPlan,
    source: str | pathlib.Path,
    artifact: str | pathlib.Path,
    *,
    highlight_background: str | None = DEFAULT_HIGHLIGHT_BACKGROUND,
) -> int:
    """Сколько раз область подсветки маркера в ``artifact`` накрыла живой,
    не свой символ (план М5, метрика ворот ``eval.highlight_overlap_count``).

    Геометрия подсветки (``label_region`` каждой замены) пересчитывается
    независимо от уже сохранённого артефакта тем же приёмом, что и
    сертификат обезличивания (план М3, ``compute_erase_geometry``):
    детерминированно по ``(source, plan)`` (``compute_label_geometry``), а
    не читается из самого рендера — так проверка не тавтологична коду,
    который эту геометрию построил.

    Мерить пересечение нужно по ``artifact`` (уже отрендеренному файлу), не
    по ``source``: в исходнике эрейз-регион ещё содержит собственный текст
    сущности, и его край дал бы ложное срабатывание. В артефакте эрейз-
    регион уже пуст (``apply_redactions`` стёр его), поэтому любой символ,
    зацепивший подсветку, — заведомо чужой.

    Текст самого маркера исключается не поиском литеральной строки в
    артефакте (``page.search_for``), а воспроизведением той же вставки на
    черновой странице (``_scratch_marker_boxes``) — см. её докстринг про
    то, почему ни поиск строки, ни имя шрифта в ``rawdict`` не годятся.
    """
    if parse_highlight_background(highlight_background) is None:
        return 0

    label_regions = compute_label_geometry(source, plan)
    if not label_regions:
        return 0

    font = pymupdf.Font(fontfile=str(_FONT_FILE))
    doc = pymupdf.open(str(artifact))
    try:
        pages_needed = {region.page for region, _text, _size in label_regions.values()}
        chars_by_page = {page_num: page_chars(doc[page_num]) for page_num in pages_needed}

        total = 0
        for region, text, size in label_regions.values():
            rect = pymupdf.Rect(region.x0, region.y0, region.x1, region.y1)
            marker_boxes = _scratch_marker_boxes(font, rect, text, size)
            # PyMuPDF rawdict не связывает глиф с оператором content stream:
            # если живой глиф лежит точно под подписью, его нельзя отличить
            # от нашей подписи только по bbox. До центровки историческая
            # метрика исключала левый след подписи; сохраняем его в
            # исключающем envelope, иначе та же неизменная область подсветки
            # получила бы ложный рост счётчика лишь от смены align.
            marker_boxes.extend(
                _scratch_marker_boxes(font, rect, text, size, align=pymupdf.TEXT_ALIGN_LEFT)
            )
            chars = chars_by_page[region.page]
            for index, box in enumerate(chars.boxes):
                if box == _LINE_BREAK_RECT:
                    continue
                if chars.text[index].isspace():
                    # Пробел под подсветкой не виден человеку — это то самое
                    # доказанно свободное место, ради которого расширение
                    # существует (``_free_extension_right``/
                    # ``_free_extension_vertical``), не преграда и не дефект.
                    continue
                if not _rects_overlap(box, rect):
                    continue
                if any(_rects_overlap(box, mbox) for mbox in marker_boxes):
                    continue  # символы самого маркера — не утечка и не дефект
                total += 1
        return total
    finally:
        doc.close()


def render_pdf_preview(
    source_path: str | pathlib.Path,
    dest_path: str | pathlib.Path,
    document: Document,
    entities: list[Entity],
) -> None:
    """Создать копию PDF с жёлтыми highlight-аннотациями; исходный текст сохранён."""
    source_path = pathlib.Path(source_path)
    dest_path = pathlib.Path(dest_path)
    doc = pymupdf.open(str(source_path))
    cache = _PageCharsCache(doc)
    for entity in entities:
        locator = document.segments[entity.segment_order].anchor.locator
        if _is_ocr_locator(locator):
            page_num, sx0, sy0, sx1, sy1 = _parse_ocr_locator(locator)
            seg = document.segments[entity.segment_order]
            seg_rect = pymupdf.Rect(sx0, sy0, sx1, sy1)
            rect = _entity_rect_ocr(seg_rect, len(seg.text), entity.start, entity.end)
            ocr_page = doc[page_num]
            annot = ocr_page.add_highlight_annot(rect)
            annot.update()
            continue
        page_num, seg_start, _seg_end = _parse_locator(locator)
        page = doc[page_num]
        chars = cache.chars(page_num)
        abs_start = seg_start + entity.start
        abs_end = seg_start + entity.end
        for _line_id, rect in _entity_rects(chars, abs_start, abs_end):
            annot = page.add_highlight_annot(rect)
            annot.update()
    doc.save(str(dest_path))
    doc.close()
    os.chmod(dest_path, 0o600)


@dataclass(slots=True)
class _PageJob:
    """Одна замена, привязанная к своей странице, до её редактирования."""

    replacement: Replacement
    seg_char_start: int
    rects: list[tuple[int, pymupdf.Rect]]  # (line_id, эрейз-прямоугольник до обрезки)


@dataclass(slots=True)
class _OcrPageJob:
    """Замена с OCR-локатором — геометрия из bbox сегмента, не из символьных боксов."""

    replacement: Replacement
    seg_rect: pymupdf.Rect
    entity_rect: pymupdf.Rect


def _insert_invisible_ocr_layer(page: pymupdf.Page, jobs: list[_OcrPageJob]) -> None:
    """Вставить невидимый текст маркеров на OCR-страницу (render_mode=3).

    Copy-paste из результирующего PDF даёт маркеры, а не исходный текст сущностей.
    Вызывается после apply_redactions, когда исходные пиксели уже стёрты.
    """
    page.insert_font(fontname=_FONT_NAME, fontfile=str(_FONT_FILE))
    for job in jobs:
        pos = pymupdf.Point(job.entity_rect.x0, job.entity_rect.y1)
        page.insert_text(
            pos,
            job.replacement.marker,
            fontname=_FONT_NAME,
            fontfile=str(_FONT_FILE),
            fontsize=1,
            render_mode=3,
        )


def _render_blackbox_from_prepared(
    prepared: _PreparedMarkerBase, dest_path: pathlib.Path
) -> RenderOutcome:
    """Собрать чёрный вариант из уже действительно отредактированной основы."""
    doc = pymupdf.open(stream=prepared.pdf, filetype="pdf")
    try:
        for replacement in prepared.replacements:
            for region in replacement.erase_regions:
                doc[region.page].draw_rect(
                    pymupdf.Rect(region.x0, region.y0, region.x1, region.y1),
                    color=(0.0, 0.0, 0.0),
                    fill=(0.0, 0.0, 0.0),
                    width=0,
                )
        doc.set_metadata({})
        doc.del_xml_metadata()
        doc.save(str(dest_path), garbage=4, deflate=True, no_new_id=True)
    finally:
        doc.close()
    os.chmod(dest_path, 0o600)
    return RenderOutcome(
        replacements=prepared.replacements,
        markers=(),
        collisions=prepared.collisions,
    )


def render_pdf_redacted(
    source_path: str | pathlib.Path,
    dest_path: str | pathlib.Path,
    document: Document,
    plan: MaskPlan,
    *,
    style: str = "marker",
    highlight_background: str | None = DEFAULT_HIGHLIGHT_BACKGROUND,
) -> RenderOutcome:
    """Удалить сущности из content-stream и вставить заглушки с маркерами плана.

    style="marker"   — выбранный фон (или без него) и подпись читаемой лестницы отступления
                       (план М1/М4): человекочитаемая полная форма →
                       только роль → компактная метка (``[Ф1]``) → голый
                       тип (``[Представитель]``) → пусто. Ступень выбирается
                       **один раз на группу**, по самому тесному из всех её
                       вхождений (план М4, пункт 3) — иначе одна и та же
                       сущность получала бы разные маркеры в разных местах
                       документа, что и было дефектом до этого плана.
    style="blackbox" — чёрный прямоугольник и ничего больше (план T2.2.2,
                       шаг 1): текст не вставляется ни одной ступенью.

    Прямоугольник **удаления** строится только из символов своей строки
    (``line_id`` из ``page_chars``) и обрезается серединой полосы
    перекрытия с соседними строками — план T2.2.2, шаг 3, лечит Д10.
    Прямоугольник **подписи** может быть шире — расширяется вправо по той
    же строке в доказанно свободное место (``_free_extension_right``), но
    сам прямоугольник удаления при этом не меняется ни на пункт (план М1,
    правило 3) — иначе ``apply_redactions`` стёр бы текст соседа.

    Подходящая строка для подписи многострочной сущности выбирается по
    наибольшей итоговой ширине поля подписи, а не всегда первая (план М1,
    правило 2) — первая строка ФИО через перенос может содержать один
    инициал. Подпись вставляется не более одного раза на ``Replacement``.

    ``document`` рендеру для поиска места замены не нужен — место уже
    посчитано один раз ``PlanAgent`` и приходит в ``plan.replacements[].anchor``.
    Параметр оставлен для единообразия сигнатуры с ``render_pdf_preview``.
    """
    if style not in ("marker", "blackbox"):
        raise ValueError(f"неизвестный стиль редактирования: {style!r}")
    highlight_background = parse_highlight_background(highlight_background)

    source_path = pathlib.Path(source_path)
    dest_path = pathlib.Path(dest_path)
    global _PREPARED_MARKER_BASE
    # 12.09.2026: нельзя строить blackbox из marker-основы: в ней уже есть
    # янтарная заливка redact-аннотаций. Чёрный вариант проходит собственный
    # этап построения redaction с чёрной заливкой, поэтому под ним физически
    # нет подсветки, а не просто закрыта поверх неё.
    _PREPARED_MARKER_BASE = None

    doc = pymupdf.open(str(source_path))
    font = pymupdf.Font(fontfile=str(_FONT_FILE))
    cache = _PageCharsCache(doc)
    groups_by_id: dict[str, MaskGroup] = {group.id: group for group in plan.groups}

    # Сгруппировать по страницам; боксы считаются до любых изменений документа.
    by_page: dict[int, list[_PageJob]] = defaultdict(list)
    ocr_by_page: dict[int, list[_OcrPageJob]] = defaultdict(list)
    for replacement in plan.replacements:
        if replacement.anchor.fmt != "pdf":
            continue
        locator = replacement.anchor.locator
        if _is_ocr_locator(locator):
            page_num, sx0, sy0, sx1, sy1 = _parse_ocr_locator(locator)
            seg = document.segments[replacement.entity.segment_order]
            seg_rect = pymupdf.Rect(sx0, sy0, sx1, sy1)
            e_rect = _entity_rect_ocr(
                seg_rect, len(seg.text), replacement.entity.start, replacement.entity.end
            )
            ocr_by_page[page_num].append(
                _OcrPageJob(replacement=replacement, seg_rect=seg_rect, entity_rect=e_rect)
            )
        else:
            page_num, seg_start, _seg_end = _parse_locator(locator)
            rects = _rects_for_entity(cache, page_num, seg_start, replacement)
            by_page[page_num].append(
                _PageJob(replacement=replacement, seg_char_start=seg_start, rects=rects)
            )

    fill_color = (0.0, 0.0, 0.0) if style == "blackbox" else pdf_fill_color(highlight_background)
    out_replacements: list[Replacement] = []
    markers: list[MarkerRenderResult] = []
    collisions: list[RenderCollision] = []
    # План М4, пункт 3: ступень лестницы выбирается один раз на группу, а не
    # на каждом вхождении отдельно — иначе широкое место печатало полную
    # форму, узкое — сокращение, и одна и та же сущность получала два разных
    # маркера в одном документе. Поэтому вставка текста для стиля `marker`
    # идёт в два прохода: сначала по всем страницам собираются кандидаты
    # подписи (геометрия, без рисования текста), затем для каждой группы
    # выбирается общая ступень по самому тесному из её вхождений, и только
    # потом эта фиксированная ступень вписывается в каждое вхождение.
    pending_labels: list[tuple[int, Replacement, tuple[PdfRegion, ...], list[_LabelCandidate]]] = []
    candidates_by_group: dict[str, list[list[_LabelCandidate]]] = defaultdict(list)
    suppressed_label_refs: set[str] = set()

    # Явная сортировка по номеру страницы — детерминизм не должен зависеть
    # от порядка обхода defaultdict (план T2.2.1, раздел «Детерминизм»).
    for page_num in sorted(by_page):
        jobs = by_page[page_num]
        page = doc[page_num]
        line_boxes = cache.line_boxes(page_num)
        chars = cache.chars(page_num)
        line_font_sizes = _line_font_sizes(page)
        trimmed_jobs: list[tuple[_PageJob, list[tuple[int, pymupdf.Rect]]]] = []
        for job in jobs:
            abs_start = job.seg_char_start + job.replacement.entity.start
            abs_end = job.seg_char_start + job.replacement.entity.end
            trimmed_rects: list[tuple[int, pymupdf.Rect]] = []
            for line_id, rect in job.rects:
                trimmed_rect, collided = _trim_to_own_line(rect, line_id, line_boxes)
                if collided:
                    collisions.append(
                        RenderCollision(
                            page=page_num,
                            line_id=line_id,
                            entity_type=job.replacement.entity.type,
                            marker=job.replacement.marker,
                        )
                    )
                # План М1, правило 5: ширина эрейз-прямоугольника квантуется
                # вверх по сетке 12 pt — расширение не заходит на чужой
                # текст (``_quantize_erase_rect`` использует ту же безопасную
                # границу, что и расширение подписи).
                quantized_rect = _quantize_erase_rect(
                    chars, line_id, trimmed_rect, abs_start, abs_end, line_boxes[line_id]
                )
                trimmed_rects.append((line_id, quantized_rect))
            trimmed_jobs.append((job, trimmed_rects))
        _delete_annotations_in_redaction_regions(
            page,
            [rect for _job, rects in trimmed_jobs for _line_id, rect in rects],
        )
        # См. тот же порядок в ``compute_label_geometry``: сначала убрать
        # внешний appearance stream, затем добавить собственные redaction
        # annotations, чтобы не удалить их при обходе ``page.annots()``.
        for _job, rects in trimmed_jobs:
            for _line_id, rect in rects:
                page.add_redact_annot(rect, fill=fill_color)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)

        if style == "blackbox":
            # Чёрный прямоугольник — просто чёрный (план T2.2.2, шаг 1):
            # лестница отступления текста для этого стиля не запускается.
            for job, trimmed_rects in trimmed_jobs:
                erase_regions = tuple(
                    PdfRegion(page=page_num, x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1)
                    for _line_id, r in trimmed_rects
                )
                out_replacements.append(
                    dataclasses.replace(
                        job.replacement, erase_regions=erase_regions, paint_regions=erase_regions
                    )
                )
            continue

        # План М6-1: геометрия подписи считается по уже отредактированной
        # странице, не по снимку, снятому до ``apply_redactions`` (тот всё
        # ещё лежит в ``cache``/``line_boxes``/``chars`` выше — он остаётся
        # источником для эрейз-геометрии, которая от редактирования не
        # меняется). Свежий, некэшированный ``page_chars`` — единственный
        # способ увидеть настоящий сдвиг хвоста кернингового рана, который
        # ``apply_redactions`` оставляет после себя (доказано на
        # ``contract_pdf_02_school.pdf`` — «(далее» уезжает на 7 pt влево).
        post_chars = page_chars(page)
        post_line_boxes = _line_boxes(post_chars, skip_space=True)
        suppressed_label_refs.update(
            _redundant_label_refs([job for job, _rects in trimmed_jobs], groups_by_id)
        )

        page.insert_font(fontname=_FONT_NAME, fontfile=str(_FONT_FILE))
        for job, trimmed_rects in trimmed_jobs:
            erase_regions = tuple(
                PdfRegion(page=page_num, x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1)
                for _line_id, r in trimmed_rects
            )
            other_erase_rects = _other_jobs_erase_rects(trimmed_jobs, job)
            candidates = _label_box_candidates(
                post_chars,
                line_boxes,
                post_line_boxes,
                trimmed_rects,
                other_erase_rects,
                line_font_sizes,
            )
            # Даже подавленный фрагмент участвует в выборе общей ступени:
            # 12.09.2026 видимая форма в легенде не должна меняться лишь
            # потому, что вложенный дубль перестали печатать вторым текстом.
            candidates_by_group[job.replacement.group_id].append(candidates)
            pending_labels.append((page_num, job.replacement, erase_regions, candidates))

    for page_num in sorted(ocr_by_page):
        ocr_jobs = ocr_by_page[page_num]
        page = doc[page_num]
        for job in ocr_jobs:
            page.add_redact_annot(job.entity_rect, fill=fill_color)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)

        if style == "blackbox":
            for job in ocr_jobs:
                e = job.entity_rect
                e_regions = (PdfRegion(page=page_num, x0=e.x0, y0=e.y0, x1=e.x1, y1=e.y1),)
                out_replacements.append(
                    dataclasses.replace(
                        job.replacement, erase_regions=e_regions, paint_regions=e_regions
                    )
                )
            continue

        page.insert_font(fontname=_FONT_NAME, fontfile=str(_FONT_FILE))
        for job in ocr_jobs:
            e = job.entity_rect
            e_regions = (PdfRegion(page=page_num, x0=e.x0, y0=e.y0, x1=e.x1, y1=e.y1),)
            label_box = pymupdf.Rect(e.x0, e.y0, job.seg_rect.x1, e.y1)
            candidates = [_LabelCandidate(e, label_box, e.y0, max(8.0, e.height))]
            candidates_by_group[job.replacement.group_id].append(candidates)
            pending_labels.append((page_num, job.replacement, e_regions, candidates))

    if style == "marker":
        # 11.09.2026: снимок берём после всех ``apply_redactions()``, но до
        # ``insert_textbox``. Поэтому blackbox получает тот же удалённый
        # content stream без marker-текста и не выполняет второй дорогой
        # проход редакции по 35 страницам.
        prepared_replacements = [
            dataclasses.replace(
                replacement,
                erase_regions=erase_regions,
                paint_regions=erase_regions,
            )
            for _page_num, replacement, erase_regions, _candidates in pending_labels
        ]
        order_by_ref = {
            replacement.ref: index for index, replacement in enumerate(plan.replacements)
        }
        prepared_replacements.sort(key=lambda item: order_by_ref[item.ref])
        _PREPARED_MARKER_BASE = _PreparedMarkerBase(
            source=source_path.resolve(),
            plan=plan,
            pdf=doc.tobytes(garbage=4, deflate=True, no_new_id=True),
            replacements=tuple(prepared_replacements),
            collisions=tuple(sorted(collisions, key=lambda item: (item.page, item.line_id))),
        )

    if style == "marker":
        rung_by_group = _choose_group_rungs(font, plan.groups, candidates_by_group)
        # 11.09.2026: два Shape на страницу вместо двух коммитов на каждую
        # из 457 подписей; порядок ключей фиксирован для детерминизма.
        dot_shapes: dict[tuple[int, str], pymupdf.Shape] = {}
        for page_num, replacement, erase_regions, candidates in pending_labels:
            if replacement.ref in suppressed_label_refs:
                out_replacements.append(
                    dataclasses.replace(
                        replacement,
                        erase_regions=erase_regions,
                        paint_regions=erase_regions,
                    )
                )
                continue
            page = doc[page_num]
            group = groups_by_id[replacement.group_id]
            label_region, marker_result = _place_label_fixed(
                page,
                font,
                candidates,
                replacement,
                rung_by_group[group.id],
                fill_color,
                dot_shapes,
                extra_dot_regions=erase_regions,
            )
            markers.append(marker_result)
            paint_regions = (*erase_regions, label_region) if fill_color is not None else ()
            out_replacements.append(
                dataclasses.replace(
                    replacement,
                    erase_regions=erase_regions,
                    paint_regions=paint_regions,
                    label_region=label_region,
                )
            )
        for key in sorted(dot_shapes):
            dot_shapes[key].finish(color=None, fill=_MARKER_TEXT_COLOR, width=0)
            dot_shapes[key].commit()

    for page_num in sorted(ocr_by_page):
        _insert_invisible_ocr_layer(doc[page_num], ocr_by_page[page_num])

    doc.set_metadata({})
    doc.del_xml_metadata()
    # PyMuPDF по умолчанию генерирует новый случайный /ID при каждом save(),
    # даже когда content stream совпадает. Сохраняем ID исходника: два прогона
    # одного документа тогда дают побайтово одинаковый PDF, как и отчёт.
    # К одному и тому же выводу независимо пришли обе ветки — OCR и маркеры.
    doc.save(str(dest_path), garbage=4, deflate=True, no_new_id=True)
    doc.close()
    os.chmod(dest_path, 0o600)
    # Сортировка по (page, line_id) — план T2.2.2, раздел «Детерминизм»:
    # порядок коллизий не должен зависеть от порядка plan.replacements.
    collisions.sort(key=lambda item: (item.page, item.line_id))
    # Порядок замен на выходе — порядок plan.replacements (текстовый), не
    # порядок обхода страниц (план T1.6/T1.8, раздел «Детерминизм»).
    order_by_ref = {replacement.ref: index for index, replacement in enumerate(plan.replacements)}
    out_replacements.sort(key=lambda item: order_by_ref[item.ref])
    markers.sort(key=lambda item: order_by_ref[item.ref])
    return RenderOutcome(
        replacements=tuple(out_replacements),
        markers=tuple(markers),
        collisions=tuple(collisions),
    )


def _parse_locator(locator: tuple[str | int | float, ...]) -> tuple[int, int, int]:
    """``("page", page_num, char_start, char_end)`` → номер страницы и
    символьный диапазон сегмента (план T2.2.1, шаг 8)."""
    _, page_num, char_start, char_end = locator
    return int(page_num), int(char_start), int(char_end)


def _ladder_fits(
    font: pymupdf.Font,
    candidate: _LabelCandidate,
    ladder: list[tuple[str, str]],
) -> bool:
    """Влезет ли хоть одна ступень в ``box`` — БЕЗ рисования на странице.

    Нужна отдельно от ``_try_ladder``, потому что выбор кандидата и
    закраска расширения обязаны произойти до вставки текста: закраска
    после вставки затёрла бы сам текст, а закраска до неудачной попытки
    оставляла бы на странице висячую полосу заливки. С белой заливкой
    такая полоса была невидима, с янтарной (``_HIGHLIGHT_FILL``) — это
    видимый мусор на странице.
    """
    box = candidate.label_box
    if box.width <= 0 or box.height <= 0:
        return False
    return any(
        font.text_length(text, fontsize=size) <= box.width
        and box.height >= size * _LABEL_GLYPH_HEIGHT
        for text, reason in ladder
        if text
        for size in _font_size_candidates(candidate.source_font_size)
    )


def _try_ladder(
    page: pymupdf.Page,
    font: pymupdf.Font,
    box: pymupdf.Rect,
    ladder: list[tuple[str, str]],
    *,
    baseline_y0: float | None = None,
    source_font_size: float = 8.0,
) -> tuple[str, str, float] | None:
    """Попробовать вписать в ``box`` первую подходящую ступень лестницы.

    Идём по ступеням от лучшей к худшей; на каждой — по размерам шрифта от
    крупного к минимальному (пол — 8 pt, план М1, правило 1). Пустая
    строка ступени (``""`` — «пусто») никогда не пробуется здесь: это
    сигнал вызывающему оставить подсветку без текста, а не настоящий текст
    для вставки. ``insert_textbox`` — единственный надёжный тест: он либо
    реально вписывает текст и возвращает остаток высоты, либо не пишет
    ничего и возвращает отрицательное число (план T2.2.1, риск Р6).

    Поднимает ``MarkerDoesNotFitError`` только на вырожденный (нулевой или
    отрицательной площади) прямоугольник — сигнал ошибки геометрии выше по
    стеку, а не «место кончилось».
    """
    if box.width <= 0 or box.height <= 0:
        raise MarkerDoesNotFitError(f"вырожденный прямоугольник {box!r} — вставлять текст некуда")
    for text, fallback_reason in ladder:
        if not text:
            continue
        for size in _font_size_candidates(source_font_size):
            if font.text_length(text, fontsize=size) > box.width:
                continue
            if box.height < size * _LABEL_GLYPH_HEIGHT:
                continue
            # 12.09.2026: все ступени получают baseline исходной строки.
            # `insert_textbox` сдвигал компактную подпись вниз и PyMuPDF
            # извлекал её отдельной строкой. Перенос здесь не нужен: ширина
            # и высота целой подписи проверены до рисования.
            marker_x0 = box.x0 + (box.width - font.text_length(text, fontsize=size)) / 2
            page.insert_text(
                (
                    marker_x0,
                    (baseline_y0 if baseline_y0 is not None else box.y0) + size * font.ascender,
                ),
                text,
                fontname=_FONT_NAME,
                fontfile=str(_FONT_FILE),
                fontsize=size,
                color=_MARKER_TEXT_COLOR,
            )
            reason = fallback_reason
            if size != source_font_size:
                reason = "+".join(part for part in (reason, "font_size_reduced") if part)
            return text, reason, size
    return None


def _marker_dot_counts(
    font: pymupdf.Font, box: pymupdf.Rect, text: str, size: float
) -> tuple[int, int]:
    """Вернуть число векторных точек слева и справа от центрированного маркера.

    Шаг между точками — настоящая ширина глифа ``.`` в шрифте подписи, а не
    подобранная константа. Точки остаются обычной графикой, а не текстом PDF:
    текстовый слой содержит только маркер и не получает искусственного
    заполнителя. Если суммарно помещается нечётное число точек, лишняя сначала
    назначается справа; если там для полного шага места всё же нет, кандидат
    отбрасывается. В симметричном поле это естественно даёт одинаковое число
    точек с обеих сторон.
    """
    dot_advance = font.text_length(".", fontsize=size)
    marker_width = font.text_length(text, fontsize=size)
    free_width = box.width - marker_width
    if dot_advance <= 0 or free_width <= _GEOMETRY_EPS:
        return 0, 0

    left_free = free_width / 2
    right_free = free_width - left_free
    total = math.floor((left_free + right_free + _GEOMETRY_EPS) / dot_advance)
    while total:
        left_count = total // 2
        right_count = total - left_count  # лишняя точка детерминированно справа
        if (
            left_count * dot_advance <= left_free + _GEOMETRY_EPS
            and right_count * dot_advance <= right_free + _GEOMETRY_EPS
        ):
            return left_count, right_count
        total -= 1
    return 0, 0


def _draw_marker_dots(
    page: pymupdf.Page,
    font: pymupdf.Font,
    box: pymupdf.Rect,
    text: str,
    size: float,
    dot_shapes: dict[tuple[int, str], pymupdf.Shape] | None = None,
    *,
    baseline_y0: float | None = None,
) -> None:
    """Нарисовать точки-заполнители в ``box`` без добавления их в text layer.

    Каждый кружок стоит на обычном шаге глифа ``.``. Последовательность
    центрируется в своей свободной половине, поэтому остаток от деления не
    сдвигает маркер и не создаёт визуального перекоса. Центр по вертикали
    соответствует базовой линии ``insert_textbox`` для текущего шрифта.
    """
    left_count, right_count = _marker_dot_counts(font, box, text, size)
    if not left_count and not right_count:
        return

    dot_advance = font.text_length(".", fontsize=size)
    marker_width = font.text_length(text, fontsize=size)
    left_free = (box.width - marker_width) / 2
    marker_x0 = box.x0 + left_free
    marker_x1 = marker_x0 + marker_width
    # insert_textbox начинает первую базовую линию на ascender * fontsize
    # от верхней границы. У точки DejaVu центр расположен чуть выше неё.
    dot_y = (baseline_y0 if baseline_y0 is not None else box.y0) + size * (font.ascender - 0.10)
    radius = min(dot_advance * 0.22, size * 0.09)
    # 11.09.2026: на edukirovsk-2018-659372 отдельный ``page.draw_circle``
    # на каждую точку доминировал в marker-рендере: каждый вызов коммитит
    # отдельный content stream. По одному Shape на сторону сохраняет те же
    # векторные круги двумя коммитами, а также различимые слева и справа
    # ранги, на которые опирается визуальная регрессия.

    def draw_run(start: float, available: float, count: int, side: str) -> None:
        if not count:
            return
        shape = (
            page.new_shape()
            if dot_shapes is None
            else dot_shapes.setdefault((page.number, side), page.new_shape())
        )
        run_width = count * dot_advance
        first_center = start + (available - run_width) / 2 + dot_advance / 2
        for index in range(count):
            shape.draw_circle(
                (first_center + index * dot_advance, dot_y),
                radius,
            )
        if dot_shapes is None:
            shape.finish(color=None, fill=_MARKER_TEXT_COLOR, width=0)
            shape.commit()

    draw_run(box.x0, left_free, left_count, "left")
    draw_run(marker_x1, box.x1 - marker_x1, right_count, "right")


def _other_jobs_erase_rects(
    trimmed_jobs: list[tuple[_PageJob, list[tuple[int, pymupdf.Rect]]]],
    current: _PageJob,
) -> list[pymupdf.Rect]:
    """Эрейз-регионы всех остальных замен той же страницы, кроме ``current``
    (план М6-1, регресс на ``contract_pdf_02_school.pdf``, стр. 26,
    ``highlight_overlaps`` 1090 → 813) — см. докстринг ``_label_box_candidates``
    про то, зачем расширению подписи нужно видеть их, хотя их текст в
    ``post_chars`` к этому моменту ещё пуст."""
    return [
        rect
        for job, rects in trimmed_jobs
        if job.replacement.ref != current.replacement.ref
        for _line_id, rect in rects
    ]


def _redundant_label_refs(jobs: list[_PageJob], groups_by_id: dict[str, MaskGroup]) -> set[str]:
    """Вернуть подписи вложенных фрагментов одного смыслового вхождения.

    Все найденные фрагменты всё равно редактируются: это единственный
    безопасный способ не оставить утечку. Но 12.09.2026 в преамбуле школьного
    контракта пересекающиеся NER/block-спаны одной роли печатали три
    ``[Исп.П1]`` подряд. Для читателя это три человека, хотя профиль один.
    Печатаем подпись только у первого фрагмента цепочки; соседние и вложенные
    фрагменты остаются подсвеченными, но не получают второй текст.
    """
    ordered = sorted(
        jobs,
        key=lambda job: (
            job.seg_char_start + job.replacement.entity.start,
            -(job.seg_char_start + job.replacement.entity.end),
            job.replacement.ref,
        ),
    )
    retained: list[tuple[_PageJob, int, int, MaskGroup]] = []
    redundant: set[str] = set()
    for job in ordered:
        group = groups_by_id[job.replacement.group_id]
        start = job.seg_char_start + job.replacement.entity.start
        end = job.seg_char_start + job.replacement.entity.end
        for _previous, previous_start, previous_end, previous_group in retained:
            same_label = group.canonical_label == previous_group.canonical_label
            same_profile = (
                group.profile_id is not None and group.profile_id == previous_group.profile_id
            )
            if same_label and start <= previous_end + 1:
                redundant.add(job.replacement.ref)
                break
            if same_profile and previous_start <= start and end <= previous_end:
                redundant.add(job.replacement.ref)
                break
        else:
            retained.append((job, start, end, group))
    return redundant


def _label_box_candidates(
    post_chars: PageChars,
    pre_line_boxes: dict[int, pymupdf.Rect],
    post_line_boxes: dict[int, pymupdf.Rect],
    trimmed_rects: list[tuple[int, pymupdf.Rect]],
    other_erase_rects: list[pymupdf.Rect] | tuple[pymupdf.Rect, ...] = (),
    line_font_sizes: dict[int, float] | None = None,
) -> list[_LabelCandidate]:
    """Кандидаты (эрейз-прямоугольник, поле подписи) одного вхождения.

    Чистая геометрия, без рисования на странице — план М4 выбирает ступень
    лестницы один раз на группу, по самому тесному из всех её вхождений
    (``_choose_group_rungs``), а для этого нужны кандидаты **всех**
    вхождений группы заранее, до того как рендер решит, что печатать.

    Кандидаты — все прямоугольники сущности (по одному на строку), каждый
    расширенный вправо в доказанно свободное место своей строки
    (``_free_extension_right``) — план М1, правило 3. Отступ на воздух под
    глифы (сверху и снизу) — доказанно свободным местом по той же логике
    (``_free_extension_vertical``, план М5): раньше эти пункты добавлялись
    безусловно поверх уже посчитанной безопасной границы, из-за чего
    заливка заезжала на живой символ соседней строки или строки-соседа
    справа (заказчик нашёл это глазами 08.09.2026 — «№» сразу за
    замаскированной датой).

    План М6-1: свободные границы (и справа, и сверху/снизу) ищутся по
    ``post_chars``/``post_line_boxes`` — символьным боксам страницы **после**
    ``apply_redactions``, а не до него. ``apply_redactions`` при удалении
    части кернингового рана перерисовывает выживший хвост со смещением
    (доказано на ``contract_pdf_02_school.pdf`` — «(далее» уезжает на 7 pt
    влево), поэтому граница, посчитанная по дореди­акционным боксам, была
    честной для документа, которого уже нет на диске: реальный сосед в
    сохранённом файле мог стоять на 12 pt ближе, и подпись накрывала его
    целиком видимым образом. ``pre_line_boxes`` (полоса строки **до**
    редактирования, посчитанная в проходе 1 вместе с ``trimmed_rects``)
    остаётся источником для собственной строки — её положение
    редактирование не двигает, только переписывает содержимое соседей —
    и передаётся ``_free_extension_vertical`` готовым прямоугольником, а не
    ``line_id``: тот же ``line_id`` после редактирования индексирует уже
    другую строку (``line_id`` физически перенумерован, план М6-1).

    Символы самой сущности в ``post_chars`` уже не существуют — их стёр
    ``apply_redactions`` — поэтому пропускать диапазон ``[abs_start,
    abs_end)`` (как это делает ``_quantize_erase_rect`` для до-редакционных
    боксов) здесь не нужно: единственный признак «это не преграда» —
    положение левее эрейз-прямоугольника, а не совпадение индекса символа
    с самой сущностью. ``_free_extension_right`` получает поэтому заведомо
    пустой диапазон ``(0, 0)`` и часовой (никогда не встречающийся в
    ``post_chars``) ``_NO_LINE`` вместо ``line_id`` — сравнение «та же
    строка» после редактирования не имеет смысла (то же перенумерование),
    остаётся только геометрический критерий — пересечение по вертикали с
    самим ``erase_rect``, который редактирование не двигает.

    ``other_erase_rects`` — эрейз-регионы **других** замен той же страницы
    (план М6-1, регресс на ``contract_pdf_02_school.pdf``, стр. 26, группа
    «Муниципальное автономное...», найденный при разборе
    ``highlight_overlaps`` 1090 → 813): к моменту вызова этой функции текст
    других замен ещё не вписан (ступень лестницы выбирается один раз на
    группу уже после того, как собраны кандидаты всех замен страницы,
    план М4), поэтому их эрейз-регион в ``post_chars`` уже пуст — но не
    свободен, туда скоро впишется чужой маркер. Без этого списка расширение
    видело там только пустоту и заезжало в чужую область, а не на реальный
    символ — так наложение просто переносилось с исходного текста соседа
    на будущий маркер соседа, оставаясь тем же дефектом читаемости.
    """
    for _line_id, rect in trimmed_rects:
        if rect.width <= 0 or rect.height <= 0:
            raise MarkerDoesNotFitError(
                f"вырожденный прямоугольник {rect!r} — вставлять текст некуда"
            )

    candidates: list[_LabelCandidate] = []
    for line_id, erase_rect in trimmed_rects:
        own_line = pre_line_boxes[line_id]
        # Поле подписи вправе занять пробелы справа от стёртой сущности,
        # но только до первого *живого* глифа на странице после redaction.
        # В предыдущем варианте это расширение отключили полностью: оно
        # устранило наложение, но сделало четыре широких поля на arkhschool
        # пустыми. Причиной наложения был не сам доказанно свободный участок,
        # а добавочные пункты за возвращённой границей. Здесь никаких
        # арифметических припусков после _free_extension_right нет.
        label_x1 = _free_extension_right(post_chars, _NO_LINE, erase_rect, 0, 0, own_line)
        for other in other_erase_rects:
            if other.y1 <= erase_rect.y0 + _GEOMETRY_EPS or other.y0 >= erase_rect.y1 - (
                _GEOMETRY_EPS
            ):
                continue
            if other.x0 < erase_rect.x1 - _GEOMETRY_EPS:
                continue
            label_x1 = min(label_x1, other.x0)
        label_x1 = max(label_x1, erase_rect.x1)
        top_limit, bottom_limit = _free_extension_vertical(
            post_line_boxes, own_line, erase_rect.x0, label_x1, other_erase_rects
        )
        # 11.09.2026: соседняя замена — не свободное место для отступа
        # подписи. Средина полосы пересечения строк безопасна для удаления
        # исходных глифов, но оставляла 0.46--0.55 pt, в которые заходил
        # маркер следующего поля (БИК/счёт/КПП в школьном договоре). Для
        # двух масок нужна строгая граница самого erase-региона: иначе
        # подсветка одной маски накрывает живые глифы маркера другой.
        for other in other_erase_rects:
            if other.x1 <= erase_rect.x0 + _GEOMETRY_EPS or other.x0 >= label_x1 - (_GEOMETRY_EPS):
                continue
            if other.y1 <= erase_rect.y0 + _GEOMETRY_EPS:
                top_limit = max(top_limit, other.y1)
            elif other.y0 >= erase_rect.y1 - _GEOMETRY_EPS:
                bottom_limit = min(bottom_limit, other.y0)
        # Желаемый отступ на воздух под глифы — не безусловный, а зажатый
        # доказанно свободной вертикальной границей (план М5): без соседа
        # рядом отступ остаётся тем же, что и раньше (``-1``/``+2``).
        label_y0 = max(erase_rect.y0 - 1, top_limit)
        label_y1 = min(erase_rect.y1 + 2, bottom_limit)
        label_box = pymupdf.Rect(erase_rect.x0, label_y0, label_x1, label_y1)
        candidates.append(
            _LabelCandidate(
                erase_rect,
                label_box,
                _label_baseline_y0(own_line, post_line_boxes),
                (line_font_sizes or {}).get(line_id, max(8.0, own_line.height)),
            )
        )
    return candidates


def _label_baseline_y0(
    own_line: pymupdf.Rect,
    post_line_boxes: dict[int, pymupdf.Rect],
) -> float:
    """Вернуть baseline именно исходной строки заменённого значения.

    12.09.2026: после удаления строки, состоящей только из PII, её нет в
    ``post_line_boxes``. Нельзя подменять её предыдущей живой строкой:
    метка тогда накладывается на заголовок поля (например, «ЗАКАЗЧИК:»),
    как в реквизитах arkhschool-68-183.pdf. Отдельная строка метки лучше
    наложения и сохраняет координату удалённого значения.
    """
    del post_line_boxes
    return own_line.y0


def _rung_fits_everywhere(
    font: pymupdf.Font,
    text: str,
    fallback_reason: str,
    occurrences: list[list[_LabelCandidate]],
) -> bool:
    """``text`` обязан поместиться хоть в одном кандидате **каждого** вхождения."""
    return all(
        any(
            font.text_length(text, fontsize=size) <= label_box.width
            and label_box.height >= size * _LABEL_GLYPH_HEIGHT
            for candidate in occurrence
            for _erase_rect, label_box in (candidate,)
            for size in _font_size_candidates(candidate.source_font_size)
        )
        for occurrence in occurrences
    )


def _choose_group_rungs(
    font: pymupdf.Font,
    groups: tuple[MaskGroup, ...],
    candidates_by_group: dict[str, list[list[_LabelCandidate]]],
) -> dict[str, tuple[str, str]]:
    """Выбрать одну ступень лестницы на группу (план М4, пункт 3).

    Дефект, который здесь лечится: раньше ступень выбиралась на каждом
    вхождении отдельно, поэтому широкое место печатало полную форму, а
    узкое — сокращение, и одна и та же сущность получала два разных
    маркера в одном документе — прямое нарушение инварианта согласованности
    псевдонимов (AGENTS.md). Лечение — пробовать ступени от самой полной к
    самой короткой (``marker_ladder``) и взять первую, что помещается **во
    всех** вхождениях группы разом; она печатается везде. Одно узкое
    вхождение честно огрубляет метку по всему документу — расшифровку даёт
    легенда отчёта (``report/payload.py::marker_legend``).

    Группа без единого вхождения среди собранных кандидатов (сюда рендер не
    дошёл вовсе) получает ``("", "blank")`` — печатать для неё нечего.
    """
    result: dict[str, tuple[str, str]] = {}
    used_by_label: dict[str, str] = {}
    occurrences_by_canonical: dict[str, list[list[_LabelCandidate]]] = defaultdict(list)
    first_group_by_canonical: dict[str, MaskGroup] = {}
    for group in groups:
        canonical = group.canonical_label
        occurrences_by_canonical[canonical].extend(candidates_by_group.get(group.id, []))
        first_group_by_canonical.setdefault(canonical, group)
    for group in groups:
        canonical = group.canonical_label
        if canonical in result:
            result[group.id] = result[canonical]
            continue
        occurrences = occurrences_by_canonical[canonical]
        chosen: tuple[str, str] = ("", "blank")
        if occurrences:
            for text, reason in marker_ladder(first_group_by_canonical[canonical]):
                if not text:
                    continue
                # 12.09.2026: разные PlanAgent-группы с одной канонической
                # ролью стороны обязаны показать одну подпись. Занятой текст
                # запрещён только другой канонической метке, иначе легенда
                # превращает одного Исполнителя в несколько «а/б/в».
                if text in used_by_label and used_by_label[text] != canonical:
                    continue
                if _rung_fits_everywhere(font, text, reason, occurrences):
                    chosen = (text, reason)
                    break
            if not chosen[0]:
                # Одно экстремально узкое вхождение не должно превращать
                # широкое и пригодное для чтения вхождение той же группы в
                # пустую жёлтую полосу. В таком случае сохраняем одну
                # ступень группы, но печатаем её только там, где она реально
                # помещается; узкое место остаётся без второй, ложной метки.
                for text, reason in marker_ladder(first_group_by_canonical[canonical]):
                    if text and any(
                        _rung_fits_everywhere(font, text, reason, [occurrence])
                        for occurrence in occurrences
                    ):
                        chosen = (text, reason)
                        break
        result[group.id] = chosen
        result[canonical] = chosen
        if chosen[0]:
            used_by_label[chosen[0]] = canonical
    return result


def _place_label_fixed(
    page: pymupdf.Page,
    font: pymupdf.Font,
    candidates: list[_LabelCandidate],
    replacement: Replacement,
    rung: tuple[str, str],
    fill_color: tuple[float, float, float] | None,
    dot_shapes: dict[tuple[int, str], pymupdf.Shape] | None = None,
    extra_dot_regions: tuple[PdfRegion, ...] = (),
) -> tuple[PdfRegion, MarkerRenderResult]:
    """Вписать в это вхождение ступень, уже выбранную для всей группы.

    В отличие от прежнего ``_place_label``, ступень (``rung``) больше не
    подбирается здесь — она одна на группу (``_choose_group_rungs``), общая
    для всех вхождений. Задача этой функции — только найти, в какой из
    кандидатов **этого** вхождения она влезет, в документном порядке (план
    М1, правило 2: не обязательно первая строка — первая строка сущности,
    разорванной переносом, может содержать один инициал).
    """
    text, reason = rung
    if text:
        single_rung = [(text, reason)]
        for candidate in candidates:
            erase_rect, label_box = candidate
            tight_box = pymupdf.Rect(erase_rect.x0, label_box.y0, erase_rect.x1, label_box.y1)
            tight_candidate = dataclasses.replace(candidate, label_box=tight_box)
            # Фон в свободных пробелах нужен лишь когда без него выбранная
            # групповая ступень не помещается. Так безопасное расширение не
            # раздувает каждую жёлтую полосу и не повышает метрику наложений.
            candidate_to_draw = (
                tight_candidate if _ladder_fits(font, tight_candidate, single_rung) else candidate
            )
            erase_rect, label_box = candidate_to_draw
            if not _ladder_fits(font, candidate_to_draw, single_rung):
                continue
            if fill_color is not None and label_box.x1 > erase_rect.x1 + _GEOMETRY_EPS:
                # Расширение вправо доказанно свободно
                # (``_free_extension_right``) — красим его отдельно от
                # удаления (план М1, правило 3): сама область удаления при
                # этом не меняется ни на пункт.
                page.draw_rect(
                    pymupdf.Rect(erase_rect.x1, label_box.y0, label_box.x1, label_box.y1),
                    color=fill_color,
                    fill=fill_color,
                    width=0,
                )
            outcome = _try_ladder(
                page,
                font,
                label_box,
                single_rung,
                baseline_y0=candidate.line_y0,
                source_font_size=candidate.source_font_size,
            )
            if outcome is None:
                continue
            shown_text, fallback_reason, size = outcome
            _draw_marker_dots(
                page,
                font,
                label_box,
                shown_text,
                size,
                dot_shapes=dot_shapes,
                baseline_y0=candidate.line_y0,
            )
            # Точки на остальных строках этой сущности (многострочный случай).
            # Сравниваем с erase_rect (исходный, до расширения), а не с
            # label_box: label_box может слегка залезать на соседнюю строку
            # по вертикали (_free_extension_vertical) и тогда ложно совпадёт.
            for er in extra_dot_regions:
                er_box = pymupdf.Rect(er.x0, er.y0, er.x1, er.y1)
                if not (er_box & erase_rect).is_empty:
                    continue  # строка метки — точки уже нарисованы выше
                _draw_marker_dots(page, font, er_box, "", size, dot_shapes=dot_shapes)
            region = PdfRegion(
                page=page.number,
                x0=label_box.x0,
                y0=label_box.y0,
                x1=label_box.x1,
                y1=label_box.y1,
            )
            return region, MarkerRenderResult(
                ref=replacement.ref,
                group_id=replacement.group_id,
                page=page.number,
                font_size=size,
                shown_label=shown_text,
                fallback_reason=fallback_reason,
            )
        # Ступень выбрана для широкого вхождения группы, но это конкретное
        # поле уже минимально и её не вмещает. Не рисуем в нём второй,
        # другой маркер и не расширяем заливку ради текста.
        erase_rect, _label_box = candidates[0]
        region = PdfRegion(
            page=page.number, x0=erase_rect.x0, y0=erase_rect.y0, x1=erase_rect.x1, y1=erase_rect.y1
        )
        return region, MarkerRenderResult(
            ref=replacement.ref,
            group_id=replacement.group_id,
            page=page.number,
            font_size=0.0,
            shown_label="",
            fallback_reason="blank",
        )

    erase_rect, _label_box = candidates[0]
    region = PdfRegion(
        page=page.number, x0=erase_rect.x0, y0=erase_rect.y0, x1=erase_rect.x1, y1=erase_rect.y1
    )
    return region, MarkerRenderResult(
        ref=replacement.ref,
        group_id=replacement.group_id,
        page=page.number,
        font_size=0.0,
        shown_label="",
        fallback_reason="blank",
    )
