"""LLM-верификатор на recall (Р7, TASKS.md): что пропустили правила и NER.

Имена и названия — открытый класс: конечное множество регулярок никогда не
даст recall 1.0 по построению. Этот модуль — последний слой, который ищет
пропуски правил/NER/блоков реквизитов (Р4–Р6) там, где для этого есть хоть
слабый структурный сигнал, и просит модель (`LLMProvider`, requirement
заказчика №6) подтвердить конкретную подстроку.

Документ в модель НЕ грузим целиком (замер `spikes/verifier_payload_spike.py`
на `contract_pdf_02_school.pdf`: весь документ — ~59 000 токенов, окна вокруг
кандидатов после дедупа — ~1 560, разница в 38 раз, и это не только вопрос
цены: поиск иголки в 59 000 токенов даёт модели куда худший recall, чем
короткое окно). В модель уходят только окна вокруг мест, где слабый сигнал
есть, а baseline-детекторы его не покрыли.

Ключевая ошибка первой редакции (найдена внешним ресерчем 08.09.2026,
подтверждена замером на нашем корпусе: из 7 пропущенных baseline
gold-сущностей 5 (71%) лежат в сегментах, где что-то ДРУГОЕ уже найдено) —
исключать из выборки СЕГМЕНТ целиком, если в нём сработал хоть один
детектор. Найденный ИНН не закрывает стоящую рядом фамилию. Поэтому здесь
отбор идёт по **непокрытым кандидатным спанам** (`_covered`,
``build_windows``), а не по сегментам: сегмент участвует в выборке, если в
нём есть хотя бы один слабый сигнал ВНЕ уже принятых интервалов
``baseline_entities``.

Дедупликация окон — точная (по буквальному содержимому окна вместе с его
контекстом), не нормализованная: нормализация цифр в ``#`` схлопнула бы
``ООО «123»`` и ``ООО «456»`` в один ключ и перенесла бы решение по первому
на второе. Для каждого уникального текста окна хранятся ВСЕ его исходные
расположения (``_group_by_text``), а ответ модели проверяется заново для
КАЖДОГО расположения (``_resolve_window``) — на разных страницах документа
одно и то же окно оказывается в разных абсолютных координатах.

Модель не возвращает смещения. Ей показывается пронумерованный список окон
(``{"id": "w0", "text": "..."}``), и ответ обязан ссылаться на ``id``, а не
на позицию символа — при попытке подсунуть в ``id`` число (смещение) вместо
выданного идентификатора запись отбрасывается (``_dispatch_batch``), и то
окно, для которого не нашлось ни одной валидной ссылки, остаётся
``unverified`` с причиной ``missing_window``.

Несовпавшая или неоднозначная цитата — это ``unverified``, а не «ничего не
найдено»: см. ``Finding.status`` и ``WindowVerdict.status``. Технический
сбой (сеть, обрезанный JSON, превышение бюджета окон, отказ модели) не
должен превращаться в тихое ``entities: []`` — это выдало бы сбой за
доказанное отсутствие PII.

Слой только добавляет: ``verify_recall`` никогда не удаляет и не подменяет
``baseline_entities`` — только пристраивает новые, не пересекающиеся с ними
спаны (см. фильтр перекрытия в конце ``verify_recall``).

Незакрытое (осознанно, по указанию плана Р7): ablation размера окна
(предложение/строка таблицы против ±80/±160/±320 символов) и размера батча
(1/4/8/16/37) не проводился — взяты фиксированные умеренные значения
(``DEFAULT_WINDOW_CHARS``, ``DEFAULT_BATCH_SIZE``) как гипотеза, а не как
измеренный оптимум. JSON Schema со ``strict: true`` (GigaChat v1/v2) тоже не
подключена — контракт держится только на промпте и валидации на нашей
стороне, как и у уже существующего ``llm_filter_detector``.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from masker.detect.morph import _morph_vocab
from masker.detect.normalize import normalize_value
from masker.detect.orgforms import org_forms
from masker.llm import LLMError, LLMProvider, Message
from masker.model import Document, Entity, EntityType, Source

#: Ширина контекста вокруг кластера кандидатов, в символах в каждую сторону.
#: Гипотеза (см. докстринг модуля, п.7 TASKS.md Р7) — ablation не проводился.
DEFAULT_WINDOW_CHARS = 160

#: Сколько окон уходит в одном вызове `LLMProvider.complete()`. TASKS.md Р7,
#: п.5: «батч 8–16 окон, а не все сразу» — позиционные эффекты внутри
#: длинной пачки (BatchPrompt, ICLR 2024) не позволяют слать все окна одним
#: списком. Ablation конкретного числа внутри 8–16 не проводился.
DEFAULT_BATCH_SIZE = 12

#: Бюджет УНИКАЛЬНЫХ (после дедупа) окон на документ. Превышение не роняет
#: прогон — окна сверх бюджета просто помечаются `unverified` без обращения
#: к модели (см. докстрин `verify_recall`).
DEFAULT_MAX_WINDOWS = 200

#: Сколько раз повторить попытку на технический сбой (сеть, обрезанный JSON)
#: — «ограниченный повтор», не бесконечный (TASKS.md Р7, п.4).
MAX_ATTEMPTS = 2

#: Типы, которые верификатор имеет право предлагать — открытый класс, тот же,
#: что участвует в `ConfidenceLevel.POSSIBLE` (`masker.detect.confidence`).
VERIFIER_TYPES: frozenset[str] = frozenset({EntityType.PERSON, EntityType.ORG_NAME})

#: Уверенность найденной верификатором сущности — как решение модели по
#: контексту, а не точный формат/чек-сумма (тот же порядок величины, что у
#: `llm_filter_detector.LLM_FILTER_CONFIDENCE`).
VERIFIER_CONFIDENCE = 0.6

_CAPITALIZED_WORD_RE = re.compile(r"[А-ЯЁ][а-яё]+|[А-ЯЁ]{2,}")

_SYSTEM_PROMPT = (
    "Тебе показан пронумерованный список окон текста договора. В каждом окне может "
    'быть персональное имя человека (тип "person") или название организации (тип '
    '"org_name"), не помеченные разметкой. Верни ровно один JSON-объект без '
    'пояснений вида {"windows": [{"id": "w0", "entities": [{"text": "Иванов Пётр '
    'Сергеевич", "type": "person"}]}, {"id": "w1", "entities": []}]}. Обязательно '
    "верни запись для КАЖДОГО окна из входного списка, даже если в нём ничего нет "
    '— тогда "entities": []. Поле "text" — точная подстрока окна символ в символ, '
    'без изменений и сокращений. Поле "id" — ровно тот идентификатор окна, что '
    'дан во входе (например "w3"), а не число и не позиция символа в тексте.'
)


@dataclass(frozen=True, slots=True)
class Window:
    """Одно окно текста, отправляемое модели, с местом в исходном документе."""

    id: str
    segment_order: int
    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class Finding:
    """Один заявленный моделью факт («в этом окне есть person X») и его судьба."""

    #: "matched" | "unmatched_quote" | "ambiguous_quote" | "invalid_type" | "invalid_schema"
    status: str
    entity: Entity | None
    text: str
    type_: str


@dataclass(frozen=True, slots=True)
class WindowVerdict:
    """Итог по одному расположению окна — для отчёта/метрики r_verify."""

    window: Window
    status: str  # "verified" | "unverified"
    #: "" когда status == "verified"; иначе — почему нельзя доверять ответу:
    #: "llm_error" | "malformed_json" | "malformed_entities_field" |
    #: "missing_window" | "budget_exceeded" | "unresolved_claim".
    reason: str
    findings: tuple[Finding, ...] = ()


@dataclass(frozen=True, slots=True)
class VerifierResult:
    """Результат `verify_recall`: что добавить к baseline и как это проверялось."""

    entities: tuple[Entity, ...]
    verdicts: tuple[WindowVerdict, ...]


@functools.lru_cache(maxsize=8192)
def _any_name_grammeme(word: str) -> str | None:
    """Есть ли у слова ХОТЯ БЫ ОДИН морфологический разбор с граммемой имени.

    Отличие от `masker.detect.morph._classify_word` (Р4) принципиально, а
    не случайно: тот смотрит только на ПЕРВЫЙ (наиболее вероятный) разбор —
    это правильно для производственного детектора, который сам решает,
    маскировать ли найденное, и не должен ловить омонимы вроде «Вера»/
    «Слава»/«Надежда» (см. докстринг `morph.py`). Здесь решение не
    принимается — только строится список мест, которые стоит ПОКАЗАТЬ
    модели, поэтому сеть сознательно шире: слово с разбором-омонимом
    (частый нарицательный смысл первым, фамилия/имя — вторым) — тоже повод
    спросить модель, а не тихо промолчать. Ровно так в реальном корпусе
    (`contract_pdf_02_school.pdf`) находится «ЗУБРИЦКАЯ» — ПЕРВЫЙ разбор
    pymorphy2 для этого слова — прилагательное («зубрицкая», угадано по
    окончанию), фамильный разбор идёт вторым, и `_classify_word` (Р4)
    закономерно проходит мимо.
    """
    if not word or not (word[0].isalpha() and word[0].isupper()):
        return None
    if word.casefold() in org_forms().requisite_labels:
        return None
    for form in _morph_vocab()(word):
        tag = str(getattr(form, "tag", ""))
        for name_tag in ("Surn", "Name", "Patr"):
            if name_tag in tag:
                return name_tag
    return None


@functools.lru_cache(maxsize=1)
def _quoted_after_org_form_pattern() -> re.Pattern[str]:
    """Название в кавычках СРАЗУ ПОСЛЕ оргформы — сигнал организации (Р5:
    «кавычки после орг-формы»).

    Без требования «сразу после оргформы» кавычки ловят и заголовки
    ГОСТов/законов («ГОСТ 30524-2013 «Услуги общественного питания...»»,
    реальный ложный сигнал на `contract_pdf_02_school.pdf`, раздел
    нормативных ссылок) — они тоже в кавычках, но не организации, и раздули
    бы окна верификатора мусором в 3 раза. Оргформа перед кавычкой — то
    самое независимое подтверждение, которое отличает «ООО «Ромашка»» от
    «ГОСТ «Требования к персоналу»»."""
    forms_alt = "|".join(re.escape(form).replace(r"\ ", r"\s+") for form in org_forms().forms)
    quote_alt = "|".join(
        rf"{re.escape(opening)}[^{re.escape(closing)}]{{2,60}}{re.escape(closing)}"
        for opening, closing in org_forms().quote_pairs
    )
    return re.compile(rf"(?:{forms_alt})\s*(?:{quote_alt})", re.IGNORECASE)


def find_weak_signal_spans(text: str) -> list[tuple[int, int]]:
    """Найти в тексте сегмента места со слабым сигналом person/org_name.

    Два независимых признака: заглавное слово хотя бы с одним
    морфологическим разбором `Surn`/`Name`/`Patr` (шире, чем у
    `MorphPersonDetector`, Р4 — см. докстринг `_any_name_grammeme`) и
    название в кавычках сразу после оргформы (Р5: `_quoted_after_org_form_pattern`).
    """
    spans = [
        match.span()
        for match in _CAPITALIZED_WORD_RE.finditer(text)
        if _any_name_grammeme(match.group()) is not None
    ]
    spans.extend(match.span() for match in _quoted_after_org_form_pattern().finditer(text))
    return spans


def _covered(ranges: Sequence[tuple[int, int]], start: int, end: int) -> bool:
    return any(r_start < end and start < r_end for r_start, r_end in ranges)


def _cluster_spans(spans: list[tuple[int, int]], *, gap: int) -> list[tuple[int, int]]:
    """Слить соседние непокрытые спаны в один кластер, если их окна и так
    пересеклись бы (расстояние между ними не больше ``gap``) — иначе один и
    тот же кусок текста дублировался бы в несколько окон подряд."""
    ordered = sorted(spans)
    clusters: list[list[int]] = []
    for start, end in ordered:
        if clusters and start - clusters[-1][1] <= gap:
            clusters[-1][1] = max(clusters[-1][1], end)
        else:
            clusters.append([start, end])
    return [(c[0], c[1]) for c in clusters]


def _snap_left(text: str, pos: int) -> int:
    """Не резать слово границей окна слева (TASKS.md Р7, п.7)."""
    while pos > 0 and text[pos - 1].isalnum():
        pos -= 1
    return pos


def _snap_right(text: str, pos: int) -> int:
    """Не резать слово границей окна справа."""
    while pos < len(text) and text[pos].isalnum():
        pos += 1
    return pos


def build_windows(
    document: Document,
    baseline_entities: Sequence[Entity],
    *,
    window_chars: int = DEFAULT_WINDOW_CHARS,
) -> list[Window]:
    """Построить окна вокруг непокрытых кандидатных спанов (см. докстринг модуля).

    Сегмент попадает в выборку, только если в нём есть хотя бы один слабый
    сигнал ВНЕ уже принятых ``baseline_entities`` — не «в сегменте ничего не
    найдено», а «в сегменте есть непокрытое место», это и есть исправление
    ошибки первой редакции.
    """
    occupied: dict[int, list[tuple[int, int]]] = {}
    for entity in baseline_entities:
        occupied.setdefault(entity.segment_order, []).append((entity.start, entity.end))

    windows: list[Window] = []
    counter = 0
    for segment in document.segments:
        ranges = occupied.get(segment.order, ())
        raw_spans = find_weak_signal_spans(segment.text)
        residual = [span for span in raw_spans if not _covered(ranges, span[0], span[1])]
        if not residual:
            continue
        for cluster_start, cluster_end in _cluster_spans(residual, gap=window_chars):
            start = _snap_left(segment.text, max(0, cluster_start - window_chars))
            end = _snap_right(segment.text, min(len(segment.text), cluster_end + window_chars))
            windows.append(
                Window(
                    id=f"w{counter}",
                    segment_order=segment.order,
                    start=start,
                    end=end,
                    text=segment.text[start:end],
                )
            )
            counter += 1
    return windows


def _group_by_text(windows: Sequence[Window]) -> dict[str, list[Window]]:
    """Точная (не нормализованная) дедупликация — см. докстринг модуля."""
    groups: dict[str, list[Window]] = {}
    for window in windows:
        groups.setdefault(window.text, []).append(window)
    return groups


def _chunks(items: Sequence[Window], size: int) -> list[list[Window]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def _build_messages(batch: Sequence[Window]) -> list[Message]:
    payload = {"windows": [{"id": window.id, "text": window.text} for window in batch]}
    return [
        Message("system", _SYSTEM_PROMPT),
        Message(
            "user", json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        ),
    ]


def _call_with_retry(llm: LLMProvider, batch: Sequence[Window]) -> str | None:
    """До `MAX_ATTEMPTS` попыток на отказ модели — «ограниченный повтор»,
    не бесконечный. Возвращает `None`, если все попытки провалились."""
    messages = _build_messages(batch)
    for _attempt in range(MAX_ATTEMPTS):
        try:
            return llm.complete(messages)
        except LLMError:
            continue
    return None


def _parse_top_level(raw: str) -> list[object] | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    windows = parsed.get("windows")
    if not isinstance(windows, list):
        return None
    return windows


def _find_bounded(window_text: str, needle: str) -> list[re.Match[str]]:
    """Точные вхождения ``needle`` в ``window_text`` с проверкой границ слова.

    ``(?<!\\w)``/``(?!\\w)`` не дают засчитать «Иван» внутри «Иванов» —
    после найденной подстроки идёт буква, лукахед не проходит, и совпадение
    просто не попадает в список (TASKS.md Р7, п.3).
    """
    pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
    return list(pattern.finditer(window_text))


def _resolve_claim(window: Window, claim: object) -> Finding:
    if not isinstance(claim, dict):
        return Finding(status="invalid_schema", entity=None, text="", type_="")
    text = claim.get("text")
    type_ = claim.get("type")
    if not isinstance(text, str) or not text.strip():
        return Finding(status="invalid_schema", entity=None, text="", type_=str(type_))
    if type_ not in VERIFIER_TYPES:
        return Finding(status="invalid_type", entity=None, text=text, type_=str(type_))
    matches = _find_bounded(window.text, text)
    if not matches:
        return Finding(status="unmatched_quote", entity=None, text=text, type_=type_)
    if len(matches) > 1:
        # «При нескольких вхождениях строки не выбирать молча первое»
        # (TASKS.md Р7, п.3) — неоднозначность идёт в unverified, а не в
        # тихий выбор произвольного вхождения.
        return Finding(status="ambiguous_quote", entity=None, text=text, type_=type_)
    match = matches[0]
    start = window.start + match.start()
    end = window.start + match.end()
    entity = Entity(
        type=type_,
        text=text,
        segment_order=window.segment_order,
        start=start,
        end=end,
        source=Source.LLM,
        confidence=VERIFIER_CONFIDENCE,
        normalized=normalize_value(type_, text),
    )
    return Finding(status="matched", entity=entity, text=text, type_=type_)


def _resolve_window(window: Window, claims: Sequence[object]) -> tuple[Finding, ...]:
    return tuple(_resolve_claim(window, claim) for claim in claims)


def _dispatch_batch(
    llm: LLMProvider,
    batch: Sequence[Window],
    claims_by_text: dict[str, list[object]],
    error_by_text: dict[str, str],
) -> None:
    """Один вызов модели на батч, разложенный по текстам окон-представителей."""
    raw = _call_with_retry(llm, batch)
    if raw is None:
        for window in batch:
            error_by_text[window.text] = "llm_error"
        return
    parsed = _parse_top_level(raw)
    if parsed is None:
        for window in batch:
            error_by_text[window.text] = "malformed_json"
        return

    known_ids = {window.id: window.text for window in batch}
    responded: set[str] = set()
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        window_id = entry.get("id")
        # Ответ со смещением (число) или незнакомым id вместо выданного
        # идентификатора окна отвергается целиком (TASKS.md Р7, п.3) — не
        # пытаемся угадать, какое окно имелось в виду.
        if not isinstance(window_id, str) or window_id not in known_ids:
            continue
        entities_field = entry.get("entities")
        text = known_ids[window_id]
        if not isinstance(entities_field, list):
            error_by_text[text] = "malformed_entities_field"
            responded.add(window_id)
            continue
        claims_by_text[text] = entities_field
        responded.add(window_id)

    for window in batch:
        if window.id not in responded:
            error_by_text[window.text] = "missing_window"


def verify_recall(
    document: Document,
    baseline_entities: Sequence[Entity],
    llm: LLMProvider,
    *,
    window_chars: int = DEFAULT_WINDOW_CHARS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_windows: int = DEFAULT_MAX_WINDOWS,
) -> VerifierResult:
    """Найти сущности, пропущенные ``baseline_entities``, через `LLMProvider`.

    Пайплайн: кандидаты (``build_windows``) → точная дедупликация
    (``_group_by_text``) → бюджет окон → батчи по ``batch_size`` →
    `LLMProvider.complete()` с ограниченным повтором → разбор ответа без
    доверия к смещениям → проверка цитаты в указанном окне с проверкой
    границ слова → перенос решения на ВСЕ расположения дедуплицированного
    окна с повторной локальной валидацией на каждом. Слой только добавляет:
    сущность, чей спан пересекается с уже принятой ``baseline_entities`` в
    том же сегменте, не добавляется повторно (структурно такого быть не
    должно — окна строятся только из непокрытых спанов, — фильтр здесь на
    случай, если модель процитировала другой, случайно перекрывающийся
    кусок текста).
    """
    windows = build_windows(document, baseline_entities, window_chars=window_chars)
    groups = _group_by_text(windows)
    representatives = [group[0] for group in groups.values()]

    claims_by_text: dict[str, list[object]] = {}
    error_by_text: dict[str, str] = {}

    budgeted = representatives[:max_windows]
    for window in representatives[max_windows:]:
        error_by_text[window.text] = "budget_exceeded"

    for batch in _chunks(budgeted, batch_size):
        _dispatch_batch(llm, batch, claims_by_text, error_by_text)

    baseline_by_segment: dict[int, list[tuple[int, int]]] = {}
    for entity in baseline_entities:
        baseline_by_segment.setdefault(entity.segment_order, []).append((entity.start, entity.end))

    entities: list[Entity] = []
    verdicts: list[WindowVerdict] = []
    for text, locations in groups.items():
        error = error_by_text.get(text)
        for window in locations:
            if error is not None:
                verdicts.append(WindowVerdict(window=window, status="unverified", reason=error))
                continue
            findings = _resolve_window(window, claims_by_text.get(text, []))
            all_matched = all(finding.status == "matched" for finding in findings)
            verdicts.append(
                WindowVerdict(
                    window=window,
                    status="verified" if all_matched else "unverified",
                    reason="" if all_matched else "unresolved_claim",
                    findings=findings,
                )
            )
            for finding in findings:
                if finding.entity is None:
                    continue
                ranges = baseline_by_segment.get(finding.entity.segment_order, ())
                if _covered(ranges, finding.entity.start, finding.entity.end):
                    continue
                entities.append(finding.entity)

    entities.sort(key=lambda item: (item.segment_order, item.start, item.end, item.type))
    verdicts.sort(key=lambda item: (item.window.segment_order, item.window.start, item.window.id))
    return VerifierResult(entities=tuple(entities), verdicts=tuple(verdicts))


@dataclass(frozen=True, slots=True)
class FilterCoverage:
    """r_filter (TASKS.md Р7): доля пропущенных baseline сущностей, реально
    попавших хотя бы в одно окно `build_windows` — потолок пользы слоя: чего
    фильтр не показал модели, того она не найдёт никогда."""

    document: str
    missed_baseline: int
    covered_by_windows: int

    @property
    def r_filter(self) -> float | None:
        if not self.missed_baseline:
            return None
        return self.covered_by_windows / self.missed_baseline


def _collapse(text: str) -> str:
    return " ".join(text.split())


def measure_filter_coverage(
    document: Document,
    baseline_entities: Sequence[Entity],
    gold_entities: Sequence[tuple[str, str]],
    *,
    window_chars: int = DEFAULT_WINDOW_CHARS,
    label: str = "",
) -> FilterCoverage:
    """Посчитать r_filter на одном документе с известной разметкой.

    ``gold_entities`` — пары (тип, текст) из ``*.labels.json`` корпуса.
    Сравнение текстовое (в разметке нет смещений), как и остальной
    `masker.eval` (см. ``_collapse``/``score`` там же) — здесь код
    самодостаточен и не импортирует ``masker.eval``, чтобы не зависеть от
    модуля, которым занимается соседняя задача (отчёт/валидация).
    """
    found_keys = {(entity.type, _collapse(entity.text)) for entity in baseline_entities}
    missed = [
        (etype, etext)
        for etype, etext in gold_entities
        if etype in VERIFIER_TYPES and (etype, _collapse(etext)) not in found_keys
    ]
    windows = build_windows(document, baseline_entities, window_chars=window_chars)
    window_texts = [_collapse(window.text) for window in windows]
    covered = sum(
        1
        for _etype, etext in missed
        if any(_collapse(etext) in window_text for window_text in window_texts)
    )
    return FilterCoverage(document=label, missed_baseline=len(missed), covered_by_windows=covered)
