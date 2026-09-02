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

Узкое поле реальной таблицы иногда не вмещает полный маркер плана
(``[ПОТРЕБИТЕЛЬ-ОРГАНИЗАЦИЯ-1]`` в ячейку под трёхбуквенную аббревиатуру).
Решение заказчика (план T2.2.1, пачка 5) — лестница отступления, а не
падение: полный маркер → короткая метка типа (``mask/labels.py``) → без
текста. Исходный текст при этом удалён на всех трёх ступенях — падает
только вырожденный (нулевой площади) прямоугольник, которого на верно
посчитанных боксах быть не должно.

Стиль ``blackbox`` из этой лестницы выведен (план T2.2.2, шаг 1, отменяет
решение из пачки 5 плана T2.2.1): заказчик увидел метку типа на чёрном
прямоугольнике готового документа и потребовал вернуть просто чёрный
прямоугольник без текста. ``blackbox`` больше не пытается вписать ни
полный маркер, ни короткую метку и никогда не порождает
``MarkerDegradation`` — «без текста» для него не деградация, а замысел
стиля. Лестница отступления целиком осталась только у стиля ``marker``.
"""

from __future__ import annotations

import os
import pathlib
from collections import defaultdict
from dataclasses import dataclass

import pymupdf

from masker.ingest.pdf_ingest import PageChars, page_chars
from masker.mask.labels import type_marker_label
from masker.model import Document, Entity, MaskPlan, Replacement

_FONT_FILE: pathlib.Path = pathlib.Path(__file__).parent.parent / "data" / "DejaVuSans.ttf"
_FONT_NAME = "cyr"
#: Кандидаты размера шрифта, от крупного к минимальному — риск Р6 плана
#: T2.2.1: узкая ячейка таблицы не должна тихо остаться без текста там,
#: где текст физически можно уменьшить и вписать.
_MARKER_FONT_SIZES: tuple[float, ...] = (10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0)
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


class MarkerDoesNotFitError(ValueError):
    """Прямоугольник вырожденной площади — деградировать некуда.

    Раньше это исключение поднималось на любой узкий, но настоящей площади
    прямоугольник, если в него не влезал маркер целиком — план T2.2.1,
    риск Р6. Лестница отступления (решение заказчика, пачка 5) закрывает
    этот случай текстом покороче или пустым прямоугольником без падения;
    исключение остаётся только на прямоугольник нулевой или отрицательной
    площади — сигнал, что боксы посчитаны неверно выше по стеку, а не что
    место физически кончилось.
    """


@dataclass(frozen=True, slots=True)
class MarkerDegradation:
    """Один спуск на ступень ниже лучшего результата стиля — факт для отчёта.

    ``shown_as`` — что реально показано вместо лучшего результата:
    ``"type_label"`` (короткая метка типа вместо полного маркера, только
    для стиля ``marker``) или ``"blank"`` (прямоугольник вовсе без
    текста). Успешная вставка лучшего результата стиля в список не
    попадает — деградацией не является.
    """

    page: int
    entity_type: str
    marker: str
    shown_as: str


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
    """Результат ``render_pdf_redacted`` целиком (план T2.2.2, шаг 3).

    ``degradations`` — спуски по лестнице отступления маркера (план T2.2.1,
    пачка 5). ``collisions`` — прямоугольники, для которых обрезка по
    соседней строке была отменена из-за полного перекрытия строк.
    """

    degradations: tuple[MarkerDegradation, ...]
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
    cache: _PageCharsCache, page_num: int, seg_char_start: int, entity: Entity
) -> list[tuple[int, pymupdf.Rect]]:
    chars = cache.chars(page_num)
    abs_start = seg_char_start + entity.start
    abs_end = seg_char_start + entity.end
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
        for _line_id, rect in _rects_for_entity(cache, page_num, seg_start, entity):
            annot = page.add_highlight_annot(rect)
            annot.update()
    doc.save(str(dest_path))
    doc.close()
    os.chmod(dest_path, 0o600)


def render_pdf_redacted(
    source_path: str | pathlib.Path,
    dest_path: str | pathlib.Path,
    document: Document,
    plan: MaskPlan,
    *,
    style: str = "marker",
) -> RenderOutcome:
    """Удалить сущности из content-stream и вставить заглушки с маркерами плана.

    style="marker"   — светлый фон весь спуск по лестнице отступления
                       (план T2.2.1, пачка 5): полный маркер плана →
                       короткая метка типа → без текста.
    style="blackbox" — чёрный прямоугольник и ничего больше (план T2.2.2,
                       шаг 1, решение заказчика отменяет прежнюю метку типа
                       на чёрном из пачки 5 плана T2.2.1): текст не
                       вставляется ни одной ступенью, деградаций для этого
                       стиля не бывает в принципе.

    Прямоугольник редакции строится только из символов **своей** строки
    (``line_id`` из ``page_chars``) и обрезается серединой полосы
    перекрытия с соседними строками — план T2.2.2, шаг 3, лечит Д10
    (``apply_redactions`` стирал глифы соседней строки, попавшие в
    прямоугольник по пересечению боксов). Заливка и вставка текста
    работают по уже обрезанному прямоугольнику.

    Текст маркера вставляется не более одного раза на ``Replacement`` — в
    первый Rect (Д1): сущность, разбитая переносом строки на несколько
    прямоугольников, раньше получала текст в каждый из них. Каждый спуск
    ниже полного маркера стиля ``marker`` возвращается в
    ``RenderOutcome.degradations`` — не падение, а факт для отчёта, чтобы
    человек видел, где документ стал менее читаемым. Для ``blackbox`` эта
    лестница не запускается вовсе. Отменённые обрезки (строки перекрыты
    целиком) возвращаются в ``RenderOutcome.collisions``.

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

    # Сгруппировать по страницам; боксы считаются до любых изменений документа.
    # `is_primary` истинно только у первого Rect замены (Д1): текст
    # вставляется не более одного раза на Replacement, даже если сущность
    # разбита переносом строки на несколько прямоугольников.
    by_page: dict[int, list[tuple[int, pymupdf.Rect, Replacement, bool]]] = defaultdict(list)
    for replacement in plan.replacements:
        page_num, seg_start, _seg_end = _parse_locator(replacement.anchor.locator)
        rects = _rects_for_entity(cache, page_num, seg_start, replacement.entity)
        for index, (line_id, rect) in enumerate(rects):
            by_page[page_num].append((line_id, rect, replacement, index == 0))

    fill_color = (0.0, 0.0, 0.0) if style == "blackbox" else (1.0, 1.0, 1.0)
    degradations: list[MarkerDegradation] = []
    collisions: list[RenderCollision] = []

    # Явная сортировка по номеру страницы — детерминизм не должен зависеть
    # от порядка обхода defaultdict (план T2.2.1, раздел «Детерминизм»).
    for page_num in sorted(by_page):
        redactions = by_page[page_num]
        page = doc[page_num]
        line_boxes = cache.line_boxes(page_num)
        trimmed: list[tuple[pymupdf.Rect, Replacement, bool]] = []
        for line_id, rect, replacement, is_primary in redactions:
            trimmed_rect, collided = _trim_to_own_line(rect, line_id, line_boxes)
            if collided:
                collisions.append(
                    RenderCollision(
                        page=page_num,
                        line_id=line_id,
                        entity_type=replacement.entity.type,
                        marker=replacement.marker,
                    )
                )
            page.add_redact_annot(trimmed_rect, fill=fill_color)
            trimmed.append((trimmed_rect, replacement, is_primary))
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
        if style == "blackbox":
            # Чёрный прямоугольник — просто чёрный (план T2.2.2, шаг 1):
            # лестница отступления маркера для этого стиля не запускается.
            continue
        page.insert_font(fontname=_FONT_NAME, fontfile=str(_FONT_FILE))
        for trimmed_rect, replacement, is_primary in trimmed:
            if not is_primary:
                continue
            box = pymupdf.Rect(
                trimmed_rect.x0, trimmed_rect.y0 - 1, trimmed_rect.x1 + 2, trimmed_rect.y1 + 2
            )
            degradation = _insert_marker_ladder(page, font, box, trimmed_rect, replacement)
            if degradation is not None:
                degradations.append(degradation)

    doc.set_metadata({})
    doc.del_xml_metadata()
    doc.save(str(dest_path), garbage=4, deflate=True)
    doc.close()
    os.chmod(dest_path, 0o600)
    # Сортировка по (page, line_id) — план T2.2.2, раздел «Детерминизм»:
    # порядок коллизий не должен зависеть от порядка plan.replacements.
    collisions.sort(key=lambda item: (item.page, item.line_id))
    return RenderOutcome(degradations=tuple(degradations), collisions=tuple(collisions))


def _parse_locator(locator: tuple[str | int | float, ...]) -> tuple[int, int, int]:
    """``("page", page_num, char_start, char_end)`` → номер страницы и
    символьный диапазон сегмента (план T2.2.1, шаг 8)."""
    _, page_num, char_start, char_end = locator
    return int(page_num), int(char_start), int(char_end)


def _insert_marker_ladder(
    page: pymupdf.Page,
    font: pymupdf.Font,
    box: pymupdf.Rect,
    rect: pymupdf.Rect,
    replacement: Replacement,
) -> MarkerDegradation | None:
    """Вписать текст по лестнице отступления стиля ``marker``, вернуть факт деградации.

    Вызывается только для стиля ``marker`` — ``blackbox`` эту функцию не
    зовёт вовсе (план T2.2.2, шаг 1). ``None``, если поместился полный
    маркер — деградации не было.
    """
    if rect.width <= 0 or rect.height <= 0:
        raise MarkerDoesNotFitError(f"вырожденный прямоугольник {rect!r} — вставлять текст некуда")

    type_label = type_marker_label(replacement.entity.type)
    steps: list[tuple[str, str, int]] = [
        (replacement.marker, "marker", pymupdf.TEXT_ALIGN_LEFT),
        (type_label, "type_label", pymupdf.TEXT_ALIGN_CENTER),
    ]

    for text, shown_as, align in steps:
        if _fits(page, font, box, rect, text, _MARKER_TEXT_COLOR, align):
            if shown_as == "marker":
                return None
            return MarkerDegradation(
                page=page.number,
                entity_type=replacement.entity.type,
                marker=replacement.marker,
                shown_as=shown_as,
            )
    return MarkerDegradation(
        page=page.number,
        entity_type=replacement.entity.type,
        marker=replacement.marker,
        shown_as="blank",
    )


def _fits(
    page: pymupdf.Page,
    font: pymupdf.Font,
    box: pymupdf.Rect,
    rect: pymupdf.Rect,
    text: str,
    color: tuple[float, float, float],
    align: int,
) -> bool:
    """Попробовать вписать ``text`` в ``box``, проверив настоящий результат.

    ``insert_textbox`` возвращает отрицательное число, если текст не
    поместился. `text_length` — дешёвая отсечка ширины до настоящей
    (небесплатной, с побочным эффектом) вставки; настоящий возврат
    проверяется всегда — оценка по ширине не учитывает перенос по высоте.
    """
    for size in _MARKER_FONT_SIZES:
        if font.text_length(text, fontsize=size) > rect.width:
            continue
        result = page.insert_textbox(
            box,
            text,
            fontname=_FONT_NAME,
            fontfile=str(_FONT_FILE),
            fontsize=size,
            color=color,
            align=align,
        )
        if result >= 0:
            return True
    return False
