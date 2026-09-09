from pathlib import Path

import pytest

from masker.detect.agent import DetectAgent
from masker.detect.confidence import classify_level
from masker.detect.result import DetectionResult, build_pii_chunks
from masker.ingest.docx_ingest import ingest_docx
from masker.judge import JudgeAgent
from masker.mask.agent import PlanAgent
from masker.model import (
    Action,
    Anchor,
    ConfidenceLevel,
    Document,
    Entity,
    EntityType,
    Segment,
    Source,
)
from masker.profile import ProfileAgent
from masker.refs import EntityIndex

FIXTURES = Path(__file__).parents[3] / "fixtures" / "labeled"


def test_contract_profiles_are_two_open_roles() -> None:
    """ "ДОГОВОР ПОСТАВКИ № 44/2026" (план T2.2.1, шаг 10) не образует
    собственного профиля: contract_number — факт о документе, не о
    стороне (`profile/agent.py::_DOCUMENT_LEVEL_TYPES`), остаётся
    unassigned и получает общий маркер через `group_key`, а не свой
    профиль на каждое вхождение (найдено на реальном PDF — без этого
    фильтра номер договора, повторённый в футере каждой страницы, получал
    новый профиль и новый маркер на каждом вхождении)."""
    document = ingest_docx(FIXTURES / "contract_01.docx")
    detection = DetectAgent().detect(document)
    result = ProfileAgent().profile(document, detection)
    assert [(profile.role_title, len(profile.members)) for profile in result.profiles] == [
        ("Поставщик", 11),
        ("Покупатель", 8),
    ]
    index = EntityIndex(detection.entities)
    contract_number_ref = next(
        index.ref(entity)
        for entity in detection.entities
        if entity.type is EntityType.CONTRACT_NUMBER
    )
    assert contract_number_ref in result.unassigned


def test_repeated_document_level_value_gets_one_consistent_profile() -> None:
    """Регрессия, найденная на реальном PDF-корпусе (план T2.2.1, пачка 5):

    один и тот же номер договора, повторённый в футере на разных
    страницах без контекста стороны, раньше образовывал СВОЙ профиль на
    каждое вхождение (52 вхождения — 51 разный маркер), потому что
    `cluster()` создавал синтетический профиль «СТОРОНА-N» для любого
    непомеченного блока, включая изолированные document-level факты.
    `_DOCUMENT_LEVEL_TYPES` держит такие типы вне блоков/кластеризации —
    все вхождения остаются unassigned и получают один маркер через
    `mask/keys.py::group_key` (AGENTS.md, «Согласованность псевдонимов»:
    одна и та же сущность во всём документе получает один и тот же маркер).
    """
    segments = [
        Segment("Договор №2025.1", Anchor("pdf", ("page", 0, 0, 15)), 0),
        Segment("Реквизиты стороны А не относятся к номеру", Anchor("pdf", ("page", 1, 0, 40)), 1),
        Segment("Договор №2025.1", Anchor("pdf", ("page", 2, 0, 15)), 2),
        Segment("Реквизиты стороны Б тоже не относятся", Anchor("pdf", ("page", 3, 0, 38)), 3),
        Segment("Договор №2025.1", Anchor("pdf", ("page", 4, 0, 15)), 4),
    ]
    document = Document("test.pdf", "pdf", segments)
    entities = [
        Entity(EntityType.CONTRACT_NUMBER, "2025.1", order, 8, 14, Source.RULE, 0.9, "2025.1")
        for order in (0, 2, 4)
    ]
    detection = DetectionResult(entities, build_pii_chunks(document.segments, entities))
    profiles = ProfileAgent().profile(document, detection)

    assert profiles.profiles == []
    assert len(profiles.unassigned) == 3

    plan = PlanAgent().plan(document, entities, profiles=profiles.profiles)
    markers = {replacement.marker for replacement in plan.replacements}
    assert markers == {"[ДОГОВОР]"}, markers


def test_open_role_fixture_does_not_need_llm() -> None:
    document = ingest_docx(FIXTURES / "contract_08_roles.docx")
    result = ProfileAgent().profile(document, DetectAgent().detect(document))
    assert {profile.role_title for profile in result.profiles} == {"Заказчик", "Исполнитель"}


def test_critical_never_asked_and_repeated_phone_is_one_question() -> None:
    segment = Segment("ИНН 1; телефон 7; телефон 7; телефон 7", Anchor("docx", ("body", 0)), 0)
    entities = [
        Entity(EntityType.INN, "1", 0, 4, 5, Source.RULE, 0.3, "1"),
        Entity(EntityType.PHONE, "7", 0, 16, 17, Source.NER, 0.5, "7"),
        Entity(EntityType.PHONE, "7", 0, 28, 29, Source.NER, 0.5, "7"),
        Entity(EntityType.PHONE, "7", 0, 40, 41, Source.NER, 0.5, "7"),
    ]
    document = Document("test.docx", "docx", [segment])
    detection = DetectionResult(entities, build_pii_chunks(document.segments, entities))
    profiles = ProfileAgent().profile(document, detection)
    result = JudgeAgent().judge(detection, profiles)
    assert len(result.questions) == 1
    assert len(result.questions[0].refs) == 3
    assert all("E1" not in question.refs for question in result.questions)
    assert result.verdicts[0].action is Action.MASK
    assert all(
        verdict.action is Action.KEEP
        for verdict in JudgeAgent().apply_answers(result, {"Q1": "оставить"})[1:]
    )


@pytest.mark.parametrize("ask_below", [0.0, 0.3, 0.75, 1.0])
def test_critical_type_masked_silently_regardless_of_ask_policy(ask_below: float) -> None:
    """Р8, приёмка: «переключение политики не меняет поведение критичных
    типов» — критичный тип (ИНН, source=NER, confidence=0.1 — заведомо
    ниже любого разумного порога) маскируется молча при любом ``ask_below``,
    от «спрашивать почти всегда» (1.0) до «никогда не спрашивать» (0.0).
    Уровень уверенности (Р8) той же сущности остаётся ``CONFIRMED`` — это
    решает критичность типа, а не порог судьи."""
    segment = Segment("ИНН 7707083893 указан в реквизитах.", Anchor("docx", ("body", 0)), 0)
    weak_inn = Entity(
        EntityType.INN, "7707083893", 0, 4, 14, Source.NER, confidence=0.1, normalized="7707083893"
    )
    entities = [weak_inn]
    document = Document("test.docx", "docx", [segment])
    detection = DetectionResult(entities, build_pii_chunks(document.segments, entities))
    profiles = ProfileAgent().profile(document, detection)

    result = JudgeAgent(ask_below=ask_below).judge(detection, profiles)

    assert result.verdicts[0].action is Action.MASK
    assert result.verdicts[0].question_id == ""
    assert result.questions == []
    assert classify_level(weak_inn, signal_count=1) == ConfidenceLevel.CONFIRMED


def test_judge_handles_llm_candidates_that_are_not_in_detection_index() -> None:
    """Регрессия: ``candidate_refs.get(id(x), index.ref(x))`` вычисляет запасной

    вариант всегда, даже когда ключ найден — ``index.ref`` падает на
    кандидате, которого нет в детекции. Кандидаты (``C*``) — законная ссылка
    вне ``EntityIndex`` (см. ``refs.py``), судья обязан их принимать.
    """
    segment = Segment("Договор № 44/2026", Anchor("docx", ("body", 0)), 0)
    document = Document("test.docx", "docx", [segment])
    entities: list[Entity] = []
    detection = DetectionResult(entities, build_pii_chunks(document.segments, entities))
    profiles = ProfileAgent().profile(document, detection)
    profiles.candidates = [
        Entity(EntityType.CONTRACT_NUMBER, "44/2026", 0, 11, 18, Source.LLM, 0.6, "44/2026")
    ]

    result = JudgeAgent().judge(detection, profiles)

    assert result.verdicts[0].ref == "C1"
