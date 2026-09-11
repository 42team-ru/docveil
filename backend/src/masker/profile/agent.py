"""ProfileAgent: структура сначала, LLM уточняет только допустимые поля."""

from __future__ import annotations

from dataclasses import dataclass, field

from masker.detect.result import DetectionResult
from masker.llm import LLMError, LLMProvider
from masker.llm.trace import ProfileOutcome
from masker.model import Anchor, Document, Entity, EntityType, Profile, Source
from masker.profile.blocks import ContextBlock, build_context_blocks
from masker.profile.candidates import build_candidates
from masker.profile.cluster import cluster
from masker.profile.labels import marker_label, role_title, slugify
from masker.profile.prompt import (
    MIN_LLM_ROLE_CONFIDENCE,
    ROLE_RESPONSE_SCHEMA,
    build_request,
    parse_response,
    valid_decision,
)
from masker.refs import EntityIndex

#: Типы, которые не принадлежат ни одной стороне договора — факт о самом
#: документе, не о субъекте (план T2.2.1, шаг 10, найдено на реальном PDF:
#: до появления детектора `contract_number` этот путь был непроверен).
#: Такие сущности не идут в блоки/кластеризацию вовсе — иначе номер
#: договора, повторённый в футере без контекста стороны на каждой
#: странице, получает на каждом вхождении свой синтетический профиль
#: («СТОРОНА-N» либо метка, унаследованная из соседнего раздела) и,
#: следовательно, свой маркер — нарушение согласованности псевдонимов
#: (AGENTS.md): одно и то же значение обязано получать один и тот же
#: маркер по всему документу. Оставленные без профиля, они попадают в
#: ``unassigned`` и получают общий маркер через ``mask/keys.py::group_key``
#: наравне с любой другой непрофилированной сущностью.
#: `date` — тоже документ-уровневый: дата подписания, срок оплаты, срок
#: поставки не принадлежат ни одной стороне. `birth_date` — исключение: она
#: принадлежит конкретному субъекту и обязана получить `[ПРОДАВЕЦ-РОЖДЕНИЕ]`
#: (план T1.15, раздел «Два типа»), поэтому в этот список не входит.
_DOCUMENT_LEVEL_TYPES = frozenset(
    {
        EntityType.CONTRACT_NUMBER,
        EntityType.DATE,
        EntityType.REGISTRY_KEY,
        EntityType.POWER_OF_ATTORNEY_NUMBER,
        EntityType.IP_ADDRESS,
    }
)


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
        profilable = [
            entity for entity in detection.entities if entity.type not in _DOCUMENT_LEVEL_TYPES
        ]
        blocks = build_context_blocks(document.segments, profilable)
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
        open_profiles = [
            profile
            for profile in profiles
            if not profile.role_title or profile.role_confidence < MIN_LLM_ROLE_CONFIDENCE
        ]
        if not open_profiles:
            return result
        raw_candidates: list[dict[str, object]] = []
        messages = build_request(document, open_profiles, index)
        try:
            response = self._llm.complete(messages, schema=ROLE_RESPONSE_SCHEMA)
        except LLMError as error:
            result.diagnostics.append(f"LLM недоступна: {error}")
            return result
        parsed = parse_response(response)
        decision = valid_decision(parsed, open_profiles, index)
        result.llm_calls += 1
        result.diagnostics.extend(decision.diagnostics)
        raw_candidates.extend(decision.candidates)
        by_id = {profile.id: profile for profile in profiles}
        valid_ids = {proposal.id for proposal in decision.profiles}
        outcomes: list[ProfileOutcome] = []
        # Профили, отсеянные valid_decision (неизвестный id, неизвестная
        # сущность, попытка сменить состав), иначе теряются молча.
        for proposal in parsed.profiles:
            if proposal.id in valid_ids:
                continue
            rejected = by_id.get(proposal.id)
            outcomes.append(
                ProfileOutcome(
                    profile_id=proposal.id,
                    outcome="rejected_by_validation",
                    old_role_title=rejected.role_title if rejected else "",
                    new_role_title=proposal.role_title,
                    old_confidence=rejected.role_confidence if rejected else 0.0,
                    new_confidence=proposal.confidence,
                    reason=_validation_reason(decision.diagnostics, proposal.id),
                )
            )
        for proposed in decision.profiles:
            profile = by_id[proposed.id]
            if not proposed.role_title:
                outcomes.append(
                    ProfileOutcome(
                        profile_id=profile.id,
                        outcome="empty_role",
                        old_role_title=profile.role_title,
                        new_role_title="",
                        old_confidence=profile.role_confidence,
                        new_confidence=proposed.confidence,
                    )
                )
                continue
            if proposed.confidence < MIN_LLM_ROLE_CONFIDENCE:
                outcomes.append(
                    ProfileOutcome(
                        profile_id=profile.id,
                        outcome="confidence_below_threshold",
                        old_role_title=profile.role_title,
                        new_role_title=proposed.role_title,
                        old_confidence=profile.role_confidence,
                        new_confidence=proposed.confidence,
                    )
                )
                continue
            # Структурная роль надёжнее модели ровно тогда, когда сама модель
            # не увереннее структуры: LLM не должна тихо подменять или
            # понижать роль, в которую уже есть основания верить сильнее.
            if proposed.confidence <= profile.role_confidence:
                outcomes.append(
                    ProfileOutcome(
                        profile_id=profile.id,
                        outcome="confidence_not_higher",
                        old_role_title=profile.role_title,
                        new_role_title=proposed.role_title,
                        old_confidence=profile.role_confidence,
                        new_confidence=proposed.confidence,
                    )
                )
                continue
            old_role_title = profile.role_title
            old_confidence = profile.role_confidence
            new_role_title = role_title(proposed.role_title)
            profile.role_title = new_role_title
            profile.role_id = slugify(proposed.role_title)
            profile.marker_label = marker_label(proposed.role_title)
            profile.role_confidence = proposed.confidence
            profile.source = Source.LLM
            profile.evidence.append(
                f"LLM: роль «{new_role_title}» с уверенностью {proposed.confidence:.1f}"
            )
            outcomes.append(
                ProfileOutcome(
                    profile_id=profile.id,
                    outcome="applied",
                    old_role_title=old_role_title,
                    new_role_title=new_role_title,
                    old_confidence=old_confidence,
                    new_confidence=proposed.confidence,
                )
            )
        recorder = getattr(self._llm, "record_batch", None)
        calls = getattr(self._llm, "calls", ())
        if callable(recorder) and isinstance(calls, list) and calls:
            recorder(
                call_index=calls[-1].index,
                proposed_profiles=len(parsed.profiles),
                valid_profiles=len(decision.profiles),
                outcomes=outcomes,
                diagnostics=list(decision.diagnostics),
            )
        result.candidates = build_candidates(raw_candidates, document.segments, detection.entities)
        return result


def _validation_reason(diagnostics: list[str], profile_id: str) -> str:
    """Найти диагностику valid_decision, относящуюся к отклонённому профилю."""
    for diagnostic in diagnostics:
        if diagnostic.rsplit(" ", 1)[-1] == profile_id:
            return diagnostic
    return "профиль отклонён валидацией"
