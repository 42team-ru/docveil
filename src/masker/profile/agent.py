"""ProfileAgent: структура сначала, LLM уточняет только допустимые поля."""

from __future__ import annotations

from dataclasses import dataclass, field

from masker.detect.result import DetectionResult
from masker.llm import LLMError, LLMProvider
from masker.model import Anchor, Document, Entity, Profile, Source
from masker.profile.blocks import ContextBlock, build_context_blocks
from masker.profile.candidates import build_candidates
from masker.profile.cluster import cluster
from masker.profile.labels import marker_label, role_title, slugify
from masker.profile.prompt import build_request, parse_response, valid_decision
from masker.refs import EntityIndex


@dataclass(slots=True)
class ProfileResult:
    profiles: list[Profile]
    blocks: list[ContextBlock]
    unassigned: list[str]
    candidates: list[Entity]
    anchors: dict[int, Anchor] = field(default_factory=dict)
    llm_calls: int = 0
    diagnostics: list[str] = field(default_factory=list)


class ProfileAgent:
    """Группирует сущности и при наличии LLM уточняет открытые названия ролей."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self._llm = llm

    def profile(self, document: Document, detection: DetectionResult) -> ProfileResult:
        """Вернуть профильный результат, не меняя ``detection``."""
        index = EntityIndex(detection.entities)
        blocks = build_context_blocks(document.segments, detection.entities)
        profiles = cluster(document, blocks, index)
        assigned = {member.ref for profile in profiles for member in profile.members}
        result = ProfileResult(
            profiles=profiles,
            blocks=blocks,
            unassigned=[ref for ref in index.refs() if ref not in assigned],
            candidates=[],
            anchors={segment.order: segment.anchor for segment in document.segments},
        )
        if self._llm is None:
            return result
        raw_candidates: list[dict[str, object]] = []
        for messages in build_request(document, profiles, blocks, index):
            try:
                decision = valid_decision(
                    parse_response(self._llm.complete(messages)), profiles, index
                )
            except LLMError as error:
                result.diagnostics.append(f"LLM недоступна: {error}")
                continue
            result.llm_calls += 1
            result.diagnostics.extend(decision.diagnostics)
            raw_candidates.extend(decision.candidates)
            by_id = {profile.id: profile for profile in profiles}
            for proposed in decision.profiles:
                profile = by_id[proposed.id]
                if not proposed.role_title:
                    continue
                # Структурная роль надёжнее модели ровно тогда, когда сама модель
                # не увереннее структуры: LLM не должна тихо подменять или
                # понижать роль, в которую уже есть основания верить сильнее.
                if proposed.confidence <= profile.role_confidence:
                    continue
                new_role_title = role_title(proposed.role_title)
                profile.role_title = new_role_title
                profile.role_id = slugify(proposed.role_title)
                profile.marker_label = marker_label(proposed.role_title)
                profile.role_confidence = proposed.confidence
                profile.source = Source.LLM
                profile.evidence.append(
                    f"LLM: роль «{new_role_title}» с уверенностью {proposed.confidence:.1f}"
                )
        result.candidates = build_candidates(raw_candidates, document.segments, detection.entities)
        return result
