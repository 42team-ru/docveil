"""Контекстные блоки для структурного профилирования."""

from __future__ import annotations

import re
from dataclasses import dataclass

from masker.model import Entity, Segment
from masker.profile.labels import find_labels

MAX_EMPTY_GAP = 2
MAX_BLOCK_SPANS = 12
MAX_BLOCK_CHARS = 4000
# Точка обязательна: то же понятие «начало пункта договора», что и
# `ingest/pdf_ingest.py::_CLAUSE_START_RE`. Без неё бегущий колонтитул вида
# «7 От Заказчика ____/И.И. Иванов/ От Поставщика ____/П.П. Петров/»
# (номер страницы без точки) считался нумерованным заголовком на каждой
# странице PDF и сбрасывал накопленную метку роли (12.09.2026).
HEADING = re.compile(r"^\s*\d+(?:\.\d+)*\.\s+")
#: Метаданные ЭП отделяют подпись одной стороны от сертификата другой.
_SIGNATURE_METADATA_HEADING = re.compile(r"^данные\s+(?:электронной\s+подписи|сертификата)\b", re.I)


@dataclass(frozen=True, slots=True)
class BlockSpan:
    segment_order: int
    start: int
    end: int


@dataclass(slots=True)
class ContextBlock:
    id: str
    spans: list[BlockSpan]
    entities: list[Entity]
    label: str = ""
    heading: str = ""


def _anchor_kind(segment: Segment) -> str:
    return str(segment.anchor.locator[0]) if segment.anchor.locator else ""


def _scope_broken(previous: Segment, current: Segment) -> bool:
    """Проверить, обрывается ли унаследованная метка на границе сегментов.

    На DOCX смена вида якоря (абзац → ячейка таблицы) — надёжный сигнал
    «начался новый раздел». На PDF и скане вид якоря постоянен —
    `("page", n, …)` для каждого сегмента страницы (`pdf_ingest.py`,
    `scan_ingest.py`) — и это условие никогда не срабатывает: метка,
    подхваченная из формулировки внутри абзаца, текла бы до конца
    документа непрерывно (12.09.2026: так `«ЗАКАЗЧИК»` из преамбулы
    доезжала до последней страницы). Для этих форматов каждый сегмент —
    свой блок вёрстки страницы, поэтому граница — каждая смена сегмента;
    метка из заголовка (`active_label_from_heading`) по-прежнему её
    переживает — этот флаг проверяется отдельно вызывающим кодом.
    """
    if current.anchor.fmt == "pdf":
        return True
    return _anchor_kind(current) != _anchor_kind(previous)


def _is_heading(text: str, has_entities: bool) -> bool:
    stripped = text.strip()
    if HEADING.match(stripped):
        return True
    # Короткая ненумерованная строка без сущностей — вероятно заголовок
    # раздела («ПРЕДМЕТ ДОГОВОРА»). Та же строка с реквизитом внутри —
    # содержимое, а не шапка: колонтитул с ФИО подписанта или ячейка
    # таблицы реквизитов не должны резать блок пополам только потому, что
    # они короткие и без двоеточия (12.09.2026, `ipklh-2022-01-11.pdf`:
    # 73% сегментов PDF проходили это условие и дробили документ на 86
    # мусорных блоков).
    return (
        not has_entities
        and bool(stripped)
        and len(stripped) <= 80
        and ":" not in stripped
        and not stripped.endswith(".")
    )


def _label_carries_forward(text: str, is_numbered_heading: bool) -> bool:
    """Метка этого сегмента должна управлять следующими блоками, как заголовок.

    Верно для короткой шапки-поля («Поставщик: ООО «Х»», «1. Реквизиты
    Поставщика», «Заказчик Исполнитель») — она вводит роль для того, что
    идёт дальше, а не упоминает её мимоходом. НЕ верно для длинной
    преамбулы с запятыми («…, именуемое в дальнейшем «Заказчик», в лице…,
    с одной стороны, и …») — та вводит роль внутри одного предложения о
    КОНКРЕТНОЙ стороне и не должна распространяться на совсем другой
    раздел документа.

    Отдельно от `_is_heading`: у поля-шапки типа `SIGNATURE`
    («Поставщик: …») есть двоеточие и есть своя сущность, поэтому
    `_is_heading` намеренно не считает её заголовком (иначе она резала бы
    блок пополам, см. `_is_heading`) — но управлять следующим блоком она
    всё равно обязана, иначе на PDF (где `_scope_broken` рвёт область
    видимости метки на КАЖДОМ сегменте, `_scope_broken` ниже) роль
    «Поставщик» из шапки поля переставала действовать уже на следующей
    строке с его реквизитами (13.09.2026, `contract_pdf_01.pdf`).
    """
    stripped = text.strip()
    return is_numbered_heading or (bool(stripped) and len(stripped) <= 80 and "," not in stripped)


def _known_label(label: str, labels: set[str]) -> str:
    """Связать падежную форму с уже названной документом ролью без словаря ролей.

    Сравнение — по общему префиксу с точностью до падежного окончания
    (не более 2 отличающихся хвостовых символов), а не по первым 5
    символам основы: «заказчик»/«заказчика» — одна роль, но «страхователь»/
    «страховщик» и «лизингодатель»/«лизингополучатель» (обе пары есть в
    `data/party_roles.yaml`) 5-символьную основу разделяют («страх»,
    «лизин»), а не роль — старое правило склеивало их в одну (12.09.2026).
    """
    for known in sorted(labels):
        shorter = min(len(label), len(known))
        common = 0
        while common < shorter and label[common] == known[common]:
            common += 1
        if common >= max(len(label), len(known)) - 2:
            return known
    return label


def build_context_blocks(segments: list[Segment], entities: list[Entity]) -> list[ContextBlock]:
    """Собрать непрерывные блоки; каждая принятая сущность входит ровно в один.

    Сегмент с двумя и более РАЗНЫМИ метками режется на куски по позициям
    меток — двухколоночная строка подписи или преамбула с обеими
    сторонами, расплющенная PDF-экстракцией в одну строку/абзац
    (`ingest/pdf_ingest.py::_walk_page`), иначе отдаёт все свои сущности
    только первой найденной метке (12.09.2026: колонтитул «От Заказчика
    …/Фамилия1/ От Поставщика …/Фамилия2/», повторённый на каждой
    странице, приписывал подпись Поставщика Заказчику на каждой
    странице). Сущность внутри такого сегмента достаётся куску, чья метка
    стоит перед ней, — точно для меток, которые предшествуют своему
    содержимому (`SIGNATURE`, `SIGNATORY_SIDE`, `REQUISITES`), и
    приблизительно для `PREAMBLE` (там метка стоит после названия
    стороны) — но даже там результат не хуже прежнего (весь сегмент шёл
    первой метке целиком), а `cluster.py` не даст редкой ошибке на
    `PREAMBLE` склеить обе стороны в одну: конфликтующие метки не
    объединяются. Сегмент с ≤1 меткой этот путь не проходит вовсе — здесь
    поведение побайтово прежнее.
    """
    entities_by_segment: dict[int, list[Entity]] = {}
    for entity in sorted(entities, key=lambda item: (item.segment_order, item.start, item.end)):
        entities_by_segment.setdefault(entity.segment_order, []).append(entity)
    blocks: list[ContextBlock] = []
    current: ContextBlock | None = None
    active_label = ""
    # Метка, поставленная самим заголовком («1. Реквизиты Исполнителя»), должна
    # управлять всем разделом до следующего заголовка независимо от смены типа
    # якоря внутри раздела (таблица реквизитов идёт сразу после заголовка).
    # Метка, подхваченная из формулировки внутри абзаца (преамбула «именуемое
    # в дальнейшем ...»), такой гарантии не даёт и гасится на первой же смене
    # структуры — иначе она утекает в совсем другой раздел документа.
    active_label_from_heading = False
    seen_labels: set[str] = set()
    empty_gap = 0
    previous_segment: Segment | None = None
    prior_kind: str | None = None
    for segment in sorted(segments, key=lambda item: item.order):
        stripped = segment.text.strip()
        is_numbered_heading = bool(HEADING.match(stripped))
        segment_entities = entities_by_segment.get(segment.order, [])
        heading = stripped if _is_heading(stripped, bool(segment_entities)) else ""
        # Сброс выполняется до применения меток этого же сегмента — иначе
        # заголовок, который сам несёт метку, погасил бы её же.
        scope_broken = previous_segment is not None and _scope_broken(previous_segment, segment)
        if (
            is_numbered_heading
            or _SIGNATURE_METADATA_HEADING.match(stripped)
            or (scope_broken and not active_label_from_heading)
        ):
            active_label = ""
            active_label_from_heading = False
        previous_segment = segment

        resolved_labels: list[tuple[int, str]] = []
        for position, raw_label in find_labels(segment.text):
            label = _known_label(raw_label, seen_labels)
            seen_labels.add(label)
            resolved_labels.append((position, label))
        distinct_values = {label for _, label in resolved_labels}

        # explicit_piece — метка, которую ЭТОТ кусок вводит сам (пусто,
        # если он лишь наследует active_label); effective_piece — метка,
        # действующая для куска, всегда непустая после первого label.
        fragments: list[tuple[str, str, int, int, list[Entity]]]
        if len(distinct_values) <= 1:
            explicit_label = resolved_labels[0][1] if resolved_labels else ""
            if explicit_label:
                active_label = explicit_label
                active_label_from_heading = _label_carries_forward(
                    segment.text, is_numbered_heading
                )
            fragments = [(explicit_label, active_label, 0, len(segment.text), segment_entities)]
        else:
            boundaries = [0, *(position for position, _ in resolved_labels), len(segment.text)]
            piece_labels = [("", active_label), *((label, label) for _, label in resolved_labels)]
            fragments = [
                (
                    explicit_piece,
                    effective_piece,
                    start,
                    end,
                    [entity for entity in segment_entities if start <= entity.start < end],
                )
                for (explicit_piece, effective_piece), start, end in zip(
                    piece_labels, boundaries[:-1], boundaries[1:], strict=True
                )
            ]
            active_label = resolved_labels[-1][1]
            # Сегмент с 2+ разными метками — почти всегда двухколоночная
            # строка/абзац с обеими сторонами сразу (шапка подписи,
            # преамбула), а не структурный заголовок. Последняя метка не
            # должна пережить сам сегмент: иначе она снова потечёт вперёд
            # ровно тем способом, который и чинит `_scope_broken` (13.09.2026,
            # `ipklh-2022-01-11.pdf`: «поставщик» из футера подписи
            # растягивался на следующие страницы).
            active_label_from_heading = is_numbered_heading

        for explicit_piece, effective_piece, start, end, piece_entities in fragments:
            new_block = current is None
            if current is not None:
                new_block = (
                    bool(explicit_piece and explicit_piece != current.label)
                    # Метка — свойство всего блока, а не последнего куска.
                    # Без границы здесь следующая метка (или сброс
                    # active_label) переписывал бы роль у уже добавленных
                    # сущностей.
                    or bool(current.entities and effective_piece != current.label)
                    or _anchor_kind(segment) != prior_kind
                    or len(current.spans) >= MAX_BLOCK_SPANS
                    or sum(span.end - span.start for span in current.spans) + (end - start)
                    > MAX_BLOCK_CHARS
                    or bool(heading and current.entities)
                    or bool(piece_entities and empty_gap > MAX_EMPTY_GAP)
                )
            if new_block:
                current = ContextBlock(
                    id=f"B{len(blocks) + 1}",
                    spans=[],
                    entities=[],
                    label=effective_piece,
                    heading=heading,
                )
                blocks.append(current)
            assert current is not None
            # Пока в блоке нет сущностей, метка может уточняться формулировкой
            # следующего куска. После первой сущности изменение метки создаёт
            # отдельный блок выше, поэтому роль уже собранного блока не стирается.
            if not current.entities:
                current.label = effective_piece
            if heading and not current.heading:
                current.heading = heading
            current.spans.append(BlockSpan(segment.order, start, end))
            current.entities.extend(piece_entities)
            empty_gap = empty_gap + 1 if not piece_entities else 0
        prior_kind = _anchor_kind(segment)
    return blocks


def block_text(segments: list[Segment], block: ContextBlock) -> str:
    """Вернуть текст блока в порядке сегментов и спанов."""
    texts = {segment.order: segment.text for segment in segments}
    return "\n".join(texts[span.segment_order][span.start : span.end] for span in block.spans)
