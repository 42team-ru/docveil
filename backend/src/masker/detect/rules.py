"""Слой правил: регулярка плюс контрольная сумма. T1.2.

Это фундамент детекции, а не временное решение до подключения модели.
У ИНН, ОГРН, СНИЛС и банковского счёта есть контрольная цифра — значит
precision почти единица достаётся бесплатно, офлайн и мгновенно.
Регулярка на десять цифр срабатывает на каждом номере накладной;
регулярка с проверкой контрольной суммы — практически никогда.

Счёт проверяется только в паре с БИК: у него нет самостоятельной
контрольной суммы. БИК ищется в том же сегменте или в соседних.
"""

from __future__ import annotations

import re

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
    EntityType.BIK: re.compile(rf"{_L}{_d(9)}{_R}"),
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
        rf"(?:(?:\+7|8){_DIGIT_SEP_DOT}\(?\d{{3,4}}\)?|\(\d{{3,4}}\))"
        rf"{_DIGIT_SEP_DOT}\d{{2,3}}{_DIGIT_SEP_DOT}\d{{2}}{_DIGIT_SEP_DOT}\d{{2}}"
        rf"{_NOT_IN_DIGIT_RUN_R}"
    ),
    EntityType.SITE: re.compile(r"https?://[^\s,;]+|(?<![\w@])www\.[\w.-]+"),
    # Федеральные законы о закупках: «44-ФЗ», «223 ФЗ», «615ФЗ», «275-ФЗ».
    # Множество фиксировано — добавлять числа следует только при появлении
    # нового закона о закупках, не для всяких «№ 123-ФЗ».
    EntityType.FEDERAL_LAW: re.compile(r"\b(44|223|615|275)[- ]?ФЗ\b"),
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
    EntityType.BIK: is_valid_bik,
    EntityType.KPP: is_valid_kpp,
}


def find_biks(segments: list[Segment]) -> dict[int, list[str]]:
    """БИК по сегментам — нужен, чтобы проверить счёт."""
    found: dict[int, list[str]] = {}
    for seg in segments:
        hits = [
            m.group()
            for m in PATTERNS[EntityType.BIK].finditer(seg.text)
            if is_valid_bik(m.group())
        ]
        if hits:
            found[seg.order] = hits
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
    # Окно контекста: ~50 символов до и после
    context_start = max(0, start - 50)
    context_end = min(len(text), end + 50)
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
    raw_hits: list[Entity] = []
    for seg in segments:
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
    return resolve_overlaps(raw_hits)


class RuleDetector:
    """Адаптер слоя регулярных правил к общему контракту детекторов."""

    name = "rules"
    source = Source.RULE
    priority = 100
    types: frozenset[str] = frozenset(PATTERNS)

    def detect(self, document: Document) -> list[Entity]:
        """Найти формальные сущности с checksum-валидацией."""
        return detect_by_rules(document.segments)
