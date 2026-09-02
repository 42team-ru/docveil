from __future__ import annotations

import json
from pathlib import Path

from masker.detect.agent import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.model import Anchor, Document, Entity, EntityType, Segment, Source
from masker.profile.blocks import BlockSpan, ContextBlock, build_context_blocks
from masker.profile.cluster import cluster
from masker.profile.prompt import build_request, parse_response
from masker.refs import EntityIndex

FIXTURES = Path(__file__).parents[3] / "fixtures" / "labeled"


def _document(count: int) -> Document:
    segments = [
        Segment(f"сегмент {number}", Anchor("docx", ("body", number)), number)
        for number in range(count)
    ]
    return Document("test.docx", "docx", segments)


def _entity(segment_order: int) -> Entity:
    return Entity(
        EntityType.ORG_NAME, "ООО «Ромашка»", segment_order, 0, 13, Source.RULE, 0.9, "ромашка"
    )


def _blocks_with_some_entities() -> tuple[Document, list[ContextBlock], EntityIndex]:
    document = _document(10)
    entity_segments = (1, 4, 7)
    entities = [_entity(order) for order in entity_segments]
    blocks = [
        ContextBlock(
            id=f"B{number + 1}",
            spans=[BlockSpan(number, 0, len(document.segments[number].text))],
            entities=[entity for entity in entities if entity.segment_order == number],
            label="",
            heading=f"заголовок {number}",
        )
        for number in range(10)
    ]
    return document, blocks, EntityIndex(entities)


def test_only_blocks_with_entities_go_into_request() -> None:
    document, blocks, index = _blocks_with_some_entities()

    messages = build_request(document, profiles=[], blocks=blocks, index=index)

    assert len(messages) == 1
    payload = json.loads(messages[0][1].content)
    assert len(payload["blocks"]) == 3
    assert {block["id"] for block in payload["blocks"]} == {"B2", "B5", "B8"}


def test_request_is_byte_stable_between_builds() -> None:
    document, blocks, index = _blocks_with_some_entities()

    first = build_request(document, profiles=[], blocks=blocks, index=index)
    second = build_request(document, profiles=[], blocks=blocks, index=index)

    assert [message.content for batch in first for message in batch] == [
        message.content for batch in second for message in batch
    ]


def test_contract_01_stays_one_batch() -> None:
    document = ingest_docx(FIXTURES / "contract_01.docx")
    entities = DetectAgent().detect(document).entities
    index = EntityIndex(entities)
    blocks = build_context_blocks(document.segments, entities)
    profiles = cluster(document, blocks, index)

    messages = build_request(document, profiles, blocks, index)

    assert len(messages) == 1


def test_system_prompt_states_the_task_and_required_fields() -> None:
    document, blocks, index = _blocks_with_some_entities()

    system = build_request(document, profiles=[], blocks=blocks, index=index)[0][0]

    assert system.role == "system"
    # Прежняя инструкция не называла задачу и не требовала confidence, из-за чего
    # модель возвращала запрос дословно обратно.
    assert "роли сторон" in system.content
    assert "обязательное число" in system.content
    assert "role_title там, где он пуст" in system.content


def test_blocks_carry_segment_orders_for_candidates() -> None:
    document, blocks, index = _blocks_with_some_entities()

    payload = json.loads(
        build_request(document, profiles=[], blocks=blocks, index=index)[0][1].content
    )

    assert [block["segments"] for block in payload["blocks"]] == [[1], [4], [7]]


def test_profile_without_confidence_is_rejected_with_diagnostic() -> None:
    decision = parse_response(
        '{"profiles": [{"id": "P1", "role_title": "Продавец", "members": []}]}'
    )

    assert decision.profiles == []
    assert decision.diagnostics == ["LLM не вернула confidence для P1"]


def test_profile_with_confidence_is_parsed() -> None:
    decision = parse_response(
        '{"profiles": [{"id": "P1", "role_title": "Продавец", "confidence": 0.7, "members": []}]}'
    )

    assert [(item.id, item.confidence) for item in decision.profiles] == [("P1", 0.7)]
    assert decision.diagnostics == []
