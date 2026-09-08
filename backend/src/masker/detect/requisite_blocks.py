"""Блок реквизитов/подписей как источник кандидатов детекции (Р6, TASKS.md).

Р8 уже строит структурные блоки (`profile/blocks.py`) для профилирования
сторон, но не использует их для детекции — заголовок «Реквизиты Поставщика»
или строка подписи «Поставщик: ______________ И.И. Иванов» сами по себе
сильный структурный сигнал: всё, что стоит там заглавной буквы и не
опознано ни одним детектором, почти наверняка PII (имя, должность, часть
названия), а не случайное слово из середины преамбулы.

Архитектурная развилка (обязательна к прочтению перед правкой)
----------------------------------------------------------------
`EntityDetector.detect(document)` (`detect/base.py`) получает только сырой
`Document` — ни один детектор в общем списке не видит, что нашли остальные.
`build_context_blocks(segments, entities)` требует ОБРАТНОГО: границы блока
и состав `block.entities` зависят от уже найденных сущностей (`empty_gap`,
«заголовок обрывает блок только если в текущем уже есть сущности» и т.п.).
Подключить этот модуль как обычный `EntityDetector` в `default_detectors()`
поэтому нельзя без изменения протокола — а протокол используют все
детекторы, менять его ради одного потребителя не входит в объём Р6.

Выбранное решение — по образцу `sweep.py` (Д13): не `EntityDetector`, а
отдельный шаг ПОСЛЕ разрешения перекрытий в `DetectAgent.detect()`,
получающий уже готовый список сущностей явным параметром. `sweep()` —
готовый прецедент именно такой архитектуры в этом же файле, поэтому это не
новый паттерн, а переиспользование существующего.

Импорт `masker.profile.blocks` — внутри функции, а не на уровне модуля.
`masker.profile.agent` импортирует `masker.detect.result` (см. импорты
`profile/agent.py`), поэтому импорт на уровне модуля здесь заставил бы
порядок импортов `detect/__init__.py` совпасть по времени с завершением
инициализации `masker.detect.result` — работает, но зависит от порядка
строк в `detect/__init__.py`/`detect/agent.py`, что хрупко при рефакторинге.
Отложенный импорт (тот же приём, что уже применяют `config_detector.py`,
`gliner.py`, `llm_filter_detector.py` в `default_detectors()`) полностью
снимает вопрос: к моменту вызова `find_requisite_block_candidates` оба
пакета уже гарантированно загружены вызывающим кодом.

Известное ограничение: PDF иногда сливает заголовок раздела и его
содержимое в один сегмент без пробела после номера («5.БАНКОВСКИЕ
РЕКВИЗИТЫ...», без пробела перед текстом — `HEADING` из `profile/blocks.py`
требует пробел после точки) — `_is_heading` там же тоже не срабатывает
(длина сегмента больше 80 символов). Такой блок не получает `.heading`, и
этот модуль его не увидит. Это дефект структурного разбора PDF-абзацев
(отдельная задача уровня ingest), не то, что решает Р6: тип не пропущен —
на этой же строке критичные типы (ОГРН/ИНН/КПП/БИК/счета) находит
`RuleDetector`, признанное P8‑ограничение только сужает охват открытого
класса «похоже на имя» на этой конкретной вёрстке.
"""

from __future__ import annotations

import re

from masker.detect.normalize import normalize_value
from masker.detect.persons import drop_role_prefix
from masker.model import Document, Entity, EntityType, Source

#: Заголовок/строка относится к разделу реквизитов или подписей только по
#: характерным словоформам — не любому слову с корнем «подпис»: иначе
#: «Документ подписан на ЭП ...» (реальный футер PDF,
#: `contract_pdf_02_school.pdf`) ложно считается заголовком раздела
#: подписей, и весь текст футера попадает в кандидаты.
_SECTION_HEADING = re.compile(r"\bреквизит\w*\b|\bподписи\b|\bподпись\b", re.IGNORECASE)

#: Одно заглавное слово: прописная буква + минимум одна строчная. Это
#: осознанно режет КАПС-заголовки («БАНКОВСКИЕ РЕКВИЗИТЫ») и аббревиатуры
#: («БИК», «ОГРН») — они не могут быть именем собственным по построению.
_TITLE_WORD = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)*"

#: Последовательность из ДВУХ и более заглавных слов подряд через один
#: пробел/таб. Одно заглавное слово регулярка не ловит осознанно: реквизитные
#: строки полны одиночных заглавных слов-меток («Адрес:», «Телефон:»,
#: «Директор»), и без минимума в два слова кандидаты захлестнули бы разметку
#: полей, а не значений (проверено прогоном `masker.eval` — метка поля не
#: должна становиться кандидатом).
_CAPITALIZED_RUN = re.compile(rf"{_TITLE_WORD}(?:[ \t]+{_TITLE_WORD})+")

#: Уверенность кандидата — намеренно низкая: сигнал один (структурный), не
#: контрольная сумма и не согласие независимых детекторов. Финальный уровень
#: (Р8, `classify_level`) не читает это число напрямую для типов из
#: `OPEN_CLASS_TYPES`, но оно идёт в отчёт как обычное поле сущности.
_CANDIDATE_CONFIDENCE = 0.5


def _covered(ranges: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(
        existing_start < end and start < existing_end for existing_start, existing_end in ranges
    )


def _is_target_block(block: object, segment_text_by_order: dict[int, str]) -> bool:
    """Блок реквизитов (по заголовку) либо строка подписи (по метке `Роль:`).

    Заголовочный путь ловит «1. Реквизиты Поставщика» и следующие за ним
    строки адреса/счёта/телефона — они попадают в ОДИН блок с этим
    заголовком (см. `build_context_blocks`). Путь по `SIGNATURE` ловит
    отдельную строку подписи («Поставщик: ______________ И.И. Иванов»),
    которая в `build_context_blocks` образует свой собственный блок БЕЗ
    заголовка (смена метки роли обрывает блок) — без этой ветки подписной
    блок остался бы вовсе не источником кандидатов, что противоречит
    задаче Р6 напрямую.
    """
    from masker.profile.labels import SIGNATURE

    if _SECTION_HEADING.search(block.heading):  # type: ignore[attr-defined]
        return True
    return any(
        SIGNATURE.match(segment_text_by_order[span.segment_order][span.start : span.end])
        for span in block.spans  # type: ignore[attr-defined]
    )


def find_requisite_block_candidates(document: Document, entities: list[Entity]) -> list[Entity]:
    """Найти заглавные последовательности внутри блоков реквизитов/подписей,
    не покрытые ни одним из уже найденных `entities` (Р6).

    Возвращает сущности типа `EntityType.PERSON` — заглавная
    последовательность вне формального признака ближе всего к «имени
    собственному без подтверждения», а не к оргформе (`OrgFormDetector` уже
    ловит названия организаций по словарю форм; то, что осталось
    непойманным, в подавляющем большинстве случаев — имя человека).
    Финальный уровень уверенности (`ConfidenceLevel.POSSIBLE`) проставляет
    не этот модуль, а `DetectAgent._levelled`/`classify_level` (Р8) — здесь
    задаётся только низкая базовая `confidence`, чтобы не задавать уровень
    дважды в двух разных местах.

    ``entities`` — уже объединённый и разрешённый по перекрытиям результат
    остальных детекторов (тот же контракт, что и у ``sweep()``): вызывающий
    (`DetectAgent.detect`) обязан звать это ПОСЛЕ `_resolve_overlaps`.
    """
    from masker.profile.blocks import HEADING, build_context_blocks

    occupied: dict[int, list[tuple[int, int]]] = {}
    for entity in entities:
        occupied.setdefault(entity.segment_order, []).append((entity.start, entity.end))

    segment_text_by_order = {segment.order: segment.text for segment in document.segments}
    blocks = build_context_blocks(document.segments, entities)

    found: list[Entity] = []
    for block in blocks:
        if not _is_target_block(block, segment_text_by_order):
            continue
        for span in block.spans:
            text = segment_text_by_order[span.segment_order]
            local_text = text[span.start : span.end]
            if HEADING.match(local_text):
                # Сам заголовок раздела («1. Реквизиты Поставщика») — не
                # значение, а название раздела: «Реквизиты» + роль — уже
                # двухсловная заглавная последовательность, но это не ФИО.
                continue
            ranges = occupied.setdefault(span.segment_order, [])
            for match in _CAPITALIZED_RUN.finditer(local_text):
                start = span.start + match.start()
                end = span.start + match.end()
                trimmed = drop_role_prefix(text, start, end)
                if trimmed is None:
                    continue
                start, end = trimmed
                if len(text[start:end].split()) < 2:
                    # Реальный дефект PDF (`contract_pdf_02_school.pdf`,
                    # блок сертификата ЭП): «Должность: Директор Сертификат»
                    # — «Директор» (должность, `role_stems`) вплотную к
                    # «Сертификат» (слово из СЛЕДУЮЩЕГО поля, не имя) даёт
                    # заглавную пару без единого реального имени. После
                    # среза ведущей должности («Директор» → пусто) от пары
                    # остаётся одно слово — недостаточно для кандидата.
                    continue
                if _covered(ranges, start, end):
                    continue
                value = text[start:end]
                found.append(
                    Entity(
                        type=EntityType.PERSON,
                        text=value,
                        segment_order=span.segment_order,
                        start=start,
                        end=end,
                        source=Source.BLOCK,
                        confidence=_CANDIDATE_CONFIDENCE,
                        normalized=normalize_value(EntityType.PERSON, value),
                    )
                )
                ranges.append((start, end))
    return sorted(found, key=lambda item: (item.segment_order, item.start, item.end))
