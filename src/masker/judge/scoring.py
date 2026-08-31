"""Единая формула уверенности JudgeAgent."""

from __future__ import annotations

from masker.model import Entity, Profile

ASK_BELOW = 0.75
PROFILE_BONUS = 0.1


def score(entity: Entity, profile: Profile | None) -> float:
    """Поднять уверенность только за счёт устойчивого профиля."""
    bonus = (
        PROFILE_BONUS if profile and profile.confidence >= 0.9 and len(profile.members) > 1 else 0.0
    )
    return min(1.0, entity.confidence + bonus)
