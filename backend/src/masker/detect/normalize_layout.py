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

from masker.detect.checksums import is_valid_bik, is_valid_inn

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

#: На `dagestanschool-kais-808.pdf` 11.09.2026 у повреждённого сегмента
#: юридического адреса доля однобуквенных буквенных токенов — 57 из 57
#: (100%). На обычном реквизитном сегменте 197 `arkhschool-68-183.pdf` —
#: лишь 5 из 50 (10%): двойные пробелы там разделяют колонки, а не буквы.
#: Поэтому порог 80% с минимумом 12 токенов уверенно отделяет разрядку
#: всего сегмента от обычной колоночной вёрстки.
_SPARSE_TOKEN_RATIO = 0.8
_SPARSE_MIN_ALPHA_TOKENS = 12
_WORD_TOKEN_RE = re.compile(r"\b\w+\b", re.UNICODE)

#: После удаления разрядки «Расчетный счет» превращается в одно слово, но
#: это не должно ослаблять правило: длинная цифровая цепочка режется только
#: за известной меткой расчётного либо корреспондентского счёта. Именно две
#: 40-разрядные цепочки в `dagestanschool-kais-808.pdf` 11.09.2026 состоят
#: из двух счетов по 20 цифр; вне этой метки произвольные числа не дробим.
_ACCOUNT_LABEL_RE = re.compile(
    r"(?:расчетныйсчет|расчётныйсчёт|корр\s*\.?\s*счет|корр\s*\.\s*счёт|корреспондентскийсчет)",
    re.IGNORECASE,
)
_ACCOUNT_RUN_RE = re.compile(r"\d+")

#: Короткие метки реквизитов не набирают 12 буквенных токенов, требуемых
#: общим эвристическим фильтром разрядки. На `dagestanschool-kais-808.pdf`
#: 11.09.2026 это были именно «корр. счет» и «телефоны»; явный перечень
#: не даёт схлопывать короткие обычные фразы только из-за пробелов.
_SPARSE_REQUISITE_RE = re.compile(
    r"(?:р\s*а\s*с\s*ч\s*е\s*т\s*н\s*ы\s*й\s*с\s*ч\s*[её]\s*т|"
    r"к\s*о\s*р\s*р\s*\.\s*с\s*ч\s*[её]\s*т|"
    r"т\s*е\s*л\s*е\s*ф\s*о\s*н\s*ы)",
    re.IGNORECASE,
)

#: Короткие подписи и наименования не проходят общий порог из 12 токенов,
#: хотя это всё та же разрядка. На `dagestanschool-kais-808.pdf` 11.09.2026
#: фамилия подписанта и аббревиатура ГБПОУ оставались открытыми именно по
#: этой причине; шаблоны узкие, чтобы не склеивать обычную короткую прозу.
_SPARSE_SIGNATORY_RE = re.compile(r"[А-ЯЁ](?:\s+[а-яё]){4,}")
_SPARSE_ORG_RE = re.compile(r"г\s*б\s*п\s*о\s*у\s*р\s*д", re.IGNORECASE)

#: Адреса e-mail в повреждённой строке содержат `®` вместо `@`; это
#: уникальный для OCR-мусора признак, по которому можно включить схлопывание
#: даже для короткого сегмента без обычного отношения одиночных токенов.
_SPARSE_EMAIL_MARKER = "®"
_EMAIL_LABEL_RE = re.compile(r"(?:е|e)-mail(?=[a-z0-9])", re.IGNORECASE)
_EMAIL_CHAIN_BOUNDARY_RE = re.compile(r"(?<=\.ru)(?=[a-z0-9._+-]+@)", re.IGNORECASE)

#: В той же строке таблицы два столбца КПП и ИНН слиплись в
#: `0554010010545011628`. Девятизначный КПП и проверяемый десятизначный ИНН
#: можно разделить без догадки о произвольном цифровом значении; контекст
#: «ИНН»/«КПП» обязателен, чтобы это правило не работало на обычном тексте.
_KPP_INN_RUN_RE = re.compile(r"\d{19}(?!\d)")
#: Метка должна стоять НЕПОСРЕДСТВЕННО перед слипшимся хвостом, а не просто
#: где-то в сегменте: проверка контрольной суммы одна не спасает — casino-
#: шанс ~1/10, что случайные 10 цифр внутри чужого числа (казначейский
#: счёт, 20 разрядов) пройдут её. На `ipklh-2022-01-11.pdf` 14.09.2026
#: «ИНН/КПП» party'и стоит за ~200 символов до «Единого казначейского
#: счёта» — совпадение контрольной суммы вырезало из счёта мнимый второй
#: ИНН и приписывало казначейство профилю стороны.
_KPP_INN_LABEL_WINDOW = 40
_KPP_INN_LABEL_NEAR_RE = re.compile(r"инн|кпп", re.IGNORECASE)

#: Два БИК, записанные одним 18-разрядным хвостом, можно разделить только
#: после метки и только если каждая девятка проходит форматную проверку БИК.
_BIK_RUN_RE = re.compile(r"\d{18,}(?!\d)")

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
    if _has_sparse_layout(chars) or _has_sparse_email_layout(chars):
        chars, mapping = _collapse_sparse_layout(chars, mapping)
        chars, mapping = _split_concatenated_accounts(chars, mapping)
        chars, mapping = _normalize_sparse_phone_separators(chars, mapping)
        chars, mapping = _repair_sparse_phone_glyph(chars, mapping)
        chars, mapping = _split_concatenated_phones(chars, mapping)
    # На `dagestanschool-kais-808.pdf` 11.09.2026 «ИНН / КПП» состоит
    # лишь из шести букв, поэтому не проходит порог разрежённого сегмента.
    # Выполняем разделение после схлопывания: иначе оно снова удаляет
    # вставленную границу. Проверка 19 цифр и контрольной суммы ИНН делает
    # это правило безопасным и для неразрежённой строки.
    chars, mapping = _split_concatenated_kpp_inn(chars, mapping)
    chars, mapping = _split_label_digit(chars, mapping)
    chars, mapping = _split_concatenated_biks(chars, mapping)
    chars, mapping = _normalize_sparse_emails(chars, mapping)
    chars, mapping = _restore_sparse_org_boundaries(chars, mapping)
    chars, mapping = _normalize_sparse_initials(chars, mapping)
    mapping.append(len(text))
    return "".join(chars), mapping


def _is_word(char: str) -> bool:
    return bool(char) and char.isalnum()


def _is_digit(char: str) -> bool:
    return bool(char) and char.isdigit()


def _has_sparse_layout(chars: list[str]) -> bool:
    """Проверить, что разрядкой повреждён именно весь сегмент, а не число."""
    text = "".join(chars)
    short_label_matches = (
        *_SPARSE_REQUISITE_RE.finditer(text),
        *_SPARSE_ORG_RE.finditer(text),
    )
    if any(match.group().count(" ") >= 4 for match in short_label_matches):
        return True
    if _SPARSE_SIGNATORY_RE.search(text):
        return True
    tokens = _WORD_TOKEN_RE.findall(text)
    alpha_tokens = [token for token in tokens if any(char.isalpha() for char in token)]
    if len(alpha_tokens) < _SPARSE_MIN_ALPHA_TOKENS:
        return False
    single_letter_tokens = sum(len(token) == 1 for token in alpha_tokens)
    return single_letter_tokens / len(alpha_tokens) > _SPARSE_TOKEN_RATIO


def _has_sparse_email_layout(chars: list[str]) -> bool:
    """Проверить специальный OCR-маркер разрежённой строки e-mail."""
    return _SPARSE_EMAIL_MARKER in chars


def _collapse_sparse_layout(chars: list[str], idx_map: list[int]) -> tuple[list[str], list[int]]:
    """Убрать разрядочные пробелы, сохранив надёжные границы слов.

    В разрежённом сегменте расстояние между буквами и между словами в
    текстовом слое одинаково. Границы всё же восстанавливаются по смене
    регистра (``Магомедов Абдурахман``) и перед словом после аббревиатуры
    (``ООО Каспий``); остальные пробелы для детекторов несущественны и
    безопаснее удалить, чем оставить разрыв внутри критичного реквизита.
    """
    keep = [True] * len(chars)
    for index, char in enumerate(chars):
        if char != " " or index == 0 or index == len(chars) - 1:
            continue
        before, after = chars[index - 1], chars[index + 1]
        if not (before.isalnum() and after.isalnum()):
            continue
        if before.isdigit() != after.isdigit():
            # На `arkhschool-68-183.pdf` 11.09.2026 колоночный пробел
            # между «1027700198767» и «БАНК» был ошибочно удалён. Любая
            # граница цифра↔буква разделяет реквизит и текст: сохраняем её
            # даже внутри подтверждённо разрежённого сегмента.
            continue
        if before.islower() and after.isupper():
            continue
        if _is_abbreviation_boundary(chars, index):
            continue
        keep[index] = False
    return (
        [char for char, should_keep in zip(chars, keep, strict=True) if should_keep],
        [offset for offset, should_keep in zip(idx_map, keep, strict=True) if should_keep],
    )


def _is_abbreviation_boundary(chars: list[str], space_index: int) -> bool:
    """Есть ли перед пробелом аббревиатура, а после — слово с заглавной."""
    before, after = chars[space_index - 1], chars[space_index + 1]
    if not (before.isupper() and after.isupper()):
        return False
    next_index = space_index + 2
    while next_index < len(chars) and chars[next_index] == " ":
        next_index += 1
    if next_index == len(chars) or not chars[next_index].islower():
        return False
    run_start = space_index - 1
    while run_start > 0 and chars[run_start - 1].isupper():
        run_start -= 1
    return space_index - run_start >= 2


def _split_concatenated_accounts(
    chars: list[str], idx_map: list[int]
) -> tuple[list[str], list[int]]:
    """Разделить кратную 20 цепочку счетов после её явной метки."""
    text = "".join(chars)
    label = _ACCOUNT_LABEL_RE.search(text)
    if label is None:
        return chars, idx_map
    run = _ACCOUNT_RUN_RE.search(text, label.end())
    if run is None or len(run.group()) <= 20 or len(run.group()) % 20:
        return chars, idx_map
    boundaries = set(range(run.start() + 20, run.end(), 20))
    if run.start() == label.end() and run.start() > 0 and text[run.start() - 1].isalnum():
        # На `dagestanschool-kais-808.pdf` 11.09.2026 пробел перед первым
        # счётом исчез вместе с разрядкой метки. Без него правило счёта не
        # видит первые 20 цифр из-за буквенной левой границы.
        boundaries.add(run.start())
    out: list[str] = []
    out_map: list[int] = []
    for index, (char, offset) in enumerate(zip(chars, idx_map, strict=True)):
        if index in boundaries:
            # У вставленного пробела якорь — первый символ следующего счёта:
            # конец первого и начало второго после remap остаются точными.
            out.append(" ")
            out_map.append(offset)
        out.append(char)
        out_map.append(offset)
    return out, out_map


def _repair_sparse_phone_glyph(chars: list[str], idx_map: list[int]) -> tuple[list[str], list[int]]:
    """Исправить одиночную ошибку текстового слоя внутри номера телефона."""
    if "телефон" not in "".join(chars).casefold():
        return chars, idx_map
    # В `dagestanschool-kais-808.pdf` 11.09.2026 цифра «1» во втором
    # телефоне извлекается как латинская `f`. Контекст цифра-`f`-дефис
    # исключает замену букв обычного текста; карта ведёт на исходный `f`,
    # поэтому при маскировании не остаётся и ошибочный символ PDF-слоя.
    repaired = [
        (
            "1"
            if (
                char == "f"
                and 0 < index < len(chars) - 1
                and chars[index - 1].isdigit()
                and chars[index + 1] == "-"
            )
            else char
        )
        for index, char in enumerate(chars)
    ]
    return repaired, idx_map


def _normalize_sparse_phone_separators(
    chars: list[str], idx_map: list[int]
) -> tuple[list[str], list[int]]:
    """Убрать разрядочные пробелы только вокруг дефисов номера телефона."""
    if "телефон" not in "".join(chars).casefold():
        return chars, idx_map
    # В `dagestanschool-kais-808.pdf` 11.09.2026 дефис записан как
    # «цифра пробел дефис пробел цифра». Регулярка телефона допускает один
    # разделитель, поэтому удаляем лишь пробелы около дефиса, не трогая
    # настоящие границы слов в остальном сегменте.
    keep = [
        not (
            char == " "
            and (
                (index > 0 and chars[index - 1] == "-")
                or (index + 1 < len(chars) and chars[index + 1] == "-")
                or (
                    index > 0
                    and chars[index - 1].isdigit()
                    and index + 1 < len(chars)
                    and chars[index + 1] == "f"
                )
            )
        )
        for index, char in enumerate(chars)
    ]
    return (
        [char for char, should_keep in zip(chars, keep, strict=True) if should_keep],
        [offset for offset, should_keep in zip(idx_map, keep, strict=True) if should_keep],
    )


def _split_concatenated_phones(chars: list[str], idx_map: list[int]) -> tuple[list[str], list[int]]:
    """Разделить слипшиеся 11-разрядные мобильные номера после метки."""
    if "телефон" not in "".join(chars).casefold():
        return chars, idx_map
    boundaries: set[int] = set()
    index = 0
    while index < len(chars):
        if chars[index] not in {"7", "8"} or (index > 0 and chars[index - 1].isdigit()):
            index += 1
            continue
        cursor = index
        digits = 0
        while cursor < len(chars) and (chars[cursor].isdigit() or chars[cursor] in {"-", " "}):
            if chars[cursor].isdigit():
                digits += 1
                if digits == 11:
                    next_index = cursor + 1
                    if next_index < len(chars) and chars[next_index].isdigit():
                        # На `dagestanschool-kais-808.pdf` 11.09.2026 два
                        # номера склеены без разделителя: граница известна
                        # по фиксированной длине мобильного номера и только
                        # внутри явно подписанного телефонного поля.
                        boundaries.add(next_index)
                    break
            cursor += 1
        index = max(cursor + 1, index + 1)
    if not boundaries:
        return chars, idx_map
    out: list[str] = []
    out_map: list[int] = []
    for index, (char, offset) in enumerate(zip(chars, idx_map, strict=True)):
        if index in boundaries:
            # Пробел допустим внутри 20-значного счёта, а запятая — нет.
            # На `dagestanschool-kais-808.pdf` 11.09.2026 это не даёт
            # правилу счёта склеить два следующих друг за другом телефона.
            out.append(",")
            out_map.append(offset)
        out.append(char)
        out_map.append(offset)
    return out, out_map


def _split_concatenated_kpp_inn(
    chars: list[str], idx_map: list[int]
) -> tuple[list[str], list[int]]:
    """Отделить ИНН от КПП в слипшейся строке реквизитов."""
    text = "".join(chars)
    if "инн" not in text.casefold() and "кпп" not in text.casefold():
        return chars, idx_map
    boundaries = set()
    for match in _KPP_INN_RUN_RE.finditer(text):
        window_start = max(0, match.start() - _KPP_INN_LABEL_WINDOW)
        if not _KPP_INN_LABEL_NEAR_RE.search(text, window_start, match.start()):
            continue
        if is_valid_inn(match.group()[9:]):
            boundaries.add(match.start() + 9)
    if not boundaries:
        return chars, idx_map
    out: list[str] = []
    out_map: list[int] = []
    for index, (char, offset) in enumerate(zip(chars, idx_map, strict=True)):
        if index in boundaries:
            out.append(" ")
            out_map.append(offset)
        out.append(char)
        out_map.append(offset)
    return out, out_map


def _split_concatenated_biks(chars: list[str], idx_map: list[int]) -> tuple[list[str], list[int]]:
    """Разделить слипшийся хвост из нескольких БИК после явной метки."""
    text = "".join(chars)
    label = re.search(r"\bбик\b", text, re.IGNORECASE)
    if label is None:
        return chars, idx_map
    run = _BIK_RUN_RE.search(text, label.end())
    if run is None or len(run.group()) % 9:
        return chars, idx_map
    chunks = [run.group()[start : start + 9] for start in range(0, len(run.group()), 9)]
    if not all(is_valid_bik(chunk) for chunk in chunks):
        return chars, idx_map
    boundaries = set(range(run.start() + 9, run.end(), 9))
    out: list[str] = []
    out_map: list[int] = []
    for index, (char, offset) in enumerate(zip(chars, idx_map, strict=True)):
        if index in boundaries:
            # На `dagestanschool-kais-808.pdf` 11.09.2026 два БИК были
            # слипшимся хвостом. Повторяем метку, потому что правило БИК
            # сознательно принимает только число после «БИК»; карта
            # привязывает искусственный текст к первой цифре второго БИК.
            out.extend(" БИК ")
            out_map.extend([offset] * len(" БИК "))
        out.append(char)
        out_map.append(offset)
    return out, out_map


def _normalize_sparse_emails(chars: list[str], idx_map: list[int]) -> tuple[list[str], list[int]]:
    """Восстановить пунктуацию и границы e-mail из испорченного PDF-слоя."""
    if _SPARSE_EMAIL_MARKER not in chars:
        return chars, idx_map
    # На `dagestanschool-kais-808.pdf` 11.09.2026 `®` заменяет `@`, а
    # точка/запятая сразу после него — мусор OCR. Преобразование ограничено
    # строкой с этим маркером: товарный знак в обычном тексте не меняем.
    compact_chars: list[str] = []
    compact_map: list[int] = []
    for index, (char, offset) in enumerate(zip(chars, idx_map, strict=True)):
        adjacent_to_separator = (index > 0 and chars[index - 1] in "®.,-") or (
            index + 1 < len(chars) and chars[index + 1] in "®.,-"
        )
        between_email_chars = (
            index > 0
            and index + 1 < len(chars)
            and chars[index - 1].isalnum()
            and chars[index + 1].isalnum()
        )
        if char == " " and (adjacent_to_separator or between_email_chars):
            continue
        replacement = "@" if char == _SPARSE_EMAIL_MARKER else char
        if replacement in ".," and compact_chars and compact_chars[-1] == "@":
            continue
        compact_chars.append(replacement)
        compact_map.append(offset)

    text = "".join(compact_chars)
    boundaries = {match.start() for match in _EMAIL_CHAIN_BOUNDARY_RE.finditer(text)}
    label_boundaries = {match.end() for match in _EMAIL_LABEL_RE.finditer(text)}
    boundaries.update(label_boundaries)
    if not boundaries:
        return compact_chars, compact_map
    out: list[str] = []
    out_map: list[int] = []
    for index, (char, offset) in enumerate(zip(compact_chars, compact_map, strict=True)):
        if index in boundaries:
            # На том же PDF 11.09.2026 «E-mail» и соседние адреса не имели
            # реальной границы в текстовом слое. Вставка нужна только для
            # разделения детекторных спанов, исходный текст она не меняет.
            out.append(" ")
            out_map.append(offset)
        out.append(char)
        out_map.append(offset)
    return out, out_map


def _restore_sparse_org_boundaries(
    chars: list[str], idx_map: list[int]
) -> tuple[list[str], list[int]]:
    """Вернуть пробелы внутри короткого разрежённого названия организации."""
    text = "".join(chars)
    match = re.search(r"гбпоу(?=рд)", text, re.IGNORECASE)
    if match is None:
        return chars, idx_map
    # На `dagestanschool-kais-808.pdf` 11.09.2026 склейка превратила
    # «ГБПОУ РД» в единое слово, из-за чего словарный детектор не видел
    # оргформу. Добавляем только подтверждённую границу этой аббревиатуры.
    boundary = match.end()
    quote_boundary = boundary + 2
    out: list[str] = []
    out_map: list[int] = []
    for index, (char, offset) in enumerate(zip(chars, idx_map, strict=True)):
        if index == match.start():
            # «ГБПОУ» отсутствует в общем словаре оргформ. На
            # `dagestanschool-kais-808.pdf` 11.09.2026 внутренний сигнал
            # «ООО «» нужен только детектору, чтобы он включил весь
            # кавычечный хвост в org_name; карта возвращает его к исходному.
            out.extend("ООО «")
            out_map.extend([offset] * len("ООО «"))
        if index == boundary:
            out.append(" ")
            out_map.append(offset)
        if index == quote_boundary and char in {"я", "«"}:
            out.append(" ")
            out_map.append(offset)
        out.append("«" if char == "я" else char)
        out_map.append(offset)
    return out, out_map


def _normalize_sparse_initials(chars: list[str], idx_map: list[int]) -> tuple[list[str], list[int]]:
    """Собрать инициалы с разрядочными пробелами в форму «Н.Г.»"""
    text = "".join(chars)
    # На `dagestanschool-kais-808.pdf` 11.09.2026 строка подписи была
    # «Магомедов Н .Г .». Убираем только пробелы вокруг точек инициала —
    # границу между фамилией и именем сохраняем для NER.
    remove: set[int] = set()
    for match in re.finditer(r"[А-ЯЁ]\s*\.\s*[А-ЯЁ]\s*\.", text):
        remove.update(index for index in range(match.start(), match.end()) if text[index] == " ")
    if not remove:
        return chars, idx_map
    return (
        [char for index, char in enumerate(chars) if index not in remove],
        [offset for index, offset in enumerate(idx_map) if index not in remove],
    )


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
