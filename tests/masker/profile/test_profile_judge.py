from pathlib import Path

from masker.detect.agent import DetectAgent
from masker.detect.result import DetectionResult, build_pii_chunks
from masker.ingest.docx_ingest import ingest_docx
from masker.judge import JudgeAgent
from masker.model import Action, Anchor, Document, Entity, EntityType, Segment, Source
from masker.profile import ProfileAgent

FIXTURES = Path(__file__).parents[3] / "fixtures" / "labeled"


def test_contract_profiles_are_two_open_roles() -> None:
    document = ingest_docx(FIXTURES / "contract_01.docx")
    result = ProfileAgent().profile(document, DetectAgent().detect(document))
    assert [(profile.role_title, len(profile.members)) for profile in result.profiles] == [
        ("Поставщик", 11),
        ("Покупатель", 8),
    ]


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
