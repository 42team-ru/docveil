"""Слой правил: регулярка плюс контрольная сумма. T1.2.

Это фундамент детекции, а не временное решение до подключения модели.
У ИНН, ОГРН, СНИЛС и банковского счёта есть контрольная цифра — значит
precision почти единица достаётся бесплатно, офлайн и мгновенно.
Регулярка на десять цифр срабатывает на каждом номере накладной;
регулярка с проверкой контрольной суммы — практически никогда.

Расчётный и корреспондентский счёт проверяются только в паре с БИК: у них
нет самостоятельной контрольной суммы. Лицевой счёт из 11 цифр принимается
только после его явной метки.
"""

from __future__ import annotations

import re
from ipaddress import AddressValueError, IPv4Address

from masker.detect.checksums import (
    is_valid_account,
    is_valid_bik,
    is_valid_inn,
    is_valid_kpp,
    is_valid_ogrn,
    is_valid_snils,
)
from masker.detect.normalize import normalize_value
from masker.detect.resolve import resolve_overlaps
from masker.model import Document, Entity, EntityType, Segment, Source

#: Сколько соседних сегментов просматривать в поисках БИК для счёта.
BIK_LOOKAROUND = 3

_DIGIT_SEP = r"[\s\-]?"
#: Разделитель, который вдобавок к пробелу и дефису допускает точку —
#: нужен для СНИЛС/телефона в форме «112.233.445.95» / «8.473.250.30.30»
#: (план T2.2.1, Р3). Не используется в остальных типах, чтобы не расширять
#: их формат без нужды.
_DIGIT_SEP_DOT = r"[\s.\-]?"


def _d(n: int) -> str:
    """n цифр, допускающих пробелы и дефисы между собой."""
    return _DIGIT_SEP.join([r"\d"] * n)


def _d_dot(n: int) -> str:
    """n цифр, допускающих пробелы, дефисы и точки между собой."""
    return _DIGIT_SEP_DOT.join([r"\d"] * n)


# Границы \b на кириллице ведут себя неожиданно, поэтому запрещаем цифру
# и слитную букву по краям явным look-around.
_L = r"(?<![\d\w])"
_R = r"(?![\d\w])"
#: Запрет срабатывания внутри более длинной цифровой последовательности —
#: отдельно от `_L`/`_R`, потому что нужен телефону, у которого само тело
#: неоднородно (код города, разделители), а не как у сплошного числа.
#: Корень дефекта Р2: без этого регулярка телефона выедала двенадцать
#: цифр из середины двадцатизначного счёта.
_NOT_IN_DIGIT_RUN_L = r"(?<!\d)"
_NOT_IN_DIGIT_RUN_R = r"(?!\d)"

#: Лицевой счёт — 11 разрядов, поэтому его нельзя искать общей регуляркой:
#: по такой же длине совпадают СНИЛС, ОКТМО и множество служебных кодов.
#: Берём только значение после метки «л/с», «л/сч», «лицевой счёт» либо
#: «лицевого счёта». В казначейских выписках между меткой и значением бывает
#: уточнение вроде «на сайте федерального казначейства», а один разряд может
#: быть буквой (например, ``03061А74190``), поэтому разрешаем ограниченный
#: текстовый мост и одиннадцать буквенно-цифровых знаков.
_PERSONAL_ACCOUNT_RE = re.compile(
    r"(?:\bл\s*/\s*сч?\b|\bлицев(?:ой|ого)\s+сч[её]т(?:а)?\b)"
    r"(?:(?![.;:\n])[\s\w/-]){0,80}?[:№]?\s*"
    r"(?P<value>\d[0-9A-Za-zА-Яа-яЁё]{10})(?![\d\w])",
    re.IGNORECASE,
)

#: Десять цифр без разделителей двусмысленны: это и телефон, и ИНН
#: организации. Принимаем их как телефон только с явным текстовым контекстом
#: либо в строке таблицы, чья колонка названа «Перечень абонентских номеров».
#: Так правило описывает формат и структуру документа, а не отдельный номер.
_PHONE_CONTEXT_RE = re.compile(
    r"(?:контактн\w*\s+телефон\w*|"
    r"номер\w*\s+контактн\w*\s+телефон\w*|"
    r"перечень\s+абонентск\w*\s+номер\w*)",
    re.IGNORECASE,
)
_PHONE_TABLE_HEADER_RE = re.compile(r"перечень\s+абонентск\w*\s+номер\w*", re.IGNORECASE)
_PHONE_TEN_DIGIT_RE = re.compile(rf"{_L}(?P<value>\d{{10}}){_R}")
_PHONE_TABLE_ROW_RE = re.compile(
    r"^\s*\d+\s+(?P<value>\d{10})(?=\s+(?:шт\.?|ед\.?))", re.IGNORECASE
)

#: ИКЗ был 29-значным в раннем формате и стал 36-значным в текущем.
#: Между разрядами в PDF нередко стоят пробелы, поэтому диапазон ищется по
#: метке и числу разрядов, а не по одному конкретному способу группировки.
#: В договорах встречается как полное название, так и сокращение «ИКЗ».
#: Между меткой и числом допускается уточнение: в контрактах рядом стоят
#: «Идентификационный код закупки:» и «Идентификационный код закупки
#: **в плане-графике**:» с разными значениями. Без этого допуска второй код
#: не распознавался целиком, и маскировались только ИНН с КПП внутри него —
#: наружу выходили «24 1» и хвост «0038 000 0000 244» (замерено 11.09.2026
#: на `arkhschool-68-183.pdf`). Уточнение ограничено по длине и не содержит
#: цифр, чтобы метка не притянула число из соседнего предложения.
_IKZ_RE = re.compile(
    r"(?:\bикз\b|идентификационн\w*\s+код\s+закупк\w*)"
    r"(?:\s+[а-яё-]+){0,3}\s*[:№]?\s*"
    r"(?P<value>\d(?:[\s-]?\d){28,35})(?![\d\w])",
    re.IGNORECASE,
)
#: Стандартизированный номер лицензии из государственного реестра.
#: Сочетание кириллической «Л», трёх блоков фиксированной длины и косой
#: черты не пересекается с номером договора или суммой, поэтому отдельная
#: текстовая метка «лицензия» ему не нужна.
_LICENSE_RE = re.compile(rf"{_L}(?P<value>Л\d{{3}}-\d{{5}}-\d{{2}}/\d{{8}}){_R}", re.IGNORECASE)
#: Лицензия ФСБ старого образца записывается не как современный ключ «Л…»,
#: а как код подразделений через косую черту: ``78/78/1346/Н/Н``. Сам по
#: себе такой код не уникален среди служебных обозначений, поэтому формат
#: ниже применяется только вместе с контекстом лицензии в
#: ``_has_fsb_license_context``.
_FSB_LICENSE_RE = re.compile(rf"{_L}(?P<value>\d{{2}}(?:/\d{{2}})?/\d{{3,5}}/[НH](?:/[НH])?){_R}")
_LICENSE_CONTEXT_RE = re.compile(
    r"лицензи\w*|регистрационн\w*\s+номер\w*|на\s+осуществлени\w*",
    re.IGNORECASE,
)
#: Маркеры лицензии в реальных PDF часто стоят в скобках перед описанием
#: деятельности; окна в обе стороны покрывают оба порядка без поиска по
#: всему сегменту.
_FSB_LICENSE_CONTEXT_WINDOW = 160
#: ОКПО — всего восемь цифр и не имеет контрольной суммы. Принимаем его
#: только после точной метки классификатора: голые восьмизначные значения
#: в договорах бывают суммами, количествами и внутренними номерами.
_OKPO_RE = re.compile(r"\bокпо\b\s*[:№]?\s*(?P<value>\d{8})(?![\d\w])", re.IGNORECASE)
#: КБК — 20 разрядов с закреплённым разбиением. Поле позволяет найти
#: заказчика и программу закупки, поэтому маскируется полностью, а не
#: только ведомственный префикс (Р22, 11.09.2026, `arkhschool-68-183.pdf`).
_KBK_RE = re.compile(
    r"\bкбк\b\s*[:№]?\s*"
    r"(?P<value>(?:[0-9A-Za-zА-Яа-яЁё]{3}\s+[0-9A-Za-zА-Яа-яЁё]{4}\s+"
    r"[0-9A-Za-zА-Яа-яЁё]{2}\s+[0-9A-Za-zА-Яа-яЁё]\s+"
    r"[0-9A-Za-zА-Яа-яЁё]{2}\s+[0-9A-Za-zА-Яа-яЁё]{5}\s+"
    r"[0-9A-Za-zА-Яа-яЁё]{3})|[0-9A-Za-zА-Яа-яЁё]{20})(?![\d\w])",
    re.IGNORECASE,
)
#: ОКТМО и ОКАТО раскрывают территорию стороны, но ОКОГУ и ОКВЭД — лишь
#: справочные классификаторы. Поэтому в правило внесены только первые два
#: и исключительно после их собственной метки (Р22, 11.09.2026,
#: `arkhschool-68-183.pdf`).
_TERRITORIAL_CODE_RE = re.compile(
    r"\b(?:октмо|окато)\b\s*[:№]?\s*(?P<value>\d{8}|\d{11})(?![\d\w])",
    re.IGNORECASE,
)
#: БИК из PDF может содержать лишний ноль или два склеенных значения.
#: После метки маскируем весь непрерывный числовой хвост, иначе из
#: `0044525225` оставался бы хотя бы один поисковый ключ (Р22, 11.09.2026,
#: `bashkirschool-usak-kichu2-4149.pdf`).
_LABELED_BIK_RE = re.compile(r"\bбик(?:\s+тофк)?\b\s*[:№]?\s*(?P<value>\d+)(?!\d)", re.IGNORECASE)
#: В XLSX подпись и значение реквизита обычно лежат в соседних ячейках,
#: поэтому строковая регулярка выше их намеренно не видит.
_XLSX_BIK_LABEL_RE = re.compile(r"\s*бик(?:\s+тофк)?\s*[:№]?\s*\Z", re.IGNORECASE)
_XLSX_BIK_VALUE_RE = re.compile(r"\s*(?P<value>\d+)\s*\Z")
#: Номер доверенности — самостоятельный ключ реестра полномочий. Метка
#: обязательна: `№ 109` без неё может быть номером пункта или приложения;
#: запись с косыми чертами покрывает доверенность Ростелекома
#: `01/29/533/23` (Р22, 11.09.2026, `arkhschool-68-183.pdf`).
_POWER_OF_ATTORNEY_RE = re.compile(
    # Между меткой и номером стоит дата: «доверенности от 20 июля 2022 г.
    # № 01/29/533/23». Точка в «г.» есть всегда, поэтому запрещать точку
    # целиком нельзя — иначе номер не находится вовсе. Запрещён только
    # конец предложения (точка перед заглавной буквой), чтобы метка не
    # притянула номер из соседней фразы.
    r"\bдоверенност\w*\b(?:(?!\.\s+[А-ЯЁ])(?![;\n])[^\n]){0,60}?"
    r"№\s*(?P<value>[0-9A-Za-zА-Яа-яЁё]+(?:[/-][0-9A-Za-zА-Яа-яЁё]+)*)(?![\d\w])",
    re.IGNORECASE,
)
#: IP без контекста похож на версию ПО. Метка исключает номера пунктов,
#: а проверка октетов ниже оставляет только публичный адрес абонента
#: (Р22, 11.09.2026, `eat-100034721124100074.pdf`).
_IP_ADDRESS_RE = re.compile(
    r"(?:\bip\s*[-–—]?\s*адрес\w*\b|\bip\b)\s*[:№]?\s*"
    r"(?P<value>\d{1,3}(?:\.\d{1,3}){3})(?![\d.])",
    re.IGNORECASE,
)
_IKZ_EMBEDDED_REQUISITES = frozenset(
    {
        EntityType.BANK_ACCOUNT,
        EntityType.INN,
        EntityType.OGRN,
        EntityType.SNILS,
        EntityType.KPP,
        EntityType.BIK,
    }
)

PATTERNS: dict[EntityType, re.Pattern[str]] = {
    # ИНН не использует _d() — межцифровые пробелы дают ложные срабатывания
    # на числовые таблицы (цены и даты через пробел образуют 10-значный ИНН
    # с правильной контрольной цифрой — статистическое совпадение).
    EntityType.INN: re.compile(rf"{_L}(?:\d{{12}}|\d{{10}}){_R}"),
    EntityType.OGRN: re.compile(rf"{_L}(?:{_d(15)}|{_d(13)}){_R}"),
    # Разделитель СНИЛС допускает и точку: «112.233.445.95» — реальная
    # форма записи, встречается наравне с дефисом (план T2.2.1, Р3).
    EntityType.SNILS: re.compile(rf"{_L}{_d_dot(11)}{_R}"),
    EntityType.BANK_ACCOUNT: re.compile(rf"{_L}{_d(20)}{_R}"),
    EntityType.KPP: re.compile(rf"{_L}\d{{4}}[\dA-Z]{{2}}\d{{3}}{_R}"),
    # Серия — два блока по две цифры (сросшихся или разделённых пробелом/
    # дефисом); между серией и номером кроме обычного разделителя может
    # стоять «№» с необязательными пробелами вокруг: «серия 2004 № 123456»,
    # «20 04 №123456», «2004 123456» (план T2.2.1, Р3).
    EntityType.PASSPORT: re.compile(
        rf"{_L}\d{{2}}{_DIGIT_SEP}\d{{2}}{_DIGIT_SEP}(?:№\s*)?{_DIGIT_SEP}\d{{6}}{_R}"
    ),
    EntityType.EMAIL: re.compile(r"[\w.+-]+@[\w-]+\.[\w]+(?:\.[\w]+)*"),
    # `_NOT_IN_DIGIT_RUN_L/_R` вокруг всего выражения — без них регулярка
    # находила «телефон» внутри произвольной цифровой последовательности
    # (например, середины двадцатизначного счёта), потому что первая
    # альтернатива не проверяла, что перед `+7`/`8` не стоит ещё одна цифра
    # (план T2.2.1, Р2/Р3). Разделитель допускает и точку: «8.473.250.30.30».
    EntityType.PHONE: re.compile(
        rf"{_NOT_IN_DIGIT_RUN_L}"
        rf"(?:(?:\+7|[78]){_DIGIT_SEP_DOT}\(?\d{{3,4}}\)?|\(\d{{3,4}}\))"
        rf"{_DIGIT_SEP_DOT}\d{{2,3}}{_DIGIT_SEP_DOT}\d{{2}}{_DIGIT_SEP_DOT}\d{{2}}"
        rf"{_NOT_IN_DIGIT_RUN_R}"
    ),
    EntityType.SITE: re.compile(r"https?://[^\s,;]+|(?<![\w@])www\.[\w.-]+"),
    # Р12: все федеральные законы с номером до трёх цифр («44-ФЗ», «152-ФЗ»,
    # «436-ФЗ» и т.д.).  Четырёхзначные и длиннее не ловятся — их нет
    # в реестре ФЗ РФ.  Префикс «№» включается в спан; нормализация
    # стирает его перед сравнением.
    EntityType.FEDERAL_LAW: re.compile(r"(?:№\s*)?\b\d{1,3}[- ]?ФЗ\b"),
    # Группа 1 — тело номера без «№»: `гимназия № 144`/`приложение № 1`
    # (короткое, без реального номера) не должны отдавать `№` частью
    # сущности лишь потому, что рядом оказалась цифра (план T2.2.1, Д6).
    # Длина тела ≥5 уже отсекает оба случая сама по себе — контекстный
    # триггер (см. `_has_contract_trigger`) фильтрует остальное.
    # Опциональный кириллический префикс перед первой цифрой покрывает
    # формат «ДП-2024/117» из «ДОГОВОР ПОСТАВКИ № ДП-2024/117».
    EntityType.CONTRACT_NUMBER: re.compile(r"№\s*((?:[А-ЯЁA-Za-z]{1,4}[-])?(?:\d[\d./-]{4,}))"),
}

#: Валидаторы контрольных сумм. Тип без валидатора принимается по формату.
VALIDATORS = {
    EntityType.INN: is_valid_inn,
    EntityType.OGRN: is_valid_ogrn,
    EntityType.SNILS: is_valid_snils,
    EntityType.KPP: is_valid_kpp,
}


def find_biks(segments: list[Segment]) -> dict[int, list[str]]:
    """БИК по сегментам — нужен, чтобы проверить счёт.

    Для хвоста с лишней цифрой рассматриваем все девятизначные окна:
    сам хвост всё равно маскируется целиком, но контрольную сумму счёта
    можно сверить с вложенным настоящим БИК.
    """
    found: dict[int, list[str]] = {}
    for seg in segments:
        hits: list[str] = []
        for match in _LABELED_BIK_RE.finditer(seg.text):
            tail = match.group("value")
            hits.extend(
                tail[offset : offset + 9]
                for offset in range(len(tail) - 8)
                if is_valid_bik(tail[offset : offset + 9])
            )
        if hits:
            found[seg.order] = hits
    for entity in _xlsx_labeled_bik_hits(segments):
        value = entity.text
        hits = [
            value[offset : offset + 9]
            for offset in range(len(value) - 8)
            if is_valid_bik(value[offset : offset + 9])
        ]
        if hits:
            found.setdefault(entity.segment_order, []).extend(hits)
    return found


def _nearby_biks(biks: dict[int, list[str]], order: int) -> list[str]:
    out: list[str] = []
    for delta in range(-BIK_LOOKAROUND, BIK_LOOKAROUND + 1):
        out.extend(biks.get(order + delta, []))
    return out


def _has_passport_context(text: str, start: int, end: int) -> bool:
    """Проверяет, есть ли рядом с числом слова, характерные для паспорта.

    Паспорт не имеет контрольной суммы, поэтому любое 10-значное число
    подходит под формат. Защита от ИНН с битой контрольной цифрой и
    номеров накладных: требуем характерные слова в окрестности.
    """
    # 12.09.2026: в лицензии ФСТЭК слово «лицензия» стоит в описании
    # спана, а не вплотную к номеру серии. Окно 180 символов покрывает весь
    # оборот «серия ... выданную ... лицензии», не меняя правило формата.
    context_start = max(0, start - 180)
    context_end = min(len(text), end + 180)
    context = text[context_start:context_end].lower()

    # Паспорт упоминается с характерными словами
    passport_markers = [
        "паспорт",
        "удостовер",
        "выдан",
        "серия",
        "номер паспорта",
        "документ",
    ]

    # Антимаркеры: если рядом эти слова, точно не паспорт
    anti_markers = [
        "накладная",
        "инн",
        "счет",
        "счёт",
        "договор",
        "заказ",
        # 12.09.2026: «серия ГТ 0253 № 012719» — номер лицензии ФСТЭК,
        # а не паспорт. В лицензии слово «серия» встречается в том же окне.
        "лицензи",
        "фстэк",
        "защиты информации",
        "серия гт",
    ]

    # Проверяем антимаркеры (высокий приоритет)
    if any(marker in context for marker in anti_markers):
        return False

    # Проверяем маркеры паспорта
    return any(marker in context for marker in passport_markers)


#: Метка «КПП» — единственный способ отличить настоящий КПП от произвольного
#: девятизначного числа без контрольной суммы (табличные величины, обрезки
#: телефонов и т.д. — см. план T2.2.1, Д8).
_KPP_LABEL_RE = re.compile(r"кпп", re.IGNORECASE)
#: Окно слева от кандидата, где ищем метку. 40 символов хватает и на
#: «КПП: 668601001» (метка вплотную), и на «ИНН/КПП 6663057404/668601001»
#: (между меткой и вторым значением пары стоит первое значение — тоже
#: число; проверено на реальном документе).
_KPP_LABEL_WINDOW = 40
#: Узкое окно для случая, когда кандидат по формату двусмыслен с БИК
#: (см. `_has_kpp_context`): хватает на «КПП: 042007681» и «КПП 042007681»
#: вплотную, но не дотягивается до метки соседнего поля в плотном блоке
#: реквизитов вроде «ИНН ..., КПП ..., ОГРН ..., БИК ...».
_KPP_TIGHT_LABEL_WINDOW = 15


def _has_kpp_label(text: str, start: int, window: int = _KPP_LABEL_WINDOW) -> bool:
    window_start = max(0, start - window)
    return bool(_KPP_LABEL_RE.search(text[window_start:start]))


def _segment_has_valid_inn(seg: Segment) -> bool:
    """КПП всегда идёт в паре с ИНН того же лица — даже без явной метки
    «КПП» валидный ИНН в том же сегменте достаточное основание доверять
    соседнему девятизначному числу."""
    return any(is_valid_inn(m.group()) for m in PATTERNS[EntityType.INN].finditer(seg.text))


def _has_kpp_context(seg: Segment, start: int, raw: str) -> bool:
    """КПП не пылесосит всё девятизначное (план T2.2.1, шаг 4, Д8):

    без контрольной суммы формат `\\d{4}[\\dA-Z]{2}\\d{3}` совпадает с любым
    девятизначным числом — без контекста в отчёте оказываются граммовки из
    таблиц питания и обрезки телефонов вместо реального КПП.

    Если то же самое число ещё и валидный по формату БИК (тоже девять
    цифр без контрольной суммы) и рядом (в узком окне) нет явной метки
    «КПП», двусмысленное число вернее считать БИК: широкое окно метки
    (40 символов) в плотном блоке реквизитов «ИНН ..., КПП ..., БИК ...»
    иначе цепляет метку соседнего поля, а «валидный ИНН где-то в
    сегменте» справедлив для любого числа по соседству. Без этой оговорки
    таблица приоритетов `resolve.py` (Р2) — где КПП неприкосновенен —
    отдаёт такому числу тип `kpp` вместо `bik`.
    """
    if is_valid_bik(raw) and not _has_kpp_label(seg.text, start, window=_KPP_TIGHT_LABEL_WINDOW):
        return False
    return _has_kpp_label(seg.text, start) or _segment_has_valid_inn(seg)


#: Триггеры номера договора/закупки — только эти корни, без словаря ролей:
#: план T2.2.1, шаг 10, Д6. `№ 144` у гимназии или `№ 1` у приложения не
#: должны стать `contract_number` только потому, что рядом «№» и цифра.
_CONTRACT_NUMBER_TRIGGERS = ("договор", "контракт", "протокол", "извещени", "закупк", "реестров")
#: Окно слева от «№», где ищем триггер — тот же порядок величины, что и у
#: КПП (`_KPP_LABEL_WINDOW`): достаточно захватить «закупочной комиссии от
#: 24.12.2025г. №» целиком, не более того.
_CONTRACT_NUMBER_TRIGGER_WINDOW = 60


def _has_contract_number_trigger(text: str, start: int) -> bool:
    window_start = max(0, start - _CONTRACT_NUMBER_TRIGGER_WINDOW)
    context = text[window_start:start].casefold()
    return any(trigger in context for trigger in _CONTRACT_NUMBER_TRIGGERS)


#: Домены PDF-генераторов: их URL в нижних колонтитулах — не пользовательские данные.
_PDF_GENERATOR_HOSTS = frozenset({"tcpdf.org", "fpdf.org", "wkhtmltopdf.org", "pdfmake.org"})


def _is_pdf_generator_url(url: str) -> bool:
    host = url.lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")
    host = host.split("/")[0].split("?")[0]
    return host in _PDF_GENERATOR_HOSTS


#: Типы, чей формат теперь допускает точку как разделитель цифр (план
#: T2.2.1, Р3: СНИЛС `112.233.445.95`, телефон `8.473.250.30.30`) — но ни
#: `checksums._digits` (понимает только пробел и дефис), ни
#: `normalize.normalize_value` (для «цифровых» типов вырезает только
#: `[\s-]`) о точке не знают.
_DOT_TOLERANT_TYPES = frozenset({EntityType.SNILS, EntityType.PHONE})


def _sanitize_for_checksum(etype: EntityType, value: str) -> str:
    """Убрать из значения разделители, которых не ждут `checksums.py`/
    `normalize.py`, не трогая типы, где точка или «№» — часть смысла
    (email, сайт).

    Используется исключительно для проверки контрольной суммы и расчёта
    нормализованного ключа — сохранённый `Entity.text` остаётся ровно тем,
    что совпало в тексте (иначе нарушится инвариант `DetectAgent._validate`:
    текст сущности должен совпадать со срезом сегмента).
    """
    if etype in _DOT_TOLERANT_TYPES:
        value = value.replace(".", "")
    if etype is EntityType.PASSPORT:
        # «№» между серией и номером (план T2.2.1, Р3) — не часть значения.
        value = value.replace("№", "")
    return value


def _account_validated(raw: str, seg: Segment, biks: dict[int, list[str]]) -> bool:
    """Сошлась ли контрольная сумма счёта хотя бы с одним соседним БИК."""
    near = _nearby_biks(biks, seg.order)
    return any(is_valid_account(raw, b) for b in near)


def _personal_account_hits(seg: Segment) -> list[Entity]:
    """Вернуть 11-разрядные лицевые счета с обязательной соседней меткой."""
    return [
        Entity(
            type=EntityType.BANK_ACCOUNT,
            text=match.group("value"),
            segment_order=seg.order,
            start=match.start("value"),
            end=match.end("value"),
            source=Source.RULE,
            # Контекстная метка — формальная проверка для счёта, у которого
            # нет контрольной суммы и нельзя применить проверку БИК.
            confidence=1.0,
            normalized=normalize_value(EntityType.BANK_ACCOUNT, match.group("value")),
        )
        for match in _PERSONAL_ACCOUNT_RE.finditer(seg.text)
    ]


def _contextual_phone_hits(segments: list[Segment]) -> list[Entity]:
    """Вернуть десятизначные телефоны только из явно телефонного контекста."""
    has_phone_table = any(_PHONE_TABLE_HEADER_RE.search(segment.text) for segment in segments)
    hits: list[Entity] = []
    for segment in segments:
        if _PHONE_CONTEXT_RE.search(segment.text):
            matches = _PHONE_TEN_DIGIT_RE.finditer(segment.text)
        elif has_phone_table:
            matches = _PHONE_TABLE_ROW_RE.finditer(segment.text)
        else:
            continue
        for match in matches:
            value = match.group("value")
            hits.append(
                Entity(
                    type=EntityType.PHONE,
                    text=value,
                    segment_order=segment.order,
                    start=match.start("value"),
                    end=match.end("value"),
                    source=Source.RULE,
                    confidence=0.9,
                    normalized=normalize_value(EntityType.PHONE, value),
                )
            )
    return hits


def _labeled_bik_hits(seg: Segment) -> list[Entity]:
    """Вернуть БИК как весь числовой хвост после его метки."""
    return [
        Entity(
            type=EntityType.BIK,
            text=match.group("value"),
            segment_order=seg.order,
            start=match.start("value"),
            end=match.end("value"),
            source=Source.RULE,
            confidence=1.0,
            normalized=normalize_value(EntityType.BIK, match.group("value")),
        )
        for match in _LABELED_BIK_RE.finditer(seg.text)
    ]


def _xlsx_labeled_bik_hits(segments: list[Segment]) -> list[Entity]:
    """Вернуть БИК из ячейки справа от точной табличной метки XLSX.

    Метка из другой строки или листа не подходит: в таблицах с плотными
    реквизитами это создало бы ложную связь между независимыми полями.
    """
    cells: dict[tuple[str, int, int], Segment] = {}
    for segment in segments:
        locator = segment.anchor.locator
        if (
            len(locator) == 4
            and locator[0] == "cell"
            and isinstance(locator[1], str)
            and isinstance(locator[2], int)
            and isinstance(locator[3], int)
        ):
            cells[(locator[1], locator[2], locator[3])] = segment

    hits: list[Entity] = []
    for (sheet_name, row, column), label_segment in cells.items():
        if not _XLSX_BIK_LABEL_RE.fullmatch(label_segment.text):
            continue
        value_segment = cells.get((sheet_name, row, column + 1))
        if value_segment is None:
            continue
        value_match = _XLSX_BIK_VALUE_RE.fullmatch(value_segment.text)
        if value_match is None:
            continue
        # 11.09.2026: маскируем БИК из отдельной value-ячейки, иначе он
        # обходит план и остаётся в XML marker- и blackbox-вариантов.
        hits.append(
            Entity(
                type=EntityType.BIK,
                text=value_match.group("value"),
                segment_order=value_segment.order,
                start=value_match.start("value"),
                end=value_match.end("value"),
                source=Source.RULE,
                confidence=1.0,
                normalized=normalize_value(EntityType.BIK, value_match.group("value")),
            )
        )
    return hits


def _power_of_attorney_hits(seg: Segment) -> list[Entity]:
    """Вернуть номера доверенностей только с контекстной меткой."""
    return [
        Entity(
            type=EntityType.POWER_OF_ATTORNEY_NUMBER,
            text=match.group("value"),
            segment_order=seg.order,
            start=match.start("value"),
            end=match.end("value"),
            source=Source.RULE,
            confidence=1.0,
            normalized=normalize_value(EntityType.POWER_OF_ATTORNEY_NUMBER, match.group("value")),
        )
        for match in _POWER_OF_ATTORNEY_RE.finditer(seg.text)
    ]


def _is_public_ipv4(value: str) -> bool:
    """Проверить, что IPv4 действительно глобально маршрутизируется."""
    try:
        return IPv4Address(value).is_global
    except AddressValueError:
        return False


def _ip_address_hits(seg: Segment) -> list[Entity]:
    """Вернуть публичные IPv4, записанные после метки IP-адреса."""
    return [
        Entity(
            type=EntityType.IP_ADDRESS,
            text=match.group("value"),
            segment_order=seg.order,
            start=match.start("value"),
            end=match.end("value"),
            source=Source.RULE,
            confidence=1.0,
            normalized=normalize_value(EntityType.IP_ADDRESS, match.group("value")),
        )
        for match in _IP_ADDRESS_RE.finditer(seg.text)
        if _is_public_ipv4(match.group("value"))
    ]


def _ikz_ranges(text: str) -> list[tuple[int, int]]:
    """Диапазоны ИКЗ, внутри которых реквизиты не ищутся по частям."""
    return [(match.start("value"), match.end("value")) for match in _IKZ_RE.finditer(text)]


def _overlaps_ikz(start: int, end: int, ikz_ranges: list[tuple[int, int]]) -> bool:
    return any(ikz_start < end and start < ikz_end for ikz_start, ikz_end in ikz_ranges)


def _has_fsb_license_context(text: str, start: int, end: int) -> bool:
    """Есть ли рядом с номером ФСБ признак именно лицензии.

    Формат старой лицензии ФСБ не обладает проверяемой контрольной суммой.
    Поэтому отдельного совпадения цифр и букв недостаточно: берём только
    номер возле слова «лицензия», «регистрационный номер» или описания
    лицензируемой деятельности «на осуществление».
    """
    context_start = max(0, start - _FSB_LICENSE_CONTEXT_WINDOW)
    context_end = min(len(text), end + _FSB_LICENSE_CONTEXT_WINDOW)
    return bool(_LICENSE_CONTEXT_RE.search(text[context_start:context_end]))


def _registry_key_hits(seg: Segment) -> list[Entity]:
    """Найти значения, по которым сторону можно открыть в публичном реестре.

    ОКПО опирается на явную метку, ИКЗ и современный номер лицензии имеют
    достаточно строгий собственный формат, а у старого номера ФСБ есть
    дополнительный контекст лицензии. Во всех случаях в сущность входит
    только значение, не заголовок поля: так замена не оставляет хвост ИКЗ и
    не уничтожает поясняющий текст документа.
    """
    hits: list[Entity] = []
    for pattern in (_IKZ_RE, _LICENSE_RE, _OKPO_RE, _KBK_RE, _TERRITORIAL_CODE_RE, _FSB_LICENSE_RE):
        for match in pattern.finditer(seg.text):
            value = match.group("value")
            if pattern is _FSB_LICENSE_RE and not _has_fsb_license_context(
                seg.text, match.start("value"), match.end("value")
            ):
                continue
            hits.append(
                Entity(
                    type=EntityType.REGISTRY_KEY,
                    text=value,
                    segment_order=seg.order,
                    start=match.start("value"),
                    end=match.end("value"),
                    source=Source.RULE,
                    confidence=1.0,
                    normalized=normalize_value(EntityType.REGISTRY_KEY, value),
                )
            )
    return hits


def _accept(etype: EntityType, raw: str, seg: Segment, biks: dict[int, list[str]]) -> bool:
    """Проходит ли кандидат проверку своего типа."""
    if etype is EntityType.BANK_ACCOUNT:
        # Формат (ровно 20 цифр с проверкой границ) уже достаточно строг —
        # кандидат принимается всегда, а `_confidence` отдельно решает,
        # прошла ли контрольная сумма. Раньше «рядом есть БИК, но с ним
        # счёт не сходится» отбрасывало счёт целиком — тот же счёт без
        # всякого БИК рядом находился нормально, только с уверенностью
        # 0.75. Recall важнее precision для критичного типа (план T2.2.1,
        # Р2/Р3): найденный рядом БИК может относиться к другому реквизиту
        # (например, к соседнему корсчёту), а не быть парой именно этому
        # счёту — это не повод молчать о самом счёте.
        return True
    if etype is EntityType.SITE:
        return not _is_pdf_generator_url(raw)
    validator = VALIDATORS.get(etype)
    return validator is None or validator(_sanitize_for_checksum(etype, raw))


def _confidence(etype: EntityType, raw: str, seg: Segment, biks: dict[int, list[str]]) -> float:
    if etype is EntityType.BANK_ACCOUNT:
        # Формат сошёлся; контрольная сумма — только если рядом нашёлся
        # БИК, с которым она сходится (иначе проверить нечем, либо БИК
        # относится не к этому счёту).
        return 1.0 if _account_validated(raw, seg, biks) else 0.75
    return 1.0 if etype in VALIDATORS else 0.9


def detect_by_rules(segments: list[Segment]) -> list[Entity]:
    """Найти все сущности, у которых есть надёжное формальное правило."""
    biks = find_biks(segments)
    contextual_phones = _contextual_phone_hits(segments)
    phone_ranges: dict[int, set[tuple[int, int]]] = {}
    for phone in contextual_phones:
        phone_ranges.setdefault(phone.segment_order, set()).add((phone.start, phone.end))
    raw_hits: list[Entity] = []
    for seg in segments:
        ikz_ranges = _ikz_ranges(seg.text)
        raw_hits.extend(_registry_key_hits(seg))
        raw_hits.extend(_labeled_bik_hits(seg))
        raw_hits.extend(_power_of_attorney_hits(seg))
        raw_hits.extend(_ip_address_hits(seg))
        for etype, pattern in PATTERNS.items():
            for m in pattern.finditer(seg.text):
                # Номер договора живёт в группе 1 — сущность не включает
                # «№» и разделитель, чтобы совпасть с уже выверенной
                # разметкой (`fixtures/labeled/*.labels.json` хранят тело
                # номера без «№», план T2.2.1, шаг 10).
                if etype is EntityType.CONTRACT_NUMBER:
                    value = m.group(1)
                    start, end = m.start(1), m.end(1)
                else:
                    value = m.group()
                    start, end = m.start(), m.end()
                # В явном телефонном поле десять цифр — телефон, даже если
                # случайно проходят контрольную сумму ИНН. Контекст здесь
                # сильнее совпадения длины и сохраняет правильный тип в
                # отчёте и маркере.
                if etype is EntityType.INN and (start, end) in phone_ranges.get(seg.order, set()):
                    continue
                # ИКЗ — самостоятельный реестровый ключ, а не контейнер
                # для банковского счёта, ИНН или КПП. Его маскирует
                # `_registry_key_hits` целиком; здесь не даём реквизитам
                # раздробить его на части и оставить поисковый хвост.
                if etype in _IKZ_EMBEDDED_REQUISITES and _overlaps_ikz(start, end, ikz_ranges):
                    continue
                # HTTP-ссылки нередко заканчиваются точкой конца предложения,
                # которая не является частью URL.
                if etype is EntityType.SITE and value.startswith("http"):
                    stripped = value.rstrip(".,;!?")
                    end -= len(value) - len(stripped)
                    value = stripped
                if not _accept(etype, value, seg, biks):
                    continue

                # Паспорт требует проверки контекста (нет контрольной суммы)
                if etype is EntityType.PASSPORT and not _has_passport_context(seg.text, start, end):
                    continue

                # КПП требует контекста (нет контрольной суммы) — иначе
                # пылесосит любое девятизначное число (Д8, план T2.2.1).
                if etype is EntityType.KPP and not _has_kpp_context(seg, start, value):
                    continue

                # Номер договора требует триггера слева от «№» (нет
                # контрольной суммы) — иначе «гимназия № 144» и
                # «приложение № 1» тоже стали бы contract_number.
                if etype is EntityType.CONTRACT_NUMBER and not _has_contract_number_trigger(
                    seg.text, m.start()
                ):
                    continue

                raw_hits.append(
                    Entity(
                        type=etype,
                        text=value,
                        segment_order=seg.order,
                        start=start,
                        end=end,
                        source=Source.RULE,
                        confidence=_confidence(etype, value, seg, biks),
                        normalized=normalize_value(etype, _sanitize_for_checksum(etype, value)),
                    )
                )
        raw_hits.extend(_personal_account_hits(seg))
    raw_hits.extend(_xlsx_labeled_bik_hits(segments))
    raw_hits.extend(contextual_phones)
    return resolve_overlaps(raw_hits)


class RuleDetector:
    """Адаптер слоя регулярных правил к общему контракту детекторов."""

    name = "rules"
    source = Source.RULE
    priority = 100
    types: frozenset[str] = frozenset(
        (
            *PATTERNS,
            EntityType.REGISTRY_KEY,
            EntityType.BIK,
            EntityType.POWER_OF_ATTORNEY_NUMBER,
            EntityType.IP_ADDRESS,
        )
    )

    def detect(self, document: Document) -> list[Entity]:
        """Найти формальные сущности с checksum-валидацией."""
        return detect_by_rules(document.segments)
