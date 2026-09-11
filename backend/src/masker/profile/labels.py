"""Ролевые метки, извлекаемые только из формулировок документа."""

from __future__ import annotations

import functools
import re
import unicodedata
from pathlib import Path

import yaml

PREAMBLE = re.compile(r"именуем\w*\s+в\s+дальнейшем\s+[«\"]([^»\"]+)[»\"]", re.IGNORECASE)
# Захват без ограничения длины (было `[А-ЯЁа-яё\- ]+`) на сегменте-строке не
# успевал добежать дальше конца строки; на сегменте-блоке (план T2.2.1, шаг 8:
# строки внутри блока склеены пробелом, не переносом) регулярка спокойно
# проходит через заголовок раздела и подхватывает соседние слова — реальный
# случай: «5.БАНКОВСКИЕ РЕКВИЗИТЫ И ПОДПИСИ СТОРОН Учреждение Потребитель
# МАОУ гимназия» целиком стало одной «ролью». Роль — максимум два слова
# («Поставщика», «Финансового управляющего»), как и было в каждом реальном
# употреблении REQUISITES до этого дефекта.
# И2-2: тот же заголовок «РЕКВИЗИТЫ И ПОДПИСИ СТОРОН» после укорачивания
# захвата стал ловить союз «И» как начало «роли» («и подписи») — это не
# роль стороны, а мусор из заголовка раздела. Мусорная метка склеивала
# профили заказчика и исполнителя в один: `cluster.py` объединяет блоки с
# одинаковой меткой независимо от того, о какой стороне блок на самом деле
# (contract_pdf_02_school.pdf, где обе стороны идут двумя соседними
# абзацами реквизитов без общего заголовка). Союзы-исключения — не
# хардкод роли, а фильтр служебных слов, которые ролью быть не могут.
REQUISITES = re.compile(
    r"(?:^|\b)реквизиты\s+(?!и\b|или\b)([А-ЯЁ][а-яёА-ЯЁ\-]*(?:\s+[А-ЯЁ][а-яёА-ЯЁ\-]*)?)",
    re.IGNORECASE,
)
SIGNATURE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?([А-ЯЁ][А-ЯЁа-яё\- ]{1,40}):\s*(?=[_—-]{2,}|[А-ЯЁ])"
)
# В PDF шапка подписи часто извлечена не как «Заказчик:», а как «от
# Заказчика:». Это всё та же явная роль стороны, а не должность подписанта.
# 11.09.2026 на `arkhschool-68-183.pdf` без неё блок с должностью министра
# оставался без ролевой метки и не мог получить псевдоним заказчика.
SIGNATORY_SIDE = re.compile(r"\bот\s+([А-ЯЁ][А-ЯЁа-яё\- ]{1,40}):", re.IGNORECASE)
# И2-2: роль из формулировки обязательств. Документы без преамбулы
# «именуемое в дальнейшем» (school-контракт) вообще не называют роль ни
# разу в именительном падеже рядом со стороной — единственная связка роли
# с конкретным лицом идёт через оборот «Уполномоченным представителем
# <РОЛЬ> ... является <ФИО>». Роль после «представител…» всегда стоит в
# родительном падеже — приводится к именительному через `_to_nominative`,
# иначе она разъезжается по форме с той же ролью, найденной SIGNATURE/
# PREAMBLE в именительном, и `blocks.py::_known_label` их не склеит.
REPRESENTATIVE = re.compile(
    r"представител[а-яёА-ЯЁ]*\s+([А-ЯЁа-яё]+)[^.]{0,250}?явля(?:ется|ются)\b",
    re.IGNORECASE,
)
# И2-2: роль из шапки подписей «Заказчик Исполнитель». В школьном договоре
# (contract_pdf_02_school.pdf) двухколоночная подпись на каждой странице
# расплющивается PDF-экстракцией в одну строку «Заказчик Исполнитель
# Директор МАОУ гимназии № 144» — рядом с этой же строкой (или сразу
# следом) идёт наименование первой стороны, а второй — в следующем
# сегменте. Формулировка «Х обязуется... по заданию Y», которую называет
# план, в этом документе выглядит как эта голая пара ролей: два известных
# слова-роли подряд без знаков препинания между ними, порядок слов и есть
# порядок появления сторон. Список ролей — тот же `party_roles.yaml`, что и
# у `SIGNATURE`, а не хардкод: пара валидна только если ОБА слова в ней —
# известные роли стороны, и это разные роли (не повтор одного слова).
ROLE_PAIR = re.compile(r"\b([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+)\b")


@functools.lru_cache(maxsize=1)
def _party_role_stems() -> tuple[str, ...]:
    """Прочитать список ролей сторон из данных (не из кода) один раз за процесс."""
    path = Path(__file__).with_name("data") / "party_roles.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(raw["role_stems"])


def _is_known_party_role(label: str) -> bool:
    """Проверить метку по списку ролей-сторон (данные `data/party_roles.yaml`).

    Матч по усечённой основе, а не по точному слову: `SIGNATURE` обычно
    захватывает именительный падеж («Поставщик:»), но основа не ломается на
    случайной словоформе. Короткая метка не может «начинаться» с более
    длинной основы — `str.startswith` на строке короче образца сам по себе
    вернёт `False`, отдельная проверка длины не нужна.
    """
    return any(label.startswith(stem) for stem in _party_role_stems())


@functools.lru_cache(maxsize=1)
def _morph_vocab():  # type: ignore[no-untyped-def]
    """Собрать `natasha.MorphVocab` один раз за процесс (лениво, как в `detect/morph.py`)."""
    from natasha import MorphVocab

    return MorphVocab()


def _to_nominative(label: str) -> str:
    """Привести словоформу роли к именительному падежу по словарю OpenCorpora.

    Нужно только для `REPRESENTATIVE`: захваченное слово («заказчика») стоит
    в родительном падеже по самой грамматике оборота «представителем X», а
    роль должна выглядеть и сравниваться так же, как та же роль, введённая
    `PREAMBLE`/`SIGNATURE` в именительном («заказчик»). Без явного разбора
    существительного эвристика может по ошибке привести к нормальной форме
    вообще другую часть речи — фильтр `pos == "NOUN"` обязателен.
    """
    for parse in _morph_vocab().parse(label):
        if parse.pos == "NOUN":
            return str(parse.normal)
    return label


def _is_nominative_role(label: str) -> bool:
    """Проверить, что слово — существительное в именительном падеже.

    Нужно для `ROLE_PAIR`: голая пара слов-ролей рядом («Заказчик
    Исполнитель») — это шапка подписи, где обе роли названы именем стороны
    (именительный). Та же пара слов в обычном предложении («уведомления
    Заказчиком Исполнителя об отказе») называет не шапку, а падежные formы
    существительных внутри фразы — это НЕ шапка с ролями сторон, а просто
    два слова-роли, упомянутые по ходу текста; без проверки падежа
    `_known_label` в `blocks.py` склеивала бы «заказчиком» с «заказчик» по
    первым буквам основы и портила уже верно найденную метку.
    """
    return any(
        parse.pos == "NOUN" and parse.tag.case == "nomn" and parse.tag.number == "sing"
        for parse in _morph_vocab().parse(label)
    )


def normalize_label(label: str) -> str:
    """Свести написание роли к стабильной форме без закрытого словаря ролей."""
    return " ".join(label.strip(' \t.,;:«»"').casefold().split())


_COLLECTIVE_STEM = "сторон"


def _is_collective(label: str) -> bool:
    """Проверить, что метка — это «Стороны» (в любом падеже), а не роль одной стороны.

    Это не словарь допустимых ролей: роли вроде «поставщик»/«покупатель» по-прежнему
    берутся только из формулировок документа, без хардкода. Единственное исключение —
    собирательное слово «Стороны», которое называет сразу обе стороны договора и
    поэтому не может быть меткой одной конкретной стороны.
    """
    first_word = label.split(" ", 1)[0]
    return first_word[: len(_COLLECTIVE_STEM)] == _COLLECTIVE_STEM


def find_labels(text: str) -> list[tuple[int, str]]:
    """Найти ролевые метки только в контекстах, явно задающих роль.

    `PREAMBLE` и `REQUISITES` по построению обрамляют роль стороны словами
    самой формулировки («именуемое в дальнейшем», «реквизиты …») — их
    результат не проверяется дополнительно. `SIGNATURE` — это голая
    регулярка «Слово:» в начале строки, ей ничего не мешает поймать
    должность подписанта («Директор:») или текст ячейки таблицы
    («Объединённая ячейка: ИНН …»), поэтому её находки допускаются только
    если метка либо входит в список ролей-сторон, либо уже введена этим же
    текстом через `PREAMBLE` (план И2-1, `docs/plans/tasks-krmi-2026-09-09.md`).
    `REPRESENTATIVE` (план И2-2) — та же голая регулярка «представителем X …
    является Y», её находки проверяются точно так же.
    """
    found: list[tuple[int, str]] = []
    preamble_labels: set[str] = set()
    for match in PREAMBLE.finditer(text):
        label = normalize_label(match.group(1))
        if label and not _is_collective(label):
            preamble_labels.add(label)
            found.append((match.start(1), label))
    for match in REQUISITES.finditer(text):
        label = normalize_label(match.group(1))
        if label and not _is_collective(label):
            found.append((match.start(1), label))
    for match in SIGNATURE.finditer(text):
        label = normalize_label(match.group(1))
        if not label or _is_collective(label):
            continue
        if label in preamble_labels or _is_known_party_role(label):
            found.append((match.start(1), label))
    for match in SIGNATORY_SIDE.finditer(text):
        # «От Заказчика» требует родительного падежа, но метка профиля
        # должна совпадать с «Заказчик» из преамбулы/реквизитов. 11.09.2026
        # на `arkhschool-68-183.pdf` иначе получались два разных профиля
        # одной стороны: «заказчик» и «заказчика».
        label = _to_nominative(normalize_label(match.group(1)))
        # 12.09.2026: PDF-экстракция иногда приклеивает подпись «от
        # Заказчика» в конец длинного блока реквизитов исполнителя. Такая
        # метка относится только к хвосту блока и не должна переименовывать
        # все предшествующие БИК/ОГРН/банк в заказчика.
        if match.start() > 80:
            continue
        if (
            label
            and not _is_collective(label)
            and (label in preamble_labels or _is_known_party_role(label))
        ):
            found.append((match.start(1), label))
    for match in REPRESENTATIVE.finditer(text):
        label = normalize_label(match.group(1))
        if not label or _is_collective(label):
            continue
        if label in preamble_labels:
            found.append((match.start(1), label))
        elif _is_known_party_role(label):
            found.append((match.start(1), _to_nominative(label)))
    for match in ROLE_PAIR.finditer(text):
        first = normalize_label(match.group(1))
        second = normalize_label(match.group(2))
        if (
            first
            and second
            and first != second
            and not _is_collective(first)
            and not _is_collective(second)
            and _is_known_party_role(first)
            and _is_known_party_role(second)
            and _is_nominative_role(match.group(1))
            and _is_nominative_role(match.group(2))
        ):
            found.append((match.start(1), first))
            found.append((match.start(2), second))
    return sorted(set(found), key=lambda item: item[0])


def slugify(label: str) -> str:
    """Сделать стабильный ASCII slug открытой роли."""
    transliteration = str.maketrans(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        "abvgdeejzijklmnoprstufhzcss_y_eua",
    )
    value = unicodedata.normalize("NFKD", normalize_label(label)).translate(transliteration)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "side"


def role_title(label: str) -> str:
    """Отобразить роль так, как она названа в документе."""
    return normalize_label(label).capitalize()


def marker_label(label: str) -> str:
    """Сделать читаемую часть будущего маркера."""
    return role_title(label).upper().replace(" ", "-")
