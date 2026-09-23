"""Морфологический детектор ФИО по словарю OpenCorpora (Р4).

Замер `spikes/detect_soft_pii_spike.py` нашёл пропуск, который
`NatashaDetector` (статистическая NER-модель) в принципе не может закрыть:
одиночное имя без окружающего контекста молчаливо теряется —
`_require_person_evidence` (``ner.py``) сознательно требует независимого
подтверждения для однотокенного `PER`, и «Оксана» без второго упоминания и
без триггера рядом («директор», «в лице», …) под это подтверждение не
попадает. Другой класс той же группы дефектов — «Мамедов Э.Г.о.» (хвост
«оглы» вне модельного спана) и «Пилипенко С.А.» (обрезанная точка
последнего инициала) — устранены не здесь, а в `orgforms.py`
(`fix_person_initials`/`shrink_span`): NatashaDetector там уже отдаёт
подрезанный спан, и подрезка — дефект в его собственной пост-обработке
span'а, а не в отсутствии независимого источника (см. докстринги функций).
Заводить для них ещё один конкурирующий детектор бессмысленно и опасно: PII
уже опознан этим же спаном, конкурент с бóльшим/меньшим спаном на том же
месте régулярно раскалывает уже верную многословную персону через
`DetectAgent._carve` (обнаружено на «Ю. В. Козлова» при разработке — carve
режет уже принятую полную сущность на «Ю. В.» + «Козлова», как только
здесь появляется самостоятельный кандидат «Козлова», перекрывающий её).

``source=Source.NER``: тот же класс задачи, что решает `NatashaDetector`, —
статистическая/словарная классификация словоформ языка (не точная
регулярка с контрольной суммой), которой закономерно требуется управление
уверенностью, а не бинарный вердикт.

Правило (план Р4): подряд идущие токены с граммемами OpenCorpora
``Surn``/``Name``/``Patr`` (в любом порядке, через ровно один пробел)
образуют один спан ФИО. 2 и более таких токенов подряд — высокая
уверенность (``0.92``, «почти наверняка ФИО», даже если `NatashaDetector`
на этой же строке смолчал). Ровно один такой токен без соседей — тоже
`PERSON`, но пониженной уверенности (``0.55`` — «похоже на имя», порог
использует другая задача, Р8).

Приоритет (``45``) ниже `NatashaDetector` (``50``): это НЕ попытка
«поправить» уже найденный NER-спан расширением вправо/влево (для этого
нужен root-cause фикс в `orgforms.py`, см. выше), а страховка на тех
местах, где `NatashaDetector` не дал НИЧЕГО. Если Natasha уже нашла на этом
месте сущность — независимо от того, шире она нашего кандидата или уже, —
`DetectAgent._resolve_overlaps` обработает Natasha первой (выше приоритет)
и примет её; наш кандидат обработается позже, целиком попадёт в уже
принятый диапазон и по правилам `_carve` (пустой остаток вне пересечения)
молча исчезнет — устраивает нас в обоих направлениях: и когда наш спан
короче найденного Natasha (не плодим дублей), и когда он ей в точности
совпадает (то же самое).
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

from masker.detect.normalize import normalize_value
from masker.detect.orgforms import is_role_token, org_forms
from masker.detect.person_values import is_single_token_uppercase_abbreviation
from masker.model import Document, Entity, EntityType, Segment, Source

#: Граммемы OpenCorpora, которыми MorphVocab помечает имя собственное
#: персоны (докстринг задачи Р4: Оксана → Name, Пилипенко → Surn,
#: Ильдарович → Patr). Порядок не важен — используется только membership.
_NAME_TAGS: tuple[str, ...] = ("Surn", "Name", "Patr")

#: Символы, которые не несут значения на краях «сырого» токена при разборе
#: на слова (аналог `orgforms.TRIM_CHARS`, но без внутренних точек —
#: разбор токена на «ядро» не должен есть точки инициалов).
_TRAILING_JUNK = " \t ,;:()[]{}«»\"'“”„…\n"

_HIGH_CONFIDENCE = 0.92
_LOW_CONFIDENCE = 0.55

_TOKEN_RE = re.compile(r"\S+")


@functools.lru_cache(maxsize=1)
def _morph_vocab():  # type: ignore[no-untyped-def]
    """Собрать `natasha.MorphVocab` один раз за процесс (не на документ),
    так же как `ner.py` мемоизирует `NewsNERTagger`."""
    from natasha import MorphVocab

    return MorphVocab()


@functools.lru_cache(maxsize=4096)
def has_name_grammeme(word: str) -> bool:
    """Есть ли у слова ХОТЯ БЫ ОДИН морфоразбор OpenCorpora с граммемой
    ``Surn``/``Name``/``Patr`` (план Р9-1).

    В отличие от `_classify_word` (тот смотрит только на ПЕРВЫЙ, самый
    вероятный разбор — так и нужно детектору, который сам решает,
    маскировать ли найденное) здесь решение другое: расширять ли уже
    найденный Natasha спан ФИО влево на соседний токен. Первый разбор
    здесь непригоден — «Мокиной» и «Зубрицкая» первым разбором получают не
    `Surn` (омонимы с нарицательным/нестандартным окончанием), и расширение
    сломалось бы ровно на тех случаях, ради которых оно и придумано (см.
    `expand_person_left`). Нужен любой разбор — тот же приём, что уже
    применяет `verifier._any_name_grammeme` для отбора спорных мест."""
    if not word or not (word[0].isalpha() and word[0].isupper()):
        return False
    if word.casefold() in org_forms().requisite_labels:
        return False
    for form in _morph_vocab()(word):
        tag = str(getattr(form, "tag", ""))
        if any(name_tag in tag for name_tag in _NAME_TAGS):
            return True
    return False


@functools.lru_cache(maxsize=4096)
def is_unambiguous_geo_word(word: str) -> bool:
    """Слово — топоним (граммема OpenCorpora ``Geox``) и не омоним ФИО.

    Нашёлся 23.09.2026 на реальном контракте: `find_requisite_block_candidates`
    (``requisite_blocks.py``) в блоке банковских реквизитов подхватывал
    «Республике Саха» как ФИО — заглавная пара слов вне признанных сущностей,
    ничем не отличимая от подписи по одной этой эвристике. «Саха» и
    «Якутия» у OpenCorpora размечены только ``Geox``, без единого разбора
    ``Surn``/``Name``/``Patr`` — надёжный сигнал «это топоним, не фамилия».

    Условие строго «есть Geox И нет граммемы имени», а не просто «есть
    Geox»: у части фамилий-омонимов топонимов (например, «Александрова» —
    и фамилия, и форма города) тоже есть разбор с ``Geox``, и такое слово
    здесь не должно гасить кандидата — иначе поймали бы противоположный
    дефект, пропуск настоящей фамилии.
    """
    if not word or not (word[0].isalpha() and word[0].isupper()):
        return False
    parses = list(_morph_vocab()(word))
    tags = [str(getattr(form, "tag", "")) for form in parses]
    has_geo = any("Geox" in tag for tag in tags)
    has_name = any(name_tag in tag for tag in tags for name_tag in _NAME_TAGS)
    return has_geo and not has_name


@functools.lru_cache(maxsize=4096)
def _classify_word(word: str) -> str | None:
    """Вернуть граммему `Surn`/`Name`/`Patr` первого (наиболее вероятного)
    морфологического разбора слова, иначе `None`.

    Проверка по ПЕРВОМУ разбору — не по любому из них — принципиальна:
    омонимы вроде «Вера»/«Слава»/«Надежда» имеют разбор с `Name` в словаре,
    но он не первый (первый — нарицательное существительное), поэтому эти
    слова корректно не классифицируются как имя (замер задачи это
    подтвердил построчно). Кэш по значению слова — тексты договоров
    многократно повторяют одни и те же токены («Договор», «Стороны», роли).
    """
    if not word or not (word[0].isalpha() and word[0].isupper()):
        return None
    # «ИНН» — реальный омограф родительного падежа множественного числа
    # имени «Инна» в словаре OpenCorpora (тег `Name`), из-за чего каждое
    # упоминание реквизита ИНН иначе ловилось бы как персона (обнаружено
    # на всём размеченном корпусе — 10 из 18 новых ложных срабатываний).
    # Реквизитные метки в принципе не могут быть личными именами.
    if word.casefold() in org_forms().requisite_labels:
        return None
    forms = _morph_vocab()(word)
    if not forms:
        return None
    tag = str(getattr(forms[0], "tag", ""))
    for name_tag in _NAME_TAGS:
        if name_tag in tag:
            return name_tag
    return None


@dataclass(frozen=True, slots=True)
class _Token:
    """Слово сегмента с границами «ядра» — без обрамляющей пунктуации."""

    start: int  # начало ядра (после ведущей пунктуации)
    end: int  # конец ядра (до хвостовой пунктуации)
    core: str  # text[start:end]


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    for match in _TOKEN_RE.finditer(text):
        raw_start, raw_end = match.start(), match.end()
        start, end = raw_start, raw_end
        while start < end and text[start] in _TRAILING_JUNK:
            start += 1
        while start < end and text[end - 1] in _TRAILING_JUNK:
            end -= 1
        if start >= end:
            continue
        tokens.append(_Token(start=start, end=end, core=text[start:end]))
    return tokens


class MorphPersonDetector:
    """ФИО по морфологическому словарю OpenCorpora (см. докстринг модуля).

    Ловит только то, что `NatashaDetector` не нашёл вообще: одиночное имя
    без контекста и подряд идущие граммемы Surn/Name/Patr. Границы уже
    найденных Natasha спанов (обрезанная точка, хвост «оглы») чинятся в
    `orgforms.py`, не здесь — см. докстринг модуля.
    """

    name = "morph_person"
    source = Source.NER
    priority = 45
    types: frozenset[str] = frozenset({EntityType.PERSON})

    def detect(self, document: Document) -> list[Entity]:
        found: list[Entity] = []
        for segment in document.segments:
            found.extend(self._detect_segment(segment))
        return self._drop_partial_duplicates(found)

    @staticmethod
    def _drop_partial_duplicates(found: list[Entity]) -> list[Entity]:
        """Не выпускать обрывок уже найденного здесь же полного ФИО.

        Реальный дефект на PDF-корпусе (`contract_pdf_02_school.pdf`):
        двойной пробел внутри одного упоминания («Мокиной Светланы
        Владимировны») рвёт цепочку на «Мокиной» + «Светланы
        Владимировны», а другое упоминание ТОГО ЖЕ человека в другом
        падеже/регистре («Светлана Владимировна» на строке подписи)
        своим отдельным прогоном ловится целиком — в сумме получаем
        полное имя ПЛЮС его обрывок как самостоятельную персону. Сравнение
        по нормализованному ключу (``normalize_value`` уже снимает падеж)
        — обрывок должен быть СТРОГИМ подмножеством токенов более
        длинного упоминания где-либо в документе, тот же приём, что
        `NatashaDetector._require_person_evidence` уже применяет к своим
        собственным спанам (``_is_partial_person``, ``ner.py``)."""
        token_sets = [frozenset(entity.normalized.split()) for entity in found]
        keep: list[Entity] = []
        for index, entity in enumerate(found):
            tokens = token_sets[index]
            is_partial = any(
                tokens < other and tokens
                for other_index, other in enumerate(token_sets)
                if other_index != index
            )
            if not is_partial:
                keep.append(entity)
        return keep

    @staticmethod
    def _detect_segment(segment: Segment) -> list[Entity]:
        text = segment.text
        tokens = _tokenize(text)
        result: list[Entity] = []
        index = 0
        total = len(tokens)
        while index < total:
            if _classify_word(tokens[index].core) is None:
                index += 1
                continue
            run_end = index
            core_count = 1
            cursor = index + 1
            while cursor < total and text[tokens[cursor - 1].end : tokens[cursor].start] == " ":
                if _classify_word(tokens[cursor].core) is None:
                    break
                run_end = cursor
                core_count += 1
                cursor += 1
            start = tokens[index].start
            end = tokens[run_end].end
            # В сертификатах ЭП фамилия часто набрана ВЕРХНИМ РЕГИСТРОМ.
            # Первый разбор MorphVocab тогда не относит её к Surn, хотя
            # соседние имя+отчество уже образуют надёжное ФИО. Берём ровно
            # один предшествующий токен только при name-граммеме; это
            # повторяет безопасную часть expand_person_left(), но не создаёт
            # циклический импорт persons.py -> morph.py.
            if (
                core_count >= 2
                and index > 0
                and text[tokens[index - 1].end : tokens[index].start] == " "
                and not is_role_token(tokens[index - 1].core)
                and has_name_grammeme(tokens[index - 1].core)
            ):
                start = tokens[index - 1].start
            value = text[start:end]
            if is_single_token_uppercase_abbreviation(value):
                index = run_end + 1
                continue
            confidence = _HIGH_CONFIDENCE if core_count >= 2 else _LOW_CONFIDENCE
            result.append(
                Entity(
                    type=EntityType.PERSON,
                    text=value,
                    segment_order=segment.order,
                    start=start,
                    end=end,
                    source=Source.NER,
                    confidence=confidence,
                    normalized=normalize_value(EntityType.PERSON, value),
                )
            )
            index = run_end + 1
        return result
