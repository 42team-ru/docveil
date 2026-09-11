"""Тесты `detect.verifier` — LLM-верификатор на recall (Р7, TASKS.md).

Каждый тест бьёт по одному пункту приёмки Р7:

1. Кандидат-спан, а не сегмент — сегмент с найденным ИНН и НЕ найденной
   фамилией рядом обязан попасть в выборку.
2. Полностью покрытый сигнал не даёт окна.
3. Объём входа на `contract_pdf_02_school.pdf` не превышает 5% документа.
4. Ответ со смещением (числом) вместо номера окна отвергается.
5. Несовпавшая цитата даёт `unverified`, а не пустой результат.
6. Неоднозначная цитата (несколько вхождений) не выбирает молча первое.
7. Совпавшая цитата даёт сущность с правильными абсолютными смещениями.
8. Слой только добавляет — не дублирует то, что уже есть в baseline.
9. `MASKER_LLM=fake` не роняет пайплайн (ни `verify_recall`, ни `DetectAgent`).
10. Бюджет окон и отказ модели дают `unverified`, а не падение прогона.
11. `r_filter` считается верно и не делится на ноль, когда пропусков нет.
12. Р7-1: вердикты верификатора выходят наружу через `DetectionResult.verifier`
    и через реальную проводку `deps.llm` в `make_detect_node`.

Имена в фикстурах взяты так, чтобы реально иметь хотя бы один морфологический
разбор с граммемой `Surn`/`Name`/`Patr` (`masker.detect.morph.has_name_grammeme`)
— «Персонова»/«Особая» словарь не распознаёт как имя/фамилию ни в одном
разборе, поэтому для сигналов используются реальные словарные фамилии/имена/
отчества («Смирнова», «Иванов», «Пётр»).
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from masker.detect import DetectAgent
from masker.detect.verifier import (
    DEFAULT_WINDOW_CHARS,
    Window,
    build_windows,
    measure_filter_coverage,
    summarize_verdicts,
    verify_recall,
)
from masker.graph import nodes
from masker.ingest.pdf_ingest import ingest_pdf
from masker.llm import FakeProvider, LLMError, Message, get_provider
from masker.model import Anchor, Document, Entity, EntityType, Segment, Source

FIXTURES = pathlib.Path(__file__).resolve().parents[3] / "fixtures" / "labeled"


def _segment(text: str, order: int = 0) -> Segment:
    return Segment(text=text, anchor=Anchor("docx", ("body", order)), order=order)


def _document(*texts: str) -> Document:
    return Document(
        path="test.docx",
        fmt="docx",
        segments=[_segment(text, order) for order, text in enumerate(texts)],
    )


def _entity(
    etype: str, text: str, start: int, *, segment_order: int = 0, source: Source = Source.RULE
) -> Entity:
    return Entity(
        type=etype,
        text=text,
        segment_order=segment_order,
        start=start,
        end=start + len(text),
        source=source,
    )


class _ScriptedProvider:
    """Провайдер с заранее заданными ответами, считающий число вызовов.

    ``schema`` не игнорируется молча, а запоминается по вызову (``schemas``)
    — так тест на подключение JSON Schema (Р7-3/Р7-4, TASKS.md: «GigaChat
    документирует JSON Schema со strict: true») проверяет, что
    ``verify_recall`` реально передаёт схему в ``LLMProvider.complete``, а не
    просто не падает на новом именованном параметре протокола.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.schemas: list[dict[str, object] | None] = []

    def complete(self, messages: list[Message], *, schema: dict[str, object] | None = None) -> str:
        del messages
        self.calls += 1
        self.schemas.append(schema)
        if not self._responses:
            raise AssertionError("неожиданный дополнительный вызов LLM")
        return self._responses.pop(0)


def _windows_response(entries: list[dict[str, object]]) -> str:
    return json.dumps({"windows": entries}, ensure_ascii=False)


# --- 1: кандидат-спан, а не сегмент -----------------------------------------


def test_segment_with_found_inn_and_missed_surname_is_selected() -> None:
    """Ключевая регрессия ресерча: 5 из 7 пропущенных сущностей лежали в
    сегментах, где что-то ДРУГОЕ уже найдено (TASKS.md Р7). Найденный ИНН
    не имеет права закрыть стоящую рядом непойманную фамилию."""
    text = "ИНН 7727123456, контактное лицо Смирнова."
    document = _document(text)
    inn_start = text.index("7727123456")
    baseline = [_entity(EntityType.INN, "7727123456", inn_start)]

    windows = build_windows(document, baseline)

    assert len(windows) == 1
    assert "Смирнова" in windows[0].text


def test_fully_covered_signal_produces_no_window() -> None:
    text = "Директор Смирнова Татьяна Ивановна подписала договор."
    document = _document(text)
    start = text.index("Смирнова")
    end = text.index("Ивановна") + len("Ивановна")
    baseline = [_entity(EntityType.PERSON, text[start:end], start)]

    windows = build_windows(document, baseline)

    assert windows == []


# --- 3: объём входа не превышает 5% документа --------------------------------


def test_verifier_payload_stays_under_5_percent_of_document() -> None:
    path = FIXTURES / "contract_pdf_02_school.pdf"
    document = ingest_pdf(path)
    baseline = DetectAgent().detect(document).entities

    windows = build_windows(document, baseline)
    unique_texts = {window.text for window in windows}

    whole = len(document.text())
    payload = sum(len(text) for text in unique_texts)

    assert whole > 0
    assert payload / whole <= 0.05, f"{payload}/{whole} = {payload / whole:.3f} > 5%"


# --- 4: ответ со смещением вместо id окна отвергается -------------------------


def test_offset_instead_of_window_id_is_rejected() -> None:
    text = "Контактное лицо: Смирнова, распорядитель."
    document = _document(text)

    provider = _ScriptedProvider(
        [_windows_response([{"id": 145, "entities": [{"text": "Смирнова", "type": "person"}]}])]
    )

    result = verify_recall(document, [], provider)

    assert result.entities == ()
    assert len(result.verdicts) == 1
    verdict = result.verdicts[0]
    assert verdict.status == "unverified"
    assert verdict.reason == "missing_window"


def test_unknown_string_id_is_also_rejected() -> None:
    """Не только число — любой id, не выданный нами, отвергается так же."""
    text = "Контактное лицо: Смирнова, распорядитель."
    document = _document(text)

    provider = _ScriptedProvider(
        [_windows_response([{"id": "w99", "entities": [{"text": "Смирнова", "type": "person"}]}])]
    )

    result = verify_recall(document, [], provider)

    assert result.entities == ()
    assert result.verdicts[0].status == "unverified"
    assert result.verdicts[0].reason == "missing_window"


# --- 5: несовпавшая цитата -> unverified, не пустой результат -----------------


def test_unmatched_quote_gives_unverified_not_silent_empty() -> None:
    text = "Контактное лицо: Смирнова, распорядитель."
    document = _document(text)
    windows = build_windows(document, [])
    assert len(windows) == 1
    window_id = windows[0].id

    provider = _ScriptedProvider(
        [
            _windows_response(
                [{"id": window_id, "entities": [{"text": "Совсем другой текст", "type": "person"}]}]
            )
        ]
    )

    result = verify_recall(document, [], provider)

    assert result.entities == ()
    verdict = result.verdicts[0]
    assert verdict.status == "unverified"
    assert verdict.reason == "unresolved_claim"
    assert len(verdict.findings) == 1
    assert verdict.findings[0].status == "unmatched_quote"


def test_quote_embedded_inside_a_longer_word_is_invalid_span() -> None:
    """«Иван» внутри «Иванов» — невалидный спан (TASKS.md Р7, п.3)."""
    text = "Подписал документ гражданин Иванов, торговый представитель."
    document = _document(text)
    windows = build_windows(document, [])
    assert len(windows) == 1
    window_id = windows[0].id

    provider = _ScriptedProvider(
        [_windows_response([{"id": window_id, "entities": [{"text": "Иван", "type": "person"}]}])]
    )

    result = verify_recall(document, [], provider)

    assert result.entities == ()
    assert result.verdicts[0].status == "unverified"
    assert result.verdicts[0].findings[0].status == "unmatched_quote"


# --- 6: неоднозначная цитата не выбирает молча первое вхождение --------------


def test_ambiguous_quote_with_multiple_occurrences_is_not_silently_resolved() -> None:
    text = "Смирнова встретилась со Смирнова у входа в офис."
    document = _document(text)
    windows = build_windows(document, [])
    assert len(windows) == 1
    window_id = windows[0].id

    provider = _ScriptedProvider(
        [
            _windows_response(
                [{"id": window_id, "entities": [{"text": "Смирнова", "type": "person"}]}]
            )
        ]
    )

    result = verify_recall(document, [], provider)

    assert result.entities == ()
    assert result.verdicts[0].status == "unverified"
    assert result.verdicts[0].findings[0].status == "ambiguous_quote"


# --- 7: совпавшая цитата даёт сущность с верными смещениями -------------------


def test_matched_claim_produces_entity_with_correct_absolute_offsets() -> None:
    text = "Контактное лицо: Смирнова Татьяна Ивановна, распорядитель."
    document = _document(text)
    windows = build_windows(document, [])
    assert len(windows) == 1
    window_id = windows[0].id

    provider = _ScriptedProvider(
        [
            _windows_response(
                [
                    {
                        "id": window_id,
                        "entities": [{"text": "Смирнова Татьяна Ивановна", "type": "person"}],
                    }
                ]
            )
        ]
    )

    result = verify_recall(document, [], provider)

    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.text == "Смирнова Татьяна Ивановна"
    assert entity.type == EntityType.PERSON
    assert entity.source == Source.LLM
    assert text[entity.start : entity.end] == "Смирнова Татьяна Ивановна"
    assert result.verdicts[0].status == "verified"


def test_matched_claim_with_wrong_type_is_rejected() -> None:
    text = "Контактное лицо: Смирнова, распорядитель."
    document = _document(text)
    windows = build_windows(document, [])
    window_id = windows[0].id

    provider = _ScriptedProvider(
        [_windows_response([{"id": window_id, "entities": [{"text": "Смирнова", "type": "inn"}]}])]
    )

    result = verify_recall(document, [], provider)

    assert result.entities == ()
    assert result.verdicts[0].findings[0].status == "invalid_type"


# --- 8: слой только добавляет -------------------------------------------------


def test_verifier_does_not_duplicate_a_span_already_in_baseline() -> None:
    """Если модель процитировала кусок текста, пересекающийся с уже принятой
    baseline-сущностью, повторная сущность не добавляется — слой только
    добавляет, не плодит дублей поверх уже найденного."""
    text = "ИНН 7727123456, контактное лицо Смирнова."
    document = _document(text)
    inn_start = text.index("7727123456")
    baseline = [_entity(EntityType.INN, "7727123456", inn_start)]
    windows = build_windows(document, baseline)
    window_id = windows[0].id

    provider = _ScriptedProvider(
        [
            _windows_response(
                [
                    {
                        "id": window_id,
                        "entities": [
                            {"text": "7727123456", "type": "person"},
                            {"text": "Смирнова", "type": "person"},
                        ],
                    }
                ]
            )
        ]
    )

    result = verify_recall(document, baseline, provider)

    # "7727123456" пересекается с уже принятым ИНН и не добавляется повторно,
    # "Смирнова" — новая, добавляется.
    assert len(result.entities) == 1
    assert result.entities[0].text == "Смирнова"


# --- 9: MASKER_LLM=fake не роняет пайплайн ------------------------------------


def test_fake_provider_default_response_yields_unverified_not_crash() -> None:
    """`FakeProvider()` без заготовленных ответов отвечает заглушкой без
    ключа "windows" — с подключённой в Р7-4 строгой схемой (`_RESPONSE_SCHEMA`)
    это ловится ещё в `FakeProvider.complete()` как несоответствие `schema`
    (`LLMError`), а не как `malformed_json` уже на нашей стороне разбора —
    оба исхода технические, ни один не превращается в тихое `entities: []`."""
    text = "Контактное лицо: Смирнова, распорядитель."
    document = _document(text)
    llm = FakeProvider()  # ответ по умолчанию не соответствует _RESPONSE_SCHEMA

    result = verify_recall(document, [], llm)

    assert result.entities == ()
    assert result.verdicts
    assert all(v.status == "unverified" and v.reason == "llm_error" for v in result.verdicts)


def test_detect_agent_with_fake_llm_does_not_raise() -> None:
    text = "Контактное лицо: Смирнова, распорядитель."
    document = _document(text)

    entities = DetectAgent(llm=FakeProvider()).detect(document).entities

    assert isinstance(entities, list)


def test_detect_agent_without_llm_is_unaffected() -> None:
    """Дефолт `llm=None` — поведение `DetectAgent` не меняется вообще."""
    text = "Контактное лицо: Смирнова, распорядитель."
    document = _document(text)

    with_default = DetectAgent().detect(document).entities
    without_llm = DetectAgent(llm=None).detect(document).entities

    assert [(e.type, e.text, e.start, e.end) for e in with_default] == [
        (e.type, e.text, e.start, e.end) for e in without_llm
    ]


# --- 12: вердикты наружу (Р7-1) -------------------------------------------------


def test_detect_agent_without_llm_has_no_verifier_report() -> None:
    document = _document("Контактное лицо: Смирнова, распорядитель.")

    result = DetectAgent().detect(document)

    assert result.verifier is None


def test_detect_agent_with_llm_reports_verdict_per_built_window() -> None:
    """`DetectionResult.verifier` — не пустышка: вердикт на каждое окно,
    включая `unverified` (`FakeProvider()` по умолчанию отвечает без ключа
    "windows" — со строгой схемой (Р7-4) это `llm_error`: `FakeProvider`
    отвергает несоответствующий `_RESPONSE_SCHEMA` ответ ещё до того, как мы
    успеваем распарсить его сами)."""
    text = "Директор ЗУБРИЦКАЯ подписала договор аренды помещения."
    document = _document(text)
    baseline = DetectAgent().detect(document).entities
    assert baseline == []  # предпосылка: без верификатора спан не находится
    windows = build_windows(document, baseline)
    assert windows  # предпосылка: слабый сигнал есть и не покрыт baseline

    result = DetectAgent(llm=FakeProvider()).detect(document)

    assert result.verifier is not None
    assert result.verifier.windows == len(windows)
    assert len(result.verifier.verdicts) == result.verifier.windows
    assert result.verifier.verified + result.verifier.unverified == result.verifier.windows
    assert result.verifier.unverified_by_reason == {"llm_error": result.verifier.windows}


def test_summarize_verdicts_counts_input_chars_from_dispatched_windows_only() -> None:
    """`input_chars` — объём УНИКАЛЬНОГО текста, реально ушедшего в модель:
    окно, срезанное бюджетом (`budget_exceeded`), в модель не уходило и не
    должно раздувать эту цифру."""
    texts = [f"Контактное лицо {i}: Смирнова{i}, распорядитель." for i in range(3)]
    document = _document(*texts)
    windows = build_windows(document, [])
    assert len(windows) == 3

    provider = _ScriptedProvider([_windows_response([{"id": windows[0].id, "entities": []}])])
    result = verify_recall(document, [], provider, max_windows=1, batch_size=1)

    report = summarize_verdicts(document, result)

    assert report.windows == 3
    assert report.verified == 1
    assert report.unverified_by_reason == {"budget_exceeded": 2}
    assert report.input_chars == len(windows[0].text)
    assert report.document_chars == sum(len(text) for text in texts)


def test_make_detect_node_wires_llm_into_verifier() -> None:
    """Приёмка Р7-1, п.3: без ``llm=deps.llm`` в ``DetectAgent`` слой
    верификатора в графе мёртв при любом ``MASKER_LLM`` — провайдер ни разу
    не вызывается. Тест обязан упасть при откате проводки в
    ``make_detect_node``."""
    text = "Директор ЗУБРИЦКАЯ подписала договор аренды помещения."
    state: dict[str, object] = {
        "path": "test.docx",
        "fmt": "docx",
        "segments": [
            {
                "text": text,
                "anchor": {"fmt": "docx", "locator": ["body", 0], "label": None},
                "order": 0,
            }
        ],
        "options": {"rules_only": False, "types": None, "interactive": False},
    }
    provider = FakeProvider()

    state.update(nodes.make_detect_node(nodes.RunDeps(llm=provider))(state))

    assert provider.calls > 0


def test_make_detect_node_rules_only_never_calls_llm() -> None:
    """``--rules-only`` обязан остаться офлайн даже при заданном ``deps.llm``
    — «только регулярки/контрольные суммы» не должно тихо начать ходить
    в сеть через верификатор."""
    text = "Директор ЗУБРИЦКАЯ подписала договор аренды помещения."
    state: dict[str, object] = {
        "path": "test.docx",
        "fmt": "docx",
        "segments": [
            {
                "text": text,
                "anchor": {"fmt": "docx", "locator": ["body", 0], "label": None},
                "order": 0,
            }
        ],
        "options": {"rules_only": True, "types": None, "interactive": False},
    }
    provider = FakeProvider()

    state.update(nodes.make_detect_node(nodes.RunDeps(llm=provider))(state))

    assert provider.calls == 0


# --- 10: бюджет и отказ модели -------------------------------------------------


def test_llm_error_after_exhausted_retries_is_unverified_not_masked_silently() -> None:
    text = "Контактное лицо: Смирнова, распорядитель."
    document = _document(text)

    class _AlwaysFails:
        def __init__(self) -> None:
            self.calls = 0

        def complete(
            self, messages: list[Message], *, schema: dict[str, object] | None = None
        ) -> str:
            del messages, schema
            self.calls += 1
            raise LLMError("сеть недоступна")

    provider = _AlwaysFails()
    result = verify_recall(document, [], provider)

    assert result.entities == ()
    assert result.verdicts[0].status == "unverified"
    assert result.verdicts[0].reason == "llm_error"
    assert provider.calls == 2  # ограниченный повтор (MAX_ATTEMPTS), не бесконечный


def test_budget_exceeded_skips_llm_call_for_overflow_window() -> None:
    texts = [f"Контактное лицо {i}: Смирнова{i}, распорядитель." for i in range(3)]
    document = _document(*texts)
    windows = build_windows(document, [])
    assert len(windows) == 3

    provider = _ScriptedProvider([_windows_response([{"id": windows[0].id, "entities": []}])])
    # max_windows=1: только первое окно уходит в модель, остальные два — budget_exceeded.
    result = verify_recall(document, [], provider, max_windows=1, batch_size=1)

    reasons = [v.reason for v in result.verdicts]
    assert reasons.count("budget_exceeded") == 2
    assert provider.calls == 1


# --- 11: r_filter --------------------------------------------------------------


def test_measure_filter_coverage_computes_r_filter() -> None:
    text = "ИНН 7727123456, контактное лицо Смирнова."
    document = _document(text)
    inn_start = text.index("7727123456")
    baseline = [_entity(EntityType.INN, "7727123456", inn_start)]
    gold = [(EntityType.INN, "7727123456"), (EntityType.PERSON, "Смирнова")]

    coverage = measure_filter_coverage(document, baseline, gold, label="synthetic")

    assert coverage.missed_baseline == 1  # только person пропущен baseline
    assert coverage.covered_by_windows == 1  # и он реально попал в окно
    assert coverage.r_filter == 1.0


def test_measure_filter_coverage_r_filter_is_none_without_misses() -> None:
    text = "ИНН 7727123456 указан в реквизитах."
    document = _document(text)
    inn_start = text.index("7727123456")
    baseline = [_entity(EntityType.INN, "7727123456", inn_start)]
    gold = [(EntityType.INN, "7727123456")]

    coverage = measure_filter_coverage(document, baseline, gold, label="synthetic")

    assert coverage.missed_baseline == 0
    assert coverage.r_filter is None


# --- Р7-4: строгая JSON Schema подключена к вызову модели ---------------------


def test_verify_recall_passes_strict_schema_with_required_field() -> None:
    """TASKS.md Р7: «GigaChat документирует JSON Schema со strict: true —
    поле required обязательно, без него схема ничего не ограничивает».
    Проверяем, что ``verify_recall`` реально передаёт схему в
    ``LLMProvider.complete``, а не полагается только на промпт."""
    text = "Контактное лицо: Смирнова, распорядитель."
    document = _document(text)
    windows = build_windows(document, [])
    window_id = windows[0].id
    provider = _ScriptedProvider([_windows_response([{"id": window_id, "entities": []}])])

    verify_recall(document, [], provider)

    assert provider.schemas
    schema = provider.schemas[0]
    assert schema is not None
    assert schema["required"] == ["windows"]
    assert schema["additionalProperties"] is False
    windows_schema = schema["properties"]["windows"]["items"]
    assert set(windows_schema["required"]) == {"id", "entities"}
    entity_schema = windows_schema["properties"]["entities"]["items"]
    assert set(entity_schema["required"]) == {"text", "type"}
    assert set(entity_schema["properties"]["type"]["enum"]) == {"org_name", "person", "address"}


def test_fake_provider_rejects_answer_that_violates_schema() -> None:
    """`FakeProvider` — единственный офлайн-провайдер, реально умеющий
    проверить `schema` без сети (Р7-3): заготовленный ответ, где "type" не
    входит в перечисленные значения, обязан провалить схему тем же путём,
    что и сетевой сбой — `unverified`/`llm_error`, а не правдоподобный,
    но неверный результат."""
    text = "Контактное лицо: Смирнова, распорядитель."
    document = _document(text)

    invalid_response = _windows_response(
        [{"id": "w0", "entities": [{"text": "Смирнова", "type": "inn"}]}]
    )
    llm = FakeProvider([invalid_response])

    result = verify_recall(document, [], llm)

    assert result.entities == ()
    assert all(v.status == "unverified" and v.reason == "llm_error" for v in result.verdicts)


# --- контракт Window -----------------------------------------------------------


def test_window_ids_are_stable_strings_not_positions() -> None:
    text = "Смирнова Татьяна и Иванов Пётр встретились в офисе."
    document = _document(text)

    windows = build_windows(document, [])

    assert windows
    for window in windows:
        assert isinstance(window, Window)
        assert window.id.startswith("w")
        assert window.id[1:].isdigit()


def test_default_window_chars_is_positive() -> None:
    assert DEFAULT_WINDOW_CHARS > 0


# --- адрес: слабый сигнал и тип address ----------------------------------------


def test_address_type_claim_produces_address_entity() -> None:
    """Адресный обрывок (почтовый индекс) порождает окно, а ответ модели с
    type="address" добавляет сущность EntityType.ADDRESS в результат."""
    text = "Юридический адрес: 129090, г. Москва, ул. Большая Спасская, д. 25."
    document = _document(text)

    # Слабый сигнал — почтовый индекс и/или «г.»/«ул.» — должен породить окно.
    windows = build_windows(document, [])
    assert windows, "адресный обрывок должен породить хотя бы одно окно"
    window_id = windows[0].id
    full_address = "129090, г. Москва, ул. Большая Спасская, д. 25"

    provider = _ScriptedProvider(
        [
            _windows_response(
                [{"id": window_id, "entities": [{"text": full_address, "type": "address"}]}]
            )
        ]
    )

    result = verify_recall(document, [], provider)

    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.type == EntityType.ADDRESS
    assert entity.text == full_address
    assert entity.source == Source.LLM
    assert text[entity.start : entity.end] == full_address


# --- e2e: настоящий GigaChat ---------------------------------------------------


@pytest.mark.e2e
def test_verify_recall_live_gigachat_finds_uncovered_name() -> None:
    """E2E-прогон настоящего GigaChat: пропущенное baseline имя в явном
    контексте («Директор: ...») подтверждается моделью. Требует
    `MASKER_LLM=gigachat` и `GIGACHAT_CREDENTIALS` — иначе пропускается, как
    и `test_gigachat_live_smoke` (`tests/masker/llm/test_gigachat.py`)."""
    if os.environ.get("MASKER_LLM") != "gigachat" or not os.environ.get("GIGACHAT_CREDENTIALS"):
        pytest.skip("нужны MASKER_LLM=gigachat и GIGACHAT_CREDENTIALS")
    provider = get_provider()

    text = (
        "Настоящий акт составлен в подтверждение приёмки оборудования. "
        "Директор: Ковалевская Марина Эдуардовна. Дата составления акта не указана."
    )
    document = _document(text)

    result = verify_recall(document, [], provider)

    names = {finding.text for verdict in result.verdicts for finding in verdict.findings}
    assert any("Ковалевская" in name for name in names), (
        f"GigaChat не нашёл пропущенное имя ни в одной цитате: {names!r}, "
        f"verdicts={result.verdicts!r}"
    )
