"""Тесты `MorphPersonDetector` — морфологический детектор ФИО (Р4).

Переносит замер `spikes/detect_soft_pii_spike.py` в тесты: три кейса
пропуска мягких PII (одиночное имя, «оглы»-хвост, обрезанная точка
инициала) и негативный корпус (юридические штампы без единой персоны).
"""

from __future__ import annotations

from masker.detect import DetectAgent, default_detectors
from masker.detect.morph import MorphPersonDetector
from masker.model import Anchor, Document, EntityType, Segment, Source


def _document(text: str) -> Document:
    return Document(
        path="x.docx",
        fmt="docx",
        segments=[Segment(text=text, anchor=Anchor(fmt="docx", locator=("body", 0)), order=0)],
    )


def _persons_via_pipeline(text: str) -> list[str]:
    document = _document(text)
    agent = DetectAgent(default_detectors())
    return [
        entity.text
        for entity in agent.detect(document).entities
        if entity.type is EntityType.PERSON
    ]


def _persons_via_detector(text: str) -> list[str]:
    return [entity.text for entity in MorphPersonDetector().detect(_document(text))]


# ---------------------------------------------------------------------------
# Р4, кейс 1: одиночное имя, которое NatashaDetector отбрасывает целиком —
# у него нет независимого подтверждения (план T2.2.1, шаг 7), а других
# упоминаний Оксаны в тексте нет.
# ---------------------------------------------------------------------------


def test_standalone_first_name_is_found_through_pipeline() -> None:
    text = "Контактное лицо со стороны Заказчика — Оксана (внутр. 4417), почта oksana.p@mail.ru"
    assert "Оксана" in _persons_via_pipeline(text)


def test_standalone_name_gets_lower_confidence() -> None:
    entities = MorphPersonDetector().detect(_document("Есть Оксана в тексте"))
    matches = [e for e in entities if e.text == "Оксана"]
    assert len(matches) == 1
    assert matches[0].source is Source.NER
    assert 0 < matches[0].confidence < 0.7


def test_single_uppercase_abbreviation_is_not_person(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Р13: словарный разбор не должен выпускать аббревиатуру «МИК»."""
    monkeypatch.setattr(
        "masker.detect.morph._classify_word",
        lambda word: "Name" if word == "МИК" else None,
    )

    assert _persons_via_detector("МИК") == []


# ---------------------------------------------------------------------------
# Р4, кейс 2 и 3 — уже чинятся в orgforms.py (fix_person_initials/
# shrink_span), но пайплайн целиком обязан отдавать полный кейс.
# ---------------------------------------------------------------------------


def test_oglu_suffix_stays_in_span() -> None:
    text = "Согласовано: Мамедов Э.Г.о., начальник ОТК"
    persons = _persons_via_pipeline(text)
    assert any(p.startswith("Мамедов Э.Г.о") for p in persons), persons


def test_trailing_initial_dot_is_kept_at_segment_end() -> None:
    text = "Подписал: и.о. начальника управления материально-технического снабжения Пилипенко С.А."
    assert "Пилипенко С.А." in _persons_via_pipeline(text)


# ---------------------------------------------------------------------------
# Правило слияния: подряд Surn+Name+Patr в любом порядке — высокая
# уверенность, даже если сам NatashaDetector не смолчал бы (эти строки
# он уже находит верно) — здесь достаточно не потерять их и в morph.py.
# ---------------------------------------------------------------------------


def test_consecutive_surn_name_patr_high_confidence() -> None:
    text = "Работы выполняет субподрядчик — Индивидуальный предприниматель Гурьянов Пётр Семёнович"
    entities = MorphPersonDetector().detect(_document(text))
    match = next(e for e in entities if e.text == "Гурьянов Пётр Семёнович")
    assert match.confidence >= 0.85


def test_full_name_declined_form_high_confidence() -> None:
    text = (
        "Поставщик: ООО «Северный ветер», в лице генерального"
        " директора Курбангалеева Рустэма Ильдаровича"
    )
    entities = MorphPersonDetector().detect(_document(text))
    match = next(e for e in entities if e.text == "Курбангалеева Рустэма Ильдаровича")
    assert match.confidence >= 0.85


def test_uppercase_surname_is_included_before_name_and_patronymic() -> None:
    """Сертификат ЭП не оставляет фамилию видимой из-за верхнего регистра."""
    text = "ФИО: ЗУБРИЦКАЯ ТАТЬЯНА ИВАНОВНА Должность: ДИРЕКТОР"
    assert _persons_via_detector(text) == ["ЗУБРИЦКАЯ ТАТЬЯНА ИВАНОВНА"]


# ---------------------------------------------------------------------------
# Негативный корпус: юридические штампы без единой персоны — обязателен
# ноль срабатываний (приёмка Р4).
# ---------------------------------------------------------------------------


def test_no_false_positives_on_legal_boilerplate() -> None:
    texts = [
        "Настоящий договор составлен в соответствии с ГОСТ Р 51141-98 и Правилами перевозок",
        "Стороны руководствуются Гражданским кодексом Российской Федерации",
    ]
    for text in texts:
        assert _persons_via_detector(text) == [], text


def test_no_false_positive_on_common_legal_words() -> None:
    """Слова-роли и юридические термины без граммем Surn/Name/Patr — как в
    замере Р4: Договор, Кодексом, Стороны, Поставщик, Российской, Настоящий
    не дают ни одной персоны."""
    text = "Договор Кодексом Стороны Поставщик Российской Настоящий"
    assert _persons_via_detector(text) == []


# ---------------------------------------------------------------------------
# Идентичность двух прогонов (детерминизм, инвариант AGENTS.md).
# ---------------------------------------------------------------------------


def test_deterministic_across_runs() -> None:
    text = "Согласовано: Мамедов Э.Г.о., начальник ОТК. Есть также Оксана рядом."
    first = _persons_via_detector(text)
    second = _persons_via_detector(text)
    assert first == second
