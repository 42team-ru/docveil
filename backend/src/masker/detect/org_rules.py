"""Словарный детектор организаций по оргформе (Д11, план T2.2.2, шаг 6).

Natasha на реальных строках договора систематически не отдаёт спана на
оргформу без кавычек: `МАОУ` (?), «Муниципальное автономное
общеобразовательное учреждение гимназия № 144» находится по словарю
(`has_organization_evidence(...) == True`), но модель на этой строке не
возвращает ни одного ORG-спана вовсе — расширять моделью нечего, нужен
отдельный детектор, а не правка `expand_org_span` (та лечит уже найденный
Natasha спан, а не его отсутствие; см. диагностику плана T2.2.2, раздел
«Д11»).

``OrgFormDetector`` ищет в тексте сегмента вхождение формы из словаря
``org_forms.yaml`` на границе слова и с заглавной буквы, и расширяет его
вправо в название организации:

- если сразу после формы (через пробел) стоит открывающая кавычка —
  управление отдаётся ``_expand_right_into_quoted_name`` (та же логика, что
  уже чинит ``expand_org_span`` для спанов Natasha, — не дублируется);
- иначе название набирается словами до первого стоп-условия: пунктуация
  (запятая, `;`, скобка, кавычка, перевод строки), стоп-слово (`в`, `лице`,
  `далее`, `именуем*`, `действующ*`, «с одной», «с другой») или ролевой
  токен (``is_role_token``); группа «№ <цифры>» считается одним словом —
  номер не должен обрезаться посередине; не больше 6 слов.

Многословная форма ищется с ``\\s+`` между своими словами, а не литеральным
пробелом: реальный документ содержит «Общество с  Ограниченной
Ответственностью» (двойной пробел между «с» и «Ограниченной», артефакт
вёрстки PDF) — с литеральным пробелом форма «Общество с ограниченной
ответственностью» не нашлась бы на этой строке вовсе, и остался бы только
двухсловный `Ограниченной Ответственностью`, потеряв «Общество с».

Приоритет 60 — ниже `RuleDetector` (100) и `AddressDetector` (90, чтобы
`ул. Банникова` осталась адресом), выше `NatashaDetector` (50): обрывочный
ORG-спан модели на этой же строке вырезается существующим
`DetectAgent._carve`, а не спорит с этим детектором за перекрытие.

`shrink_span` к результату этого детектора не применяется: он срезает
`№ 144` как «похожий на реквизит» хвост (план T2.2.1), а здесь номер —
часть названия, а не захваченная подпись.

`ИП`/`Индивидуальный предприниматель` из триггеров этого детектора
исключены (`_PERSON_IDENTIFIED_FORMS`): у индивидуального предпринимателя
нет отдельного «названия организации» — сразу за формой идёт ФИО
владельца, и общий алгоритм («слова до стоп-условия») жадно захватывал его
как org_name (`'Индивидуальный предприниматель Кузнецов Пётр Алексеевич'`,
`'ИП Сидоров С.С. направил документы'` — оба найдены на DOCX-корпусе, где
разметка верно относит имя к `person`, не к `org_name`).
"""

from __future__ import annotations

import re

from masker.detect.normalize import normalize_value
from masker.detect.orgforms import (
    _expand_right_into_quoted_name,
    has_organization_evidence,
    is_organization_form_only,
    is_public_body,
    is_role_token,
    org_forms,
)
from masker.model import Document, Entity, EntityType, Source

#: Стоп-пунктуация, останавливающая набор названия вправо (план, шаг 6, п. 2).
_STOP_PUNCT = frozenset(",;()[]{}\n")
#: Стоп-стеммы (по началу слова, регистронезависимо).
_STOP_STEMS = ("именуем", "действующ")
#: Одиночные стоп-слова (регистронезависимо).
_STOP_WORDS = frozenset({"в", "лице", "далее"})
#: Двусловная стоп-фраза «с одной»/«с другой» — сторона договора.
_STOP_PAIR_FIRST = "с"
_STOP_PAIR_SECOND = frozenset({"одной", "другой"})
#: Не более 6 слов в названии, набранном без кавычек.
_MAX_WORDS = 6
#: Формы, за которыми в тексте следует ФИО владельца, а не название
#: организации, — см. докстринг модуля.
_PERSON_IDENTIFIED_FORMS = frozenset({"ип", "индивидуальный предприниматель"})


def _quote_chars() -> frozenset[str]:
    return frozenset(char for pair in org_forms().quote_pairs for char in pair)


def _form_pattern() -> re.Pattern[str]:
    """Альтернация форм словаря; пробел внутри многословной формы — `\\s+`.

    Литеральный пробел не годится: реальный документ ставит двойной пробел
    внутри многословной формы (артефакт вёрстки PDF) — см. докстринг модуля.
    """
    alternatives = "|".join(re.escape(form).replace(r"\ ", r"\s+") for form in org_forms().forms)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def _expand_right_past_quote(text: str, quote_start: int) -> int:
    """Найти конец парной закрывающей кавычки, начиная строго с открывающей.

    Фолбэк для случая, где `_expand_right_into_quoted_name` отказался
    расширять спан из-за лишнего пробела внутри самой формы (см. вызывающий
    код) — форма уже подтверждена словарным поиском, повторная сверка не
    нужна, нужен только поиск парной закрывающей кавычки.
    """
    opening = text[quote_start]
    for candidate_open, candidate_close in org_forms().quote_pairs:
        if candidate_open != opening:
            continue
        closing_pos = text.find(candidate_close, quote_start + 1)
        if closing_pos != -1:
            return closing_pos + 1
    return quote_start


def _expand_right_plain(text: str, end: int) -> int:
    """Набрать название вправо словами до стоп-условия (план, шаг 6, п. 2)."""
    stop_chars = _STOP_PUNCT | _quote_chars()
    boundary = len(text)
    for index in range(end, len(text)):
        if text[index] in stop_chars:
            boundary = index
            break
    tokens = list(re.finditer(r"\S+", text[end:boundary]))
    result_end = end
    index = 0
    word_count = 0
    while index < len(tokens) and word_count < _MAX_WORDS:
        word = tokens[index].group()
        folded = word.casefold()
        if (
            word == _STOP_PAIR_FIRST
            and index + 1 < len(tokens)
            and tokens[index + 1].group().casefold() in _STOP_PAIR_SECOND
        ):
            break
        if folded in _STOP_WORDS:
            break
        if any(folded.startswith(stem) for stem in _STOP_STEMS):
            break
        if is_role_token(word):
            break
        local_end = tokens[index].end()
        next_index = index + 1
        is_number_group = False
        # Группа «№ <цифры>» — одно слово, не обрезаем номер посередине.
        if word == "№" and next_index < len(tokens) and tokens[next_index].group().isdigit():
            local_end = tokens[next_index].end()
            next_index += 1
            is_number_group = True
        elif word.startswith("№") and word[1:].isdigit():
            is_number_group = True
        result_end = end + local_end
        word_count += 1
        index = next_index
        if is_number_group:
            # Номер — естественный конец идентифицирующего названия: дальше
            # в прозе идёт продолжение предложения, а не имя («…гимназия
            # №144 силами своих работников» — «силами…» не часть названия).
            break
    return result_end


class OrgFormDetector:
    """Находит организацию по словарю оргформ там, где Natasha не отдаёт спана."""

    name = "org_form"
    source = Source.RULE
    priority = 60
    types: frozenset[str] = frozenset({EntityType.ORG_NAME})

    def detect(self, document: Document) -> list[Entity]:
        pattern = _form_pattern()
        found: list[Entity] = []
        for segment in document.segments:
            text = segment.text
            for match in pattern.finditer(text):
                if not text[match.start()].isupper():
                    continue
                if " ".join(match.group().casefold().split()) in _PERSON_IDENTIFIED_FORMS:
                    continue
                start, end = match.start(), match.end()
                cursor = end
                while cursor < len(text) and text[cursor] in " \t ":
                    cursor += 1
                if cursor < len(text) and text[cursor] in _quote_chars():
                    new_end = _expand_right_into_quoted_name(text, start, end)
                    if new_end == end:
                        # `_expand_right_into_quoted_name` сверяет конец
                        # спана с формой литеральным `endswith` и молча не
                        # расширяет, если внутри формы затесался лишний
                        # пробел (двойной пробел между СВОИМИ словами формы
                        # — артефакт выключки PDF: «Ограниченной
                        # Ответственностью» на реальной строке документа).
                        # Форма уже найдена по словарю через `\s+`-паттерн
                        # (см. `_form_pattern`), поэтому кавычку можно
                        # раскрыть напрямую, не сверяя форму повторно.
                        new_end = _expand_right_past_quote(text, cursor)
                else:
                    new_end = _expand_right_plain(text, end)
                value = text[start:new_end]
                if is_organization_form_only(value):
                    continue
                # Детектор сам предоставляет org_evidence (нашёл оргформу) — фильтровать
                # только те значения, где в тексте нет явного признака организации помимо
                # найденной формы; иначе «УЧРЕЖДЕНИЕ» в полном названии МАОУ ошибочно
                # срабатывает на стем public_bodies и отфильтровывает легитимный орг-спан.
                if is_public_body(value) and not has_organization_evidence(value):
                    continue
                found.append(
                    Entity(
                        type=EntityType.ORG_NAME,
                        text=value,
                        segment_order=segment.order,
                        start=start,
                        end=new_end,
                        source=Source.RULE,
                        confidence=0.95,
                        normalized=normalize_value(EntityType.ORG_NAME, value),
                    )
                )
        return found
