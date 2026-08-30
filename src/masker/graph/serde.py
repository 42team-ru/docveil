"""Явная сериализация датаклассов в состояние чекпойнтера."""

from __future__ import annotations

from typing import Any

from masker.judge.agent import JudgeResult
from masker.model import (
    Action,
    Anchor,
    Entity,
    EntityType,
    Profile,
    ProfileMember,
    Question,
    Source,
    Verdict,
)


def anchor_to_dict(anchor: Anchor) -> dict[str, Any]:
    return {"fmt": anchor.fmt, "locator": list(anchor.locator), "label": anchor.label}


def anchor_from_dict(data: dict[str, Any]) -> Anchor:
    return Anchor(str(data["fmt"]), tuple(data["locator"]), str(data.get("label", "")))


def entity_to_dict(entity: Entity) -> dict[str, Any]:
    return {
        "type": entity.type.value,
        "text": entity.text,
        "segment_order": entity.segment_order,
        "start": entity.start,
        "end": entity.end,
        "source": entity.source.value,
        "confidence": entity.confidence,
        "normalized": entity.normalized,
    }


def entity_from_dict(data: dict[str, Any]) -> Entity:
    return Entity(
        EntityType(str(data["type"])),
        str(data["text"]),
        int(data["segment_order"]),
        int(data["start"]),
        int(data["end"]),
        Source(str(data["source"])),
        float(data.get("confidence", 1.0)),
        str(data.get("normalized", "")),
    )


def profiles_to_dicts(profiles: list[Profile]) -> list[dict[str, Any]]:
    return [
        {
            "id": profile.id,
            "members": [
                {
                    "entity": entity_to_dict(member.entity),
                    "anchor": anchor_to_dict(member.anchor),
                    "ref": member.ref,
                }
                for member in profile.members
            ],
            "role_id": profile.role_id,
            "role_title": profile.role_title,
            "marker_label": profile.marker_label,
            "confidence": profile.confidence,
            "role_confidence": profile.role_confidence,
            "source": profile.source.value,
            "evidence": profile.evidence,
        }
        for profile in profiles
    ]


def profiles_from_dicts(items: list[dict[str, Any]]) -> list[Profile]:
    return [
        Profile(
            id=str(item["id"]),
            members=[
                ProfileMember(
                    entity_from_dict(member["entity"]),
                    anchor_from_dict(member["anchor"]),
                    str(member["ref"]),
                )
                for member in item["members"]
            ],
            role_id=str(item.get("role_id", "")),
            role_title=str(item.get("role_title", "")),
            marker_label=str(item.get("marker_label", "")),
            confidence=float(item.get("confidence", 0.0)),
            role_confidence=float(item.get("role_confidence", 0.0)),
            source=Source(str(item.get("source", "rule"))),
            evidence=[str(value) for value in item.get("evidence", [])],
        )
        for item in items
    ]


def verdicts_to_dicts(verdicts: list[Verdict]) -> list[dict[str, Any]]:
    return [
        {
            "ref": item.ref,
            "action": item.action.value,
            "confidence": item.confidence,
            "reason": item.reason,
            "profile_id": item.profile_id,
            "question_id": item.question_id,
        }
        for item in verdicts
    ]


def verdicts_from_dicts(items: list[dict[str, Any]]) -> list[Verdict]:
    return [
        Verdict(
            str(item["ref"]),
            Action(str(item["action"])),
            float(item["confidence"]),
            str(item["reason"]),
            str(item.get("profile_id", "")),
            str(item.get("question_id", "")),
        )
        for item in items
    ]


def questions_to_dicts(questions: list[Question]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "key": item.key,
            "prompt": item.prompt,
            "options": list(item.options),
            "default": item.default,
            "refs": list(item.refs),
            "anchors": [anchor_to_dict(anchor) for anchor in item.anchors],
        }
        for item in questions
    ]


def questions_from_dicts(items: list[dict[str, Any]]) -> list[Question]:
    return [
        Question(
            str(item["id"]),
            str(item["kind"]),
            str(item["key"]),
            str(item["prompt"]),
            tuple(str(value) for value in item["options"]),
            str(item["default"]),
            tuple(str(value) for value in item["refs"]),
            tuple(anchor_from_dict(anchor) for anchor in item["anchors"]),
        )
        for item in items
    ]


def judge_to_dicts(result: JudgeResult) -> dict[str, list[dict[str, Any]]]:
    return {
        "verdicts": verdicts_to_dicts(result.verdicts),
        "questions": questions_to_dicts(result.questions),
    }
