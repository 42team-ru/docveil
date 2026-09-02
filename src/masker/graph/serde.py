"""Явная сериализация датаклассов в состояние чекпойнтера."""

from __future__ import annotations

from typing import Any

from masker.judge.agent import JudgeResult
from masker.model import (
    Action,
    Anchor,
    Decision,
    Entity,
    MaskGroup,
    MaskPlan,
    PolicyQuestion,
    Profile,
    ProfileMember,
    Question,
    Replacement,
    SkippedRef,
    Source,
    Verdict,
)


def anchor_to_dict(anchor: Anchor) -> dict[str, Any]:
    return {"fmt": anchor.fmt, "locator": list(anchor.locator), "label": anchor.label}


def anchor_from_dict(data: dict[str, Any]) -> Anchor:
    return Anchor(str(data["fmt"]), tuple(data["locator"]), str(data.get("label", "")))


def entity_to_dict(entity: Entity) -> dict[str, Any]:
    return {
        "type": entity.type,
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
        str(data["type"]),
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


def policy_questions_to_dicts(questions: list[PolicyQuestion]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "target": item.target,
            "title": item.title,
            "prompt": item.prompt,
            "options": list(item.options),
            "default": item.default,
            "critical": item.critical,
            "found": item.found,
            "by_type": [[key, count] for key, count in item.by_type],
            "samples": list(item.samples),
            "anchors": [anchor_to_dict(anchor) for anchor in item.anchors],
            "linked": list(item.linked),
            "role_title": item.role_title,
        }
        for item in questions
    ]


def policy_questions_from_dicts(items: list[dict[str, Any]]) -> list[PolicyQuestion]:
    return [
        PolicyQuestion(
            id=str(item["id"]),
            kind=str(item["kind"]),
            target=str(item["target"]),
            title=str(item["title"]),
            prompt=str(item["prompt"]),
            options=tuple(str(value) for value in item["options"]),
            default=str(item["default"]),
            critical=bool(item["critical"]),
            found=int(item["found"]),
            by_type=tuple((str(key), int(count)) for key, count in item.get("by_type", [])),
            samples=tuple(str(value) for value in item.get("samples", [])),
            anchors=tuple(anchor_from_dict(anchor) for anchor in item.get("anchors", [])),
            linked=tuple(str(value) for value in item.get("linked", [])),
            role_title=str(item.get("role_title", "")),
        )
        for item in items
    ]


def _decision_to_dict(decision: Decision) -> dict[str, Any]:
    return {
        "action": decision.action.value,
        "decided_by": decision.decided_by,
        "question_id": decision.question_id,
        "reason": decision.reason,
    }


def _decision_from_dict(ref: str, item: dict[str, Any]) -> Decision:
    return Decision(
        ref,
        Action(str(item["action"])),
        str(item["decided_by"]),
        str(item.get("question_id", "")),
        str(item.get("reason", "")),
    )


def decisions_to_dicts(
    decisions: list[Decision], overridden: dict[str, list[Decision]]
) -> list[dict[str, Any]]:
    """Одна запись на ``ref``: победившее решение плюс проигравшие (``overridden``).

    Единица решения — ссылка на сущность, не тип и не профиль — раздел 4
    плана T1.5.1: групповые ответы уже развёрнуты в ``PolicyAgent.apply``,
    здесь остаётся только сериализовать итог по каждой ссылке.
    """
    return [
        {
            "ref": decision.ref,
            **_decision_to_dict(decision),
            "overridden": [_decision_to_dict(item) for item in overridden.get(decision.ref, [])],
        }
        for decision in decisions
    ]


def decisions_from_dicts(
    items: list[dict[str, Any]],
) -> tuple[list[Decision], dict[str, list[Decision]]]:
    decisions: list[Decision] = []
    overridden: dict[str, list[Decision]] = {}
    for item in items:
        ref = str(item["ref"])
        decisions.append(_decision_from_dict(ref, item))
        overridden[ref] = [_decision_from_dict(ref, entry) for entry in item.get("overridden", [])]
    return decisions, overridden


def _replacement_to_dict(item: Replacement) -> dict[str, Any]:
    return {
        "ref": item.ref,
        "entity": entity_to_dict(item.entity),
        "marker": item.marker,
        "group_id": item.group_id,
        "profile_id": item.profile_id,
        "anchor": anchor_to_dict(item.anchor),
    }


def _replacement_from_dict(data: dict[str, Any]) -> Replacement:
    return Replacement(
        ref=str(data["ref"]),
        entity=entity_from_dict(data["entity"]),
        marker=str(data["marker"]),
        group_id=str(data["group_id"]),
        profile_id=str(data["profile_id"]),
        anchor=anchor_from_dict(data["anchor"]),
    )


def _mask_group_to_dict(item: MaskGroup) -> dict[str, Any]:
    return {
        "id": item.id,
        "key": item.key,
        "type": item.type,
        "marker": item.marker,
        "profile_id": item.profile_id,
        "role_label": item.role_label,
        "number": item.number,
        "refs": list(item.refs),
        "sample": item.sample,
    }


def _mask_group_from_dict(data: dict[str, Any]) -> MaskGroup:
    return MaskGroup(
        id=str(data["id"]),
        key=str(data["key"]),
        type=str(data["type"]),
        marker=str(data["marker"]),
        profile_id=str(data["profile_id"]),
        role_label=str(data["role_label"]),
        number=int(data["number"]),
        refs=tuple(str(value) for value in data["refs"]),
        sample=str(data["sample"]),
    )


def _skipped_ref_to_dict(item: SkippedRef) -> dict[str, Any]:
    return {"ref": item.ref, "type": item.type, "reason": item.reason}


def _skipped_ref_from_dict(data: dict[str, Any]) -> SkippedRef:
    return SkippedRef(
        ref=str(data["ref"]), type=str(data["type"]), reason=str(data["reason"])
    )


def plan_to_dict(plan: MaskPlan) -> dict[str, Any]:
    """Сериализовать ``MaskPlan`` в состояние чекпойнтера (T1.10, шаг 4)."""
    return {
        "replacements": [_replacement_to_dict(item) for item in plan.replacements],
        "groups": [_mask_group_to_dict(item) for item in plan.groups],
        "skipped": [_skipped_ref_to_dict(item) for item in plan.skipped],
        "requested_types": list(plan.requested_types),
    }


def plan_from_dict(data: dict[str, Any]) -> MaskPlan:
    """Восстановить ``MaskPlan`` из состояния чекпойнтера (обратно ``plan_to_dict``)."""
    return MaskPlan(
        replacements=tuple(_replacement_from_dict(item) for item in data.get("replacements", [])),
        groups=tuple(_mask_group_from_dict(item) for item in data.get("groups", [])),
        skipped=tuple(_skipped_ref_from_dict(item) for item in data.get("skipped", [])),
        requested_types=tuple(str(value) for value in data.get("requested_types", [])),
    )
