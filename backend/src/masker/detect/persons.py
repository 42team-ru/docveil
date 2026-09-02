"""Границы PERSON: фамилия слева, должность прочь (план T2.2.1, шаг 6, Д4).

Два независимых дефекта под одним симптомом «ФИО обрезано»:

- фамилия в родительном падеже в начале строки/после запятой теряется
  (`Мокиной Светланы Владимировны` → модель отдаёт только
  `Светланы Владимировны`) — чинится расширением влево на один токен;
- должность оказывается внутри спана (`Директора Зубрицкой`) — чинится
  отсечением ведущих ролевых токенов, а не спана целиком, как раньше
  делал ``is_role_stopword``.

Оба правила текстовые (по соседним токенам), а не по NER-меткам: должность
и фамилия для Natasha — один и тот же спан ``PER``, разбирать его нужно по
границам слов, а не по повторному вызову модели.
"""

from __future__ import annotations

import re

from masker.detect.address import address_markers
from masker.detect.normalize import normalize_value
from masker.detect.orgforms import TRIM_CHARS, is_role_token, org_forms
from masker.model import EntityType

#: Уличные маркеры (``ул.``, ``пр-т``, ``наб.`` и т.д.) — тот же словарь,
#: что и у ``AddressDetector``: «Банникова» после «ул.» — не фамилия.
_STREET_MARKERS = frozenset(marker.casefold() for marker in address_markers().street)

#: Слова, дающие однотокенному PER право на существование без совпадения
#: с уже подтверждённым ФИО в документе (план T2.2.1, шаг 7).
_PERSON_TRIGGERS = ("в лице", "директор", "г-н", "г-жа", "подпись")
#: Ширина окна слева для поиска триггера — подобрана как у
#: ``_has_passport_context`` (``detect/rules.py``): достаточно, чтобы
#: захватить «в лице» перед фамилией через слово-два, не более того.
_TRIGGER_WINDOW = 40

_TOKEN_RE = re.compile(r"\S+")


def drop_role_prefix(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Срезать ведущие ролевые/должностные токены спана.

    ``Директора Зубрицкой`` → ``Зубрицкой``. Если после среза не осталось
    ничего (спан целиком состоял из ролевых слов) — сущности нет, ``None``.
    """
    cursor = start
    while cursor < end:
        match = _TOKEN_RE.match(text, cursor, end)
        if match is None:
            break
        token = match.group().strip(TRIM_CHARS)
        if not token or not is_role_token(token):
            break
        cursor = match.end()
        while cursor < end and text[cursor] == " ":
            cursor += 1
    if cursor >= end:
        return None
    return cursor, end


def _left_neighbor_token(text: str, start: int) -> tuple[int, int] | None:
    """Границы одного соседнего слева токена, отделённого ровно одним пробелом.

    Ровно одним — не пунктуацией и не несколькими пробелами: иначе граница
    ФИО пересекала бы знак препинания (``test_person_span_does_not_cross_punctuation``).
    """
    if start < 2 or text[start - 1] != " " or text[start - 2] == " ":
        return None
    token_end = start - 1
    token_start = token_end
    while token_start > 0 and text[token_start - 1] not in " \t ":
        token_start -= 1
    if token_start == token_end:
        return None
    return token_start, token_end


def expand_person_left(text: str, start: int, end: int) -> tuple[int, int]:
    """Расширить ФИО влево не более чем на один токен.

    Кандидат принимается, только если начинается с заглавной кириллической
    буквы, не является ролевым словом/должностью, оргформой или уличным
    маркером и отделён от спана ровно пробелом (план T2.2.1, шаг 6).
    """
    bounds = _left_neighbor_token(text, start)
    if bounds is None:
        return start, end
    token_start, token_end = bounds
    raw_token = text[token_start:token_end]
    core = raw_token.strip(TRIM_CHARS)
    # Токен с приклеенной пунктуацией («Романов,») — это конец предыдущего
    # предложения/перечисления, а не сосед через пробел: граница пунктуации
    # не пересекается (test_person_span_does_not_cross_punctuation).
    if core != raw_token or not core or not re.match(r"[А-ЯЁ]", core[0]):
        return start, end
    folded = core.casefold().rstrip(".")
    if (
        is_role_token(core)
        or folded in _STREET_MARKERS
        or any(folded == form.casefold() for form in org_forms().forms)
    ):
        return start, end
    return token_start, end


def preceded_by_address_marker(text: str, start: int) -> bool:
    """Спан стоит сразу за адресным маркером («ул. Банникова» — «Банникова»
    улица, не фамилия; план T2.2.1, шаг 7). Тот же поиск соседа, что и в
    ``expand_person_left``, но здесь маркер — повод отбросить сущность
    целиком, а не просто не расширяться на него."""
    bounds = _left_neighbor_token(text, start)
    if bounds is None:
        return False
    token = text[bounds[0] : bounds[1]].strip(TRIM_CHARS)
    return token.casefold().rstrip(".") in _STREET_MARKERS


def has_person_trigger(text: str, start: int) -> bool:
    """Слева от спана — слово, дающее одиночному PER право на существование
    без независимого подтверждения («директор Иванов», «в лице Петров»,
    план T2.2.1, шаг 7)."""
    context = text[max(0, start - _TRIGGER_WINDOW) : start].casefold()
    return any(trigger in context for trigger in _PERSON_TRIGGERS)


def person_stem(value: str) -> str:
    """Нормализованная фамилия/токен для сверки одиночного PER с уже
    подтверждённым в документе ФИО — обёртка над ``normalize_value``,
    чтобы ``ner.py`` не тянул ``EntityType.PERSON`` ради одного вызова."""
    return normalize_value(EntityType.PERSON, value)


def single_token_person_is_confirmed(
    value: str,
    text: str,
    start: int,
    confirmed_stems: frozenset[str],
) -> bool:
    """Однотокенный PER выпускается только с независимым подтверждением.

    Подтверждение — та же фамилия уже встречается с инициалами или с
    именем где-то в документе (``confirmed_stems``, собранные из
    многотокенных PERSON), либо рядом стоит триггер (план T2.2.1, шаг 7).
    Многотокенные спаны это правило не проверяет — им всегда возвращает
    ``True``, чтобы вызывающему не пришлось дублировать подсчёт токенов.
    """
    if len(value.split()) != 1:
        return True
    stem = person_stem(value)
    if stem and stem in confirmed_stems:
        return True
    return has_person_trigger(text, start)
