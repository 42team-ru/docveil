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
from collections.abc import Iterable

from masker.detect.checksums import (
    is_valid_account,
    is_valid_bik,
    is_valid_inn,
    is_valid_kpp,
    is_valid_ogrn,
    is_valid_snils,
)
from masker.detect.normalize import normalize_value
from masker.model import Document, Entity, EntityType, Segment, Source

#: Сколько соседних сегментов просматривать в поисках БИК для счёта.
BIK_LOOKAROUND = 3

_DIGIT_SEP = r"[\s\-]?"


def _d(n: int) -> str:
    """n цифр, допускающих пробелы и дефисы между собой."""
    return _DIGIT_SEP.join([r"\d"] * n)


# Границы \b на кириллице ведут себя неожиданно, поэтому запрещаем цифру
# и слитную букву по краям явным look-around.
_L = r"(?<![\d\w])"
_R = r"(?![\d\w])"

PATTERNS: dict[EntityType, re.Pattern[str]] = {
    # ИНН не использует _d() — межцифровые пробелы дают ложные срабатывания
    # на числовые таблицы (цены и даты через пробел образуют 10-значный ИНН
    # с правильной контрольной цифрой — статистическое совпадение).
    EntityType.INN: re.compile(rf"{_L}(?:\d{{12}}|\d{{10}}){_R}"),
    EntityType.OGRN: re.compile(rf"{_L}(?:{_d(15)}|{_d(13)}){_R}"),
    EntityType.SNILS: re.compile(rf"{_L}{_d(11)}{_R}"),
    EntityType.BANK_ACCOUNT: re.compile(rf"{_L}{_d(20)}{_R}"),
    EntityType.BIK: re.compile(rf"{_L}{_d(9)}{_R}"),
    EntityType.KPP: re.compile(rf"{_L}\d{{4}}[\dA-Z]{{2}}\d{{3}}{_R}"),
    EntityType.PASSPORT: re.compile(rf"{_L}\d{{2}}{_DIGIT_SEP}\d{{2}}{_DIGIT_SEP}\d{{6}}{_R}"),
    EntityType.EMAIL: re.compile(r"[\w.+-]+@[\w-]+\.[\w]+(?:\.[\w]+)*"),
    EntityType.PHONE: re.compile(
        r"(?:(?:\+7|8)[\s\-]?\(?\d{3,4}\)?|(?<!\d)\(\d{3,4}\))[\s\-]?\d{2,3}[\s\-]?\d{2}[\s\-]?\d{2}"
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

#: Порядок разрешения пересечений внутри слоя правил: длинное и строго
#: проверяемое побеждает короткое. Счёт (20 цифр) не должен распадаться
#: на СНИЛС плюс мусор, а ИНН из 12 цифр — на СНИЛС.
PRIORITY = [
    EntityType.BANK_ACCOUNT,
    EntityType.OGRN,
    EntityType.INN,
    EntityType.SNILS,
    EntityType.PASSPORT,
    EntityType.BIK,
    EntityType.KPP,
    EntityType.EMAIL,
    EntityType.PHONE,
    EntityType.SITE,
    # В хвосте: номер закупки/протокола не должен отбирать перекрытие у
    # реквизита с контрольной суммой (план T2.2.1, шаг 10, Д6).
    EntityType.CONTRACT_NUMBER,
    EntityType.FEDERAL_LAW,
]


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


def _has_kpp_label(text: str, start: int) -> bool:
    window_start = max(0, start - _KPP_LABEL_WINDOW)
    return bool(_KPP_LABEL_RE.search(text[window_start:start]))


def _segment_has_valid_inn(seg: Segment) -> bool:
    """КПП всегда идёт в паре с ИНН того же лица — даже без явной метки
    «КПП» валидный ИНН в том же сегменте достаточное основание доверять
    соседнему девятизначному числу."""
    return any(is_valid_inn(m.group()) for m in PATTERNS[EntityType.INN].finditer(seg.text))


def _has_kpp_context(seg: Segment, start: int) -> bool:
    """КПП не пылесосит всё девятизначное (план T2.2.1, шаг 4, Д8):

    без контрольной суммы формат `\\d{4}[\\dA-Z]{2}\\d{3}` совпадает с любым
    девятизначным числом — без контекста в отчёте оказываются граммовки из
    таблиц питания и обрезки телефонов вместо реального КПП.
    """
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


def _accept(etype: EntityType, raw: str, seg: Segment, biks: dict[int, list[str]]) -> bool:
    """Проходит ли кандидат проверку своего типа."""
    if etype is EntityType.BANK_ACCOUNT:
        # Без БИК проверить счёт нечем. Recall важнее precision: принимаем,
        # но такой счёт получит пониженную уверенность.
        near = _nearby_biks(biks, seg.order)
        return not near or any(is_valid_account(raw, b) for b in near)
    if etype is EntityType.SITE:
        return not _is_pdf_generator_url(raw)
    validator = VALIDATORS.get(etype)
    return validator is None or validator(raw)


def _confidence(etype: EntityType, raw: str, seg: Segment, biks: dict[int, list[str]]) -> float:
    if etype is EntityType.BANK_ACCOUNT:
        near = _nearby_biks(biks, seg.order)
        if not near:
            return 0.75  # формат сошёлся, контрольную сумму проверить нечем
        return 1.0
    return 1.0 if etype in VALIDATORS else 0.9


def _overlaps(a: Entity, b: Entity) -> bool:
    return a.segment_order == b.segment_order and a.start < b.end and b.start < a.end


def resolve_overlaps(found: Iterable[Entity]) -> list[Entity]:
    """Убрать пересечения по приоритету типов, затем по длине."""
    rank: dict[str, int] = {t: i for i, t in enumerate(PRIORITY)}
    ordered = sorted(
        found,
        key=lambda e: (rank.get(e.type, len(PRIORITY)), -(e.end - e.start), e.start),
    )
    kept: list[Entity] = []
    for cand in ordered:
        if not any(_overlaps(cand, k) for k in kept):
            kept.append(cand)
    return sorted(kept, key=lambda e: (e.segment_order, e.start))


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
                if etype is EntityType.KPP and not _has_kpp_context(seg, start):
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
                        normalized=normalize_value(etype, value),
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
