"""Нормализация вёрстки текста перед детекцией (план Р1).

Метаморфный корпус (`make eval`) показывает, что подавляющее большинство
пропусков — не в качестве регулярок и не в NER, а в том, что мы ищем
сущности в «сыром» тексте с вёрсткой: неразрывные пробелы, перенос строки
посреди номера, разрядка «И Н Н», гомоглифы латиница/кириллица. Эти пять
категорий у детекторов нет ни единого шанса поймать, потому что регулярка
`\\d{10}` не совпадает, если между цифрами затесался перенос строки.

`normalize_for_detection` строит «чистый» текст для детекторов и карту
смещений обратно на исходный текст. Контракт `model.py` не меняется:
наружу (в `DetectAgent`) всегда идут координаты ИСХОДНОГО сегмента — этот
модуль не знает о `Document`/`Entity`, он работает с голыми строками.
"""

from __future__ import annotations

import re

#: Латиница → кириллица, символы, неотличимые визуально в паре шрифтов.
#: Только одно направление: обратное («о» → «o») исковеркало бы обычный
#: латинский текст (e-mail, сайты), которого в документах несравнимо
#: больше, чем случаев кириллицы, набранной латиницей.
#:
#: Применяется НЕ ко всему тексту, а только внутри токенов, где латиница
#: и кириллица смешаны (см. `_fold_homoglyphs`) — иначе чисто латинский
#: токен вроде `www`, `triema`, `catalog`, `MLT` калечится напрасно: там
#: латиница законная, а не маскировка кириллицы.
_HOMOGLYPHS: dict[str, str] = {
    "o": "о",
    "a": "а",
    "e": "е",
    "c": "с",
    "p": "р",
    "x": "х",
    "y": "у",
    "k": "к",
    "B": "В",
    "H": "Н",
    "M": "М",
    "T": "Т",
    "P": "Р",
    "C": "С",
    "A": "А",
    "E": "Е",
    "O": "О",
    "K": "К",
    "X": "Х",
}

#: Обычные разрывные пробелы: настоящая граница между словами. Собираются
#: в рамках одного пробельного «прогона» и никогда не склеиваются с
#: соседями — иначе «пять десять» слиплось бы в «510».
_HARD_WHITESPACE = frozenset({" ", "\t"})
#: «Мягкие» варианты пробела: неразрывный (U+00A0), узкий (U+2009),
#: волосяной (U+200A), нулевой ширины (U+200B). Их смысл — «не разрывать
#: строку здесь», а не «граница слова», поэтому между двумя буквенно-
#: цифровыми символами такой пробел — это разбитое при копипасте/OCR
#: значение реквизита, а не два разных слова.
_SOFT_WHITESPACE = frozenset({"\u00a0", "\u2009", "\u200a", "\u200b"})
#: Перенос строки — типовой выход `page_chars` на PDF: колонка/строка
#: обрывается посередине номера или слова без всякого пробела.
_LINEBREAK = frozenset({"\n", "\r"})
_SOFT_HYPHEN = "\u00ad"

#: Известные метки реквизитов, к которым при копипасте из PDF могло
#: прилипнуть число без пробела: «(ИНН3662103003)». Список закрытый и
#: короткий: это не эвристика «буква+цифра» (она резала бы КПП — там
#: буква через дефис входит в сам номер, а не в метку перед ним).
_LABELS = ("огрнип", "огрн", "инн", "кпп", "снилс", "бик", "октмо")
_LETTER = "а-яёА-ЯЁa-zA-Z"
_LABEL_DIGIT_RE = re.compile(rf"(?<![{_LETTER}])(?:{'|'.join(_LABELS)})(?=\d)", re.IGNORECASE)

#: Токен разрядки: одна заглавная буква (кириллица/латиница) или цифра.
#: Обычные короткие слова русского текста («и», «я», «в», «о») — строчные
#: и под этот класс не попадают, поэтому разрядка не трогает связный текст,
#: только «И Н Н» / «3 6 6 2 …» — исключительно заглавные обрывки меток и
#: цифры реквизитов.
_SPACED_TOKEN = "0-9A-ZА-ЯЁ"
_SPACED_RUN_RE = re.compile(
    rf"(?<![{_SPACED_TOKEN}])[{_SPACED_TOKEN}](?: [{_SPACED_TOKEN}]){{2,}}(?![{_SPACED_TOKEN}])"
)

#: Основной блок кириллицы (включая Ё/ё, которые лежат вне диапазона
#: «а»…«я»). Проверка по кодовой точке, а не по `str.isalpha`, — символ
#: должен быть именно кириллическим, а не просто буквой любого алфавита.
_CYRILLIC_RANGE = ("Ѐ", "ӿ")


def _is_cyrillic(char: str) -> bool:
    return _CYRILLIC_RANGE[0] <= char <= _CYRILLIC_RANGE[1]


def _fold_homoglyphs(text: str) -> str:
    """Заменить латиницу на визуально неотличимую кириллицу, но только
    внутри токена (последовательности букв/цифр), где кириллица и латиница
    СМЕШАНЫ — «ИHН» с латинской «H» рядом с кириллическими «И», «Н».

    Токен, где нет ни одной кириллической буквы («www», «triema», «MLT»,
    «catalog», «info»), не трогается вообще: это законная латиница
    (сайт, e-mail, артикул), а не маскировка кириллицы латинскими буквами.
    Длина строки не меняется — каждый символ отображается один в один,
    поэтому вызывающему коду не нужна отдельная карта смещений для этого
    шага.
    """
    chars = list(text)
    n = len(chars)
    i = 0
    while i < n:
        if chars[i].isalnum():
            start = i
            has_cyrillic = False
            while i < n and chars[i].isalnum():
                if _is_cyrillic(chars[i]):
                    has_cyrillic = True
                i += 1
            if has_cyrillic:
                for pos in range(start, i):
                    chars[pos] = _HOMOGLYPHS.get(chars[pos], chars[pos])
        else:
            i += 1
    return "".join(chars)


def normalize_for_detection(text: str) -> tuple[str, list[int]]:
    """Построить нормализованный текст и карту смещений для детекторов.

    ``mapping`` длиной ``len(normalized) + 1``: ``mapping[i]`` — индекс
    исходного символа, которому соответствует ``normalized[i]``, а
    ``mapping[len(normalized)]`` («часовой» элемент) равен ``len(text)``.
    Конец найденного в нормализованном тексте спана ``[start, end)``
    восстанавливается как ``[mapping[start], mapping[end])`` в исходном —
    без допущения «нормализация не меняет длину строки», которое ломается
    на каждом схлопывании (два пробела → один, перенос строки удалён,
    разрядка склеена).

    Детекторы контракт не меняют: получают текст, возвращают целочисленные
    смещения. Пересчёт в координаты исходного сегмента делает
    ``DetectAgent`` (см. ``agent.py``), не сами детекторы.
    """
    chars, mapping = _normalize_chars(_fold_homoglyphs(text))
    chars, mapping = _glue_spaced_tokens(chars, mapping)
    chars, mapping = _split_label_digit(chars, mapping)
    mapping.append(len(text))
    return "".join(chars), mapping


def _is_word(char: str) -> bool:
    return bool(char) and char.isalnum()


def _is_digit(char: str) -> bool:
    return bool(char) and char.isdigit()


def _normalize_chars(text: str) -> tuple[list[str], list[int]]:
    """Первый проход: мягкий перенос, пробельные варианты.

    Гомоглифы латиница/кириллица к этому моменту уже свёрнуты вызывающей
    `normalize_for_detection` через `_fold_homoglyphs` — здесь символы
    только копируются как есть.

    Пробельный «прогон» (подряд идущие пробелы/переносы/NBSP и т.п.)
    схлопывается в один обычный пробел, кроме двух случаев склейки без
    остатка (ничего не эмитится):

    * перенос строки (без примеси обычного пробела) между двумя буквенно-
      цифровыми символами — типовой артефакт постраничного извлечения PDF,
      рвущий слово или номер ровно посередине («36621\\n03003»);
    * неразрывный/тонкий/волосяной/нулевой ширины пробел (тоже без примеси
      обычного) между ДВУМЯ ЦИФРАМИ — назначение таких пробелов —
      «не разрывать», то есть по разные стороны от них одно значение, а не
      два слова (группировка разрядов в номере счёта/ИНН). Между буквами
      это же самое было бы уже опасно: неразрывный пробел после «в», «на»,
      «по» — обычная типографская защита предлога от отрыва в конце
      строки, и склейка испортила бы совершенно рядовой текст договора.

    Обычный пробел где-либо внутри прогона — сигнал настоящей границы
    слов, склейка не идёт, прогон схлопывается в один пробел.
    """
    out: list[str] = []
    idx_map: list[int] = []
    n = len(text)
    i = 0
    while i < n:
        char = text[i]
        if char == _SOFT_HYPHEN:
            i += 1
            continue
        if char in _HARD_WHITESPACE or char in _SOFT_WHITESPACE or char in _LINEBREAK:
            start = i
            has_hard = False
            has_soft = False
            has_linebreak = False
            while i < n and (
                text[i] in _HARD_WHITESPACE or text[i] in _SOFT_WHITESPACE or text[i] in _LINEBREAK
            ):
                if text[i] in _HARD_WHITESPACE:
                    has_hard = True
                elif text[i] in _LINEBREAK:
                    has_linebreak = True
                else:
                    has_soft = True
                i += 1
            before = out[-1] if out else ""
            after = text[i] if i < n else ""
            glue_linebreak = has_linebreak and not has_hard and _is_word(before) and _is_word(after)
            glue_soft = (
                has_soft
                and not has_hard
                and not has_linebreak
                and _is_digit(before)
                and _is_digit(after)
            )
            if glue_linebreak or glue_soft:
                continue  # склейка: перенос/неразрывный пробел внутри значения
            out.append(" ")
            idx_map.append(start)
            continue
        out.append(char)
        idx_map.append(i)
        i += 1
    return out, idx_map


def _glue_spaced_tokens(chars: list[str], idx_map: list[int]) -> tuple[list[str], list[int]]:
    """Разрядка: «И Н Н» / «3 6 6 2 …» → «ИНН» / «3662…» (не трогая пробел
    на границе типа токена — это делает `_split_label_digit`)."""
    joined = "".join(chars)
    matches = list(_SPACED_RUN_RE.finditer(joined))
    if not matches:
        return chars, idx_map
    keep = [True] * len(chars)
    for match in matches:
        for pos in range(match.start(), match.end()):
            if joined[pos] == " ":
                keep[pos] = False
    return (
        [c for c, k in zip(chars, keep, strict=True) if k],
        [m for m, k in zip(idx_map, keep, strict=True) if k],
    )


def _split_label_digit(chars: list[str], idx_map: list[int]) -> tuple[list[str], list[int]]:
    """«(ИНН3662103003)» → «(ИНН 3662103003)»: вернуть регулярке
    реквизита границу `\\b`, которую съедает слипшаяся с меткой цифра."""
    joined = "".join(chars)
    matches = list(_LABEL_DIGIT_RE.finditer(joined))
    if not matches:
        return chars, idx_map
    out: list[str] = []
    out_map: list[int] = []
    cursor = 0
    for match in matches:
        pos = match.end()
        out.extend(chars[cursor:pos])
        out_map.extend(idx_map[cursor:pos])
        out.append(" ")
        out_map.append(idx_map[pos])
        cursor = pos
    out.extend(chars[cursor:])
    out_map.extend(idx_map[cursor:])
    return out, out_map
