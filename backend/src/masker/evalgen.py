"""Метаморфный корпус детекции: те же значения в другом написании.

Зачем. `make eval` печатал recall 1.0 по критичным типам — но это recall на
176 сущностях, записанных ровно так, как их записал человек, размечавший
корпус. Метрика измеряла корпус, а не детектор: те же самые значения в
другом написании находятся 14 раз из 27 (`spikes/detect_metamorphic_spike.py`).

Этот модуль берёт каждую уже размеченную сущность из
``fixtures/labeled/*.labels.json`` и порождает варианты написания —
разметка (какой тип и какое каноническое значение стоит за вариантом)
рождается вместе с текстом, руками размечать нечего. Контрольные суммы не
трогаются: генератор возмущает только форму записи (разрядку, пробелы,
регистр метки), а не сами цифры.

Детерминизм — обязательное условие приёмки: ни `random`, ни время, ни
порядок обхода файловой системы не должны влиять на результат. Все обходы
идут по отсортированным ключам.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

from masker.detect.agent import DetectAgent
from masker.detect.normalize import normalize_value
from masker.model import Anchor, Document, EntityType, Segment

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "labeled"

#: Пробельные варианты (категория 2 плана К1): неразрывный, узкий, волосяной,
#: zero-width. Значения — сами литеры Unicode, не экранированные имена.
NBSP = " "
THIN_SPACE = " "
HAIR_SPACE = " "
ZERO_WIDTH = "​"

_SPACE_VARIANTS: tuple[tuple[str, str], ...] = (
    ("неразрывный пробел", NBSP),
    ("узкий пробел", THIN_SPACE),
    ("волосяной пробел", HAIR_SPACE),
    ("zero-width пробел", ZERO_WIDTH),
)

#: Числовые типы, для которых применимы категории 1–6, 8 (разрядка, пробелы,
#: перенос строки, гомоглифы в метке, слитно/скобки, альтернативные подписи,
#: опечатки в метке). Персона (категория 7) обрабатывается отдельно —
#: у неё нет ни цифр, ни контрольной суммы.
_DIGIT_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.INN,
        EntityType.KPP,
        EntityType.OGRN,
        EntityType.SNILS,
        EntityType.BANK_ACCOUNT,
        EntityType.BIK,
        EntityType.PASSPORT,
        EntityType.PHONE,
    }
)

#: Каноническая метка слева от значения — используется как база для
#: категорий 2/3/4/5/8 (альтернативные подписи из категории 6 — отдельный
#: список ``_ALT_LABELS``).
_CANON_LABEL: dict[EntityType, str] = {
    EntityType.INN: "ИНН",
    EntityType.KPP: "КПП",
    EntityType.OGRN: "ОГРН",
    EntityType.SNILS: "СНИЛС",
    EntityType.BANK_ACCOUNT: "р/с",
    EntityType.BIK: "БИК",
    EntityType.PASSPORT: "паспорт серия",
    EntityType.PHONE: "тел.",
}

#: Альтернативные подписи (категория 6 плана К1).
_ALT_LABELS: dict[EntityType, tuple[str, ...]] = {
    EntityType.BANK_ACCOUNT: ("р/сч", "расч. счёт", "расчётный счёт"),
    EntityType.OGRN: ("ОГРНИП",),
    EntityType.PHONE: ("тел.", "телефон"),
}

#: Опечатки в метке (категория 8 плана К1) — только там, где реальная опечатка
#: наблюдалась в практике («ИИН» вместо «ИНН» и т. п.); придумывать опечатки
#: для типов, где их никто не видел, смысла нет.
_LABEL_TYPOS: dict[EntityType, str] = {
    EntityType.INN: "ИИН",
    EntityType.SNILS: "СНИСЛ",
    EntityType.OGRN: "ОРГН",
}

#: Гомоглифы кириллица→латиница для метки (категория 4). Ограничено буквами,
#: у которых есть визуально неотличимый латинский двойник — остальные буквы
#: метки остаются кириллическими, как в реальной опечатке при переключённой
#: раскладке.
_HOMOGLYPHS = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "Е": "E",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "У": "Y",
        "Х": "X",
    }
)

#: Родительный падеж имени (категория 7) для набора имён, встречающихся в
#: этом фиксированном корпусе. Это не морфологический решатель общего вида —
#: только явная таблица под конкретные значения `fixtures/labeled/*`, что и
#: проверяет `test_evalgen.py::test_genitive_matches_corpus_reality`.
_GENITIVE_GIVEN_NAME: dict[str, str] = {
    "иван": "ивана",
    "пётр": "петра",
    "анна": "анны",
    "мария": "марии",
    "олег": "олега",
    "ирина": "ирины",
    "светлана": "светланы",
    "татьяна": "татьяны",
    "борис": "бориса",
}


def _digits_only(text: str) -> str:
    return re.sub(r"\D", "", text)


def _load_corpus_entities() -> list[dict[str, str]]:
    """Все сущности всех размеченных документов, в детерминированном порядке."""
    entities: list[dict[str, str]] = []
    for path in sorted(FIXTURES.glob("*.labels.json")):
        labels = json.loads(path.read_text(encoding="utf-8"))
        for item in labels.get("entities", []):
            entry = dict(item)
            entry["_source_file"] = path.name
            entities.append(entry)
    return entities


def _unique_values(entities: list[dict[str, str]], entity_type: str) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for item in entities:
        if item["type"] != entity_type:
            continue
        text = item["text"]
        if text in seen:
            continue
        seen.add(text)
        values.append(text)
    return sorted(values)


def _inn_kpp_pairs(entities: list[dict[str, str]]) -> list[tuple[str, str]]:
    """Пары (ИНН, КПП) одной стороны одного договора — для категории 6
    («ИНН/КПП» слитной подписью). Порядок — по файлу, потом по стороне."""
    by_file_party: dict[tuple[str, str], dict[str, str]] = {}
    for item in entities:
        party = item.get("party")
        if not party or item["type"] not in ("inn", "kpp"):
            continue
        key = (item["_source_file"], party)
        by_file_party.setdefault(key, {})[item["type"]] = item["text"]
    pairs: set[tuple[str, str]] = set()
    for values in by_file_party.values():
        if "inn" in values and "kpp" in values:
            pairs.add((values["inn"], values["kpp"]))
    return sorted(pairs)


@dataclass(frozen=True, slots=True)
class MetamorphicCase:
    """Один синтетический сегмент плюс сущности, которые обязаны в нём найтись.

    ``expected`` — пары (тип, канонический ключ). Канонический ключ для
    числовых типов — голая строка цифр (перестановки разделителей не должны
    на него влиять), для персоны — ``normalize_value(PERSON, …)`` варианта,
    который сам же и посажен в текст (см. docstring ``_person_cases``).
    """

    category: str
    variant: str
    text: str
    expected: tuple[tuple[str, str], ...]


def _digit_cases(entity_type: EntityType, value: str) -> list[MetamorphicCase]:
    digits = _digits_only(value)
    if not digits:
        return []
    label = _CANON_LABEL[entity_type]
    cases: list[MetamorphicCase] = []
    expect = ((str(entity_type), digits),)

    # 1. Разрядка: пробел между каждой цифрой.
    cases.append(MetamorphicCase("разрядка", label, f"{label} {' '.join(digits)}", expect))

    # 2. Пробельные варианты: спецсимвол пробела на стыке двух групп цифр.
    mid = len(digits) // 2
    for name, char in _SPACE_VARIANTS:
        spaced = f"{digits[:mid]}{char}{digits[mid:]}" if mid else digits
        cases.append(MetamorphicCase("пробельные варианты", name, f"{label} {spaced}", expect))

    # 3. Перенос строки внутри значения (штатный выход PDF-парсера).
    if mid:
        wrapped = f"{digits[:mid]}\n{digits[mid:]}"
        cases.append(MetamorphicCase("перенос строки", label, f"{label} {wrapped}", expect))

    # 4. Гомоглифы кириллица/латиница в метке, не в цифрах.
    home_label = label.translate(_HOMOGLYPHS)
    if home_label != label:
        cases.append(
            MetamorphicCase("гомоглифы в метке", home_label, f"{home_label} {digits}", expect)
        )

    # 5. Слитное написание и скобки.
    cases.append(MetamorphicCase("слитно и в скобках", label, f"({label}{digits})", expect))

    # 6. Альтернативные подписи.
    for alt in _ALT_LABELS.get(entity_type, ()):
        cases.append(MetamorphicCase("альтернативные подписи", alt, f"{alt} {digits}", expect))

    # 8. Опечатки в метке.
    typo = _LABEL_TYPOS.get(entity_type)
    if typo:
        cases.append(MetamorphicCase("опечатки в метке", typo, f"{typo} {digits}", expect))

    return cases


def _inn_kpp_combined_cases(pairs: list[tuple[str, str]]) -> list[MetamorphicCase]:
    """Категория 6: «ИНН/КПП 100/200» — одна подпись на два значения."""
    cases: list[MetamorphicCase] = []
    for inn, kpp in pairs:
        inn_digits = _digits_only(inn)
        kpp_digits = _digits_only(kpp)
        text = f"ИНН/КПП {inn_digits}/{kpp_digits}"
        expect = ((str(EntityType.INN), inn_digits), (str(EntityType.KPP), kpp_digits))
        cases.append(MetamorphicCase("альтернативные подписи", "ИНН/КПП слитно", text, expect))
    return cases


def _genitive_word(word: str) -> str | None:
    """Родительный падеж по регулярным окончаниям русских имён/фамилий.

    Не общий морфологический решатель — таблица покрывает только патроним
    (-ович/-евич/-овна/-евна), типовые фамилии на -ов/-ев/-ин/-ая/-а/-я и
    явный список имён из этого корпуса (``_GENITIVE_GIVEN_NAME``). Для всего
    остального возвращает ``None`` — генератор такое слово не склоняет.
    """
    low = word.casefold()
    if low in _GENITIVE_GIVEN_NAME:
        result = _GENITIVE_GIVEN_NAME[low]
    elif low.endswith(("ович", "евич")):
        result = word + "а"
    elif low.endswith(("овна", "евна")):
        result = word[:-1] + "ы"
    elif low.endswith(("ов", "ев", "ин", "ын")):
        result = word + "а"
    elif low.endswith("ая"):
        result = word[:-2] + "ой"
    elif low.endswith("а"):
        result = word[:-1] + "ой"
    elif low.endswith("я"):
        result = word[:-1] + "и"
    else:
        return None
    if word[:1].isupper():
        result = result[:1].upper() + result[1:]
    return result


def _person_cases(value: str) -> list[MetamorphicCase]:
    """Категория 7: формы ФИО и падежи.

    Канонический ключ каждого варианта — ``normalize_value(PERSON, вариант)``
    самого варианта, а не исходного значения: смысл проверки в том, находит
    ли детектор person-сущность именно в этом написании и захватывает ли её
    целиком, а не в том, совпадает ли она с другим написанием того же
    человека (это уже задача связывания профилей, не детекции).
    """
    tokens = value.split()
    full = [t for t in tokens if "." not in t and len(t) > 1]
    initials = [t for t in tokens if "." in t or len(t) == 1]
    cases: list[MetamorphicCase] = []

    def add(variant: str, text: str) -> None:
        key = normalize_value(EntityType.PERSON, text)
        if not key:
            return
        cases.append(
            MetamorphicCase("формы ФИО и падежи", variant, text, ((str(EntityType.PERSON), key),))
        )

    if full and initials:
        letters = [c for token in initials for c in token if c.isalpha()]
        if letters:
            abbrev = ".".join(letters) + "."
            surname = full[0]
            add("инициалы после фамилии", f"{surname} {abbrev}")
            add("инициалы перед фамилией", f"{abbrev} {surname}")
    elif len(full) == 3:
        surname, first, patronymic = full
        abbrev = f"{first[0]}.{patronymic[0]}."
        add("инициалы после фамилии", f"{surname} {abbrev}")
        add("инициалы перед фамилией", f"{abbrev} {surname}")
        add("порядок имя-отчество-фамилия", f"{first} {patronymic} {surname}")
        declined = [_genitive_word(token) for token in full]
        if all(word is not None for word in declined):
            add("родительный падеж", " ".join(word for word in declined if word is not None))

    return cases


def generate_cases() -> list[MetamorphicCase]:
    """Полный метаморфный корпус — детерминированный список случаев.

    Порядок: по типу сущности (значение ``EntityType``), внутри типа — по
    отсортированному каноническому значению, внутри значения — в порядке
    объявления категорий в этом модуле. Никакого ``random``.
    """
    entities = _load_corpus_entities()
    cases: list[MetamorphicCase] = []
    for entity_type in sorted(_DIGIT_TYPES):
        for value in _unique_values(entities, str(entity_type)):
            cases.extend(_digit_cases(entity_type, value))
    cases.extend(_inn_kpp_combined_cases(_inn_kpp_pairs(entities)))
    for value in _unique_values(entities, str(EntityType.PERSON)):
        cases.extend(_person_cases(value))
    return cases


@dataclass(frozen=True, slots=True)
class MetamorphicReport:
    """Итог прогона метаморфного корпуса через ``DetectAgent``."""

    total: int
    hit: int
    by_category: dict[str, tuple[int, int]] = field(default_factory=dict)
    misses: tuple[str, ...] = ()

    @property
    def recall(self) -> float:
        return self.hit / self.total if self.total else 1.0


def _found_canon(entity_type: str, text: str) -> str:
    if entity_type in {str(t) for t in _DIGIT_TYPES}:
        return _digits_only(text)
    if entity_type == str(EntityType.PERSON):
        return normalize_value(EntityType.PERSON, text)
    return text


def evaluate(
    agent: DetectAgent | None = None, cases: list[MetamorphicCase] | None = None
) -> MetamorphicReport:
    """Прогнать метаморфный корпус через слой детекции и посчитать recall.

    По умолчанию — тот же ``DetectAgent`` (правила + Natasha), что и
    основной прогон, без LLM-арбитра: у синтетических сегментов нет
    неоднозначности ролей, которую решает арбитр, а сеть в измерительном
    инструменте по умолчанию не нужна.
    """
    agent = agent or DetectAgent()
    cases = cases if cases is not None else generate_cases()
    hit = 0
    by_category: dict[str, list[int]] = {}
    misses: list[str] = []
    for order, case in enumerate(cases):
        segment = Segment(
            text=case.text,
            anchor=Anchor(fmt="synthetic", locator=("metamorphic", order)),
            order=0,
        )
        document = Document(path="<metamorphic>", fmt="synthetic", segments=[segment])
        result = agent.detect(document)
        found = {
            (entity.type, _found_canon(entity.type, entity.text)) for entity in result.entities
        }
        ok = all(expected in found for expected in case.expected)
        bucket = by_category.setdefault(case.category, [0, 0])
        bucket[1] += 1
        if ok:
            hit += 1
            bucket[0] += 1
        else:
            misses.append(f"{case.category}/{case.variant}: {case.text!r} -> {sorted(found)}")
    return MetamorphicReport(
        total=len(cases),
        hit=hit,
        by_category={name: (values[0], values[1]) for name, values in sorted(by_category.items())},
        misses=tuple(misses),
    )
