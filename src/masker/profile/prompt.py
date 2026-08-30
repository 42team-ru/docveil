"""Детерминированный запрос к LLM и строгий разбор его ответа."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from masker.llm import Message
from masker.model import Document, Profile
from masker.profile.blocks import ContextBlock, block_text
from masker.refs import EntityIndex

LLM_BATCH_CHARS = 6000


@dataclass(slots=True)
class DecisionProfile:
    id: str
    role_title: str
    confidence: float
    members: list[str]


@dataclass(slots=True)
class Decision:
    profiles: list[DecisionProfile] = field(default_factory=list)
    candidates: list[dict[str, object]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def build_request(
    document: Document, profiles: list[Profile], blocks: list[ContextBlock], index: EntityIndex
) -> list[list[Message]]:
    """Собрать стабильные пачки запроса, разделяя только по объёму текста."""
    payload = {
        "entities": [
            {
                "ref": ref,
                "type": index.entity(ref).type.value,
                "text": index.entity(ref).text,
                "segment_order": index.entity(ref).segment_order,
            }
            for ref in index.refs()
        ],
        "profiles": [
            {
                "id": profile.id,
                "role_title": profile.role_title,
                "members": [member.ref for member in profile.members],
            }
            for profile in profiles
        ],
    }
    chunks = [
        {
            "id": block.id,
            "label": block.label,
            "heading": block.heading,
            "text": block_text(document.segments, block),
        }
        # Модели нечего решать по блокам без сущностей — отправка всего
        # документа стоит лишних денег и лишний раз выносит текст наружу.
        for block in blocks
        if block.entities
    ]
    batches: list[list[dict[str, str]]] = [[]]
    length = 0
    for chunk in chunks:
        text_length = len(chunk["text"])
        if batches[-1] and length + text_length > LLM_BATCH_CHARS:
            batches.append([])
            length = 0
        batches[-1].append(chunk)
        length += text_length
    messages: list[list[Message]] = []
    for batch in batches:
        request = {**payload, "blocks": batch}
        messages.append(
            [
                Message(
                    "system", "Верни только JSON с profiles и candidates; не меняй спаны сущностей."
                ),
                Message(
                    "user",
                    json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                ),
            ]
        )
    return messages


def parse_response(raw: str) -> Decision:
    """Безопасно разобрать ответ модели; испорченный ответ не прерывает обработку."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return Decision(diagnostics=["LLM вернула невалидный JSON"])
    if not isinstance(parsed, dict):
        return Decision(diagnostics=["LLM вернула JSON не-объект"])
    profiles: list[DecisionProfile] = []
    diagnostics: list[str] = []
    for item in parsed.get("profiles", []):
        if not isinstance(item, dict):
            diagnostics.append("некорректный профиль LLM")
            continue
        try:
            profiles.append(
                DecisionProfile(
                    id=str(item["id"]),
                    role_title=str(item.get("role_title", "")),
                    confidence=max(0.0, min(1.0, float(item.get("confidence", 0.0)))),
                    members=[str(ref) for ref in item.get("members", [])],
                )
            )
        except (KeyError, TypeError, ValueError):
            diagnostics.append("некорректные поля профиля LLM")
    candidates = [item for item in parsed.get("candidates", []) if isinstance(item, dict)]
    return Decision(profiles=profiles, candidates=candidates, diagnostics=diagnostics)


def valid_decision(decision: Decision, profiles: list[Profile], index: EntityIndex) -> Decision:
    """Отклонить изменения состава профилей, неизвестные ссылки и опасные слияния."""
    existing = {profile.id: {member.ref for member in profile.members} for profile in profiles}
    valid: list[DecisionProfile] = []
    diagnostics = list(decision.diagnostics)
    for proposal in decision.profiles:
        if proposal.id not in existing:
            diagnostics.append(f"LLM указала неизвестный профиль {proposal.id}")
            continue
        proposed = set(proposal.members)
        if not proposed <= set(index.refs()):
            diagnostics.append(f"LLM указала неизвестную сущность в {proposal.id}")
            continue
        # На этой стадии все детектированные сущности уже структурно назначены.
        # Поэтому изменение состава является и потерей, и потенциальным опасным слиянием.
        if proposed != existing[proposal.id]:
            diagnostics.append(f"LLM попыталась изменить состав {proposal.id}")
            continue
        valid.append(proposal)
    return Decision(profiles=valid, candidates=decision.candidates, diagnostics=diagnostics)
