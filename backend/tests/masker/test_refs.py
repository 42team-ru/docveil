from pathlib import Path

from masker.detect.agent import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.refs import EntityIndex

FIXTURES = Path(__file__).parents[2] / "fixtures" / "labeled"


def test_entity_refs_are_stable_for_reordered_input() -> None:
    entities = DetectAgent().detect(ingest_docx(FIXTURES / "contract_01.docx")).entities
    first = EntityIndex(entities)
    second = EntityIndex(list(reversed(entities)))
    # 21 сущность после T1.15: добавилась «15 января 2026» как `date`.
    assert first.refs() == [f"E{number}" for number in range(1, 22)]
    assert [second.ref(entity) for entity in entities] == [first.ref(entity) for entity in entities]
    assert all(first.entity(first.ref(entity)) is entity for entity in entities)
