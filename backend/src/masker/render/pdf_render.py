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
  свободное место, не «на глаз».

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
#: Нулевой прямоугольник — сигнатура символа-склейки строк, который
#: `page_chars`/`ingest_pdf` вставляют строго на границе физической строки
#: внутри блока (план T2.2.1, шаг 8). Настоящие пробелы получают от
#: PyMuPDF собственный ненулевой бокс — совпадение с этим сигналом
#: означает «здесь линия обрывается», а не «здесь пробел».
_LINE_BREAK_RECT = pymupdf.Rect(0.0, 0.0, 0.0, 0.0)
#: Строки не бывает — сигнатура «ещё не начали накапливать прямоугольник»,
#: чтобы не заводить `int | None` там, где это мешает статической типизации.
_NO_LINE = -1

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
_HIGHLIGHT_FILL: tuple[float, float, float] = (1.0, 0.87, 0.40)


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


def _line_boxes(chars: PageChars) -> dict[int, pymupdf.Rect]:
    """Полоса каждой строки страницы — объединение боксов **всех** её
    символов, не только символов сущности (план T2.2.2, шаг 3, п. 2): так
    полоса не зависит от того, какой кусок строки маскируется."""
    boxes: dict[int, pymupdf.Rect] = {}
    for box, line_id in zip(chars.boxes, chars.line_ids, strict=True):
        if box == _LINE_BREAK_RECT:
            continue
        boxes[line_id] = box if line_id not in boxes else boxes[line_id] | box
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
    """
    limit = line_box.x1
    for index, (box, box_line) in enumerate(zip(chars.boxes, chars.line_ids, strict=True)):
        if box_line != line_id or box == _LINE_BREAK_RECT:
            continue
        if abs_start <= index < abs_end:
            continue  # символ самой сущности — не преграда для расширения
        if chars.text[index].isspace():
            continue  # пробел — свободное место, а не преграда
        if box.x0 < rect.x1 - _GEOMETRY_EPS:
            continue  # символ левее прямоугольника — не мешает расширению вправо
        limit = min(limit, box.x0)
    return max(limit, rect.x1)


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
        page_num, seg_start, _seg_end = _parse_locator(
            document.segments[entity.segment_order].anchor.locator
        )
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


def render_pdf_redacted(
    source_path: str | pathlib.Path,
    dest_path: str | pathlib.Path,
    document: Document,
    plan: MaskPlan,
    *,
    style: str = "marker",
) -> RenderOutcome:
    """Удалить сущности из content-stream и вставить заглушки с маркерами плана.

    style="marker"   — светлый фон и подпись читаемой лестницы отступления
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

    source_path = pathlib.Path(source_path)
    dest_path = pathlib.Path(dest_path)
    doc = pymupdf.open(str(source_path))
    font = pymupdf.Font(fontfile=str(_FONT_FILE))
    cache = _PageCharsCache(doc)
    groups_by_id: dict[str, MaskGroup] = {group.id: group for group in plan.groups}

    # Сгруппировать по страницам; боксы считаются до любых изменений документа.
    by_page: dict[int, list[_PageJob]] = defaultdict(list)
    for replacement in plan.replacements:
        page_num, seg_start, _seg_end = _parse_locator(replacement.anchor.locator)
        rects = _rects_for_entity(cache, page_num, seg_start, replacement)
        by_page[page_num].append(
            _PageJob(replacement=replacement, seg_char_start=seg_start, rects=rects)
        )

    fill_color = (0.0, 0.0, 0.0) if style == "blackbox" else _HIGHLIGHT_FILL
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
    pending_labels: list[
        tuple[int, Replacement, tuple[PdfRegion, ...], list[tuple[pymupdf.Rect, pymupdf.Rect]]]
    ] = []
    candidates_by_group: dict[str, list[list[tuple[pymupdf.Rect, pymupdf.Rect]]]] = defaultdict(
        list
    )

    # Явная сортировка по номеру страницы — детерминизм не должен зависеть
    # от порядка обхода defaultdict (план T2.2.1, раздел «Детерминизм»).
    for page_num in sorted(by_page):
        jobs = by_page[page_num]
        page = doc[page_num]
        line_boxes = cache.line_boxes(page_num)
        chars = cache.chars(page_num)
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
                page.add_redact_annot(quantized_rect, fill=fill_color)
                trimmed_rects.append((line_id, quantized_rect))
            trimmed_jobs.append((job, trimmed_rects))
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

        page.insert_font(fontname=_FONT_NAME, fontfile=str(_FONT_FILE))
        for job, trimmed_rects in trimmed_jobs:
            erase_regions = tuple(
                PdfRegion(page=page_num, x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1)
                for _line_id, r in trimmed_rects
            )
            candidates = _label_box_candidates(
                cache, page_num, job.seg_char_start, job.replacement, trimmed_rects
            )
            candidates_by_group[job.replacement.group_id].append(candidates)
            pending_labels.append((page_num, job.replacement, erase_regions, candidates))

    if style == "marker":
        rung_by_group = _choose_group_rungs(font, plan.groups, candidates_by_group)
        for page_num, replacement, erase_regions, candidates in pending_labels:
            page = doc[page_num]
            group = groups_by_id[replacement.group_id]
            label_region, marker_result = _place_label_fixed(
                page, font, candidates, replacement, rung_by_group[group.id], fill_color
            )
            markers.append(marker_result)
            paint_regions = (*erase_regions, label_region)
            out_replacements.append(
                dataclasses.replace(
                    replacement,
                    erase_regions=erase_regions,
                    paint_regions=paint_regions,
                    label_region=label_region,
                )
            )

    doc.set_metadata({})
    doc.del_xml_metadata()
    doc.save(str(dest_path), garbage=4, deflate=True)
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
    box: pymupdf.Rect,
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
    if box.width <= 0 or box.height <= 0:
        return False
    return any(
        font.text_length(text, fontsize=size) <= box.width and box.height >= size
        for text, _reason in ladder
        if text
        for size in _MARKER_FONT_SIZES
    )


def _try_ladder(
    page: pymupdf.Page,
    font: pymupdf.Font,
    box: pymupdf.Rect,
    ladder: list[tuple[str, str]],
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
        for size in _MARKER_FONT_SIZES:
            if font.text_length(text, fontsize=size) > box.width:
                continue
            result = page.insert_textbox(
                box,
                text,
                fontname=_FONT_NAME,
                fontfile=str(_FONT_FILE),
                fontsize=size,
                color=_MARKER_TEXT_COLOR,
                align=pymupdf.TEXT_ALIGN_LEFT,
            )
            if result >= 0:
                return text, fallback_reason, size
    return None


def _label_box_candidates(
    cache: _PageCharsCache,
    page_num: int,
    seg_char_start: int,
    replacement: Replacement,
    trimmed_rects: list[tuple[int, pymupdf.Rect]],
) -> list[tuple[pymupdf.Rect, pymupdf.Rect]]:
    """Кандидаты (эрейз-прямоугольник, поле подписи) одного вхождения.

    Чистая геометрия, без рисования на странице — план М4 выбирает ступень
    лестницы один раз на группу, по самому тесному из всех её вхождений
    (``_choose_group_rungs``), а для этого нужны кандидаты **всех**
    вхождений группы заранее, до того как рендер решит, что печатать.

    Кандидаты — все прямоугольники сущности (по одному на строку), каждый
    расширенный вправо в доказанно свободное место своей строки
    (``_free_extension_right``) — план М1, правило 3.
    """
    for _line_id, rect in trimmed_rects:
        if rect.width <= 0 or rect.height <= 0:
            raise MarkerDoesNotFitError(
                f"вырожденный прямоугольник {rect!r} — вставлять текст некуда"
            )

    chars = cache.chars(page_num)
    line_boxes = cache.line_boxes(page_num)
    abs_start = seg_char_start + replacement.entity.start
    abs_end = seg_char_start + replacement.entity.end

    candidates: list[tuple[pymupdf.Rect, pymupdf.Rect]] = []  # (erase_rect, label_box)
    for line_id, erase_rect in trimmed_rects:
        extension_x1 = _free_extension_right(
            chars, line_id, erase_rect, abs_start, abs_end, line_boxes[line_id]
        )
        label_box = pymupdf.Rect(
            erase_rect.x0,
            erase_rect.y0 - 1,
            max(erase_rect.x1, extension_x1) + 2,
            erase_rect.y1 + 2,
        )
        candidates.append((erase_rect, label_box))
    return candidates


def _rung_fits_everywhere(
    font: pymupdf.Font,
    text: str,
    occurrences: list[list[tuple[pymupdf.Rect, pymupdf.Rect]]],
) -> bool:
    """``text`` обязан поместиться хоть в одном кандидате **каждого** вхождения."""
    return all(
        any(
            font.text_length(text, fontsize=size) <= label_box.width and label_box.height >= size
            for _erase_rect, label_box in occurrence
            for size in _MARKER_FONT_SIZES
        )
        for occurrence in occurrences
    )


def _choose_group_rungs(
    font: pymupdf.Font,
    groups: tuple[MaskGroup, ...],
    candidates_by_group: dict[str, list[list[tuple[pymupdf.Rect, pymupdf.Rect]]]],
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
    for group in groups:
        occurrences = candidates_by_group.get(group.id, [])
        chosen: tuple[str, str] = ("", "blank")
        if occurrences:
            for text, reason in marker_ladder(group):
                if not text:
                    continue
                if _rung_fits_everywhere(font, text, occurrences):
                    chosen = (text, reason)
                    break
        result[group.id] = chosen
    return result


def _place_label_fixed(
    page: pymupdf.Page,
    font: pymupdf.Font,
    candidates: list[tuple[pymupdf.Rect, pymupdf.Rect]],
    replacement: Replacement,
    rung: tuple[str, str],
    fill_color: tuple[float, float, float],
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
        for erase_rect, label_box in candidates:
            if not _ladder_fits(font, label_box, single_rung):
                continue
            if label_box.x1 > erase_rect.x1 + _GEOMETRY_EPS:
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
            outcome = _try_ladder(page, font, label_box, single_rung)
            if outcome is None:
                continue
            shown_text, fallback_reason, size = outcome
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
        # Ступень прошла общегрупповую проверку (``_rung_fits_everywhere``)
        # той же формулой ширины/высоты, что и здесь — если ни один
        # кандидат этого вхождения её всё же не принял, геометрия версий
        # разъехалась выше по стеку, а не «место кончилось»: молчать нельзя.
        raise MarkerDoesNotFitError(
            f"ступень {text!r}, выбранная для группы {replacement.group_id!r}, "
            "не поместилась ни в одном кандидате этого вхождения"
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
