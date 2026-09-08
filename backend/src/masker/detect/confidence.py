"""Три уровня уверенности детекции — режим «мазать всё» (Р8, TASKS.md).

Заказчик хочет recall → 1.0 на открытом классе (org_name/person), и это
достигается не лучшим детектором, а сменой политики: маскируется всё, но
человеку видно, насколько детектор уверен в каждой маске — это и есть
``ConfidenceLevel``. Асимметрия: снять лишнюю маску — один клик, найти
пропущенную — перечитать весь документ. Поэтому ниже нет ветки «не
маскировать»: классификатор только выбирает, как замена будет показана в
отчёте.

Уровень не влияет на решение критичных типов — они настолько же молча
маскируются вне зависимости от уровня уверенности (``CRITICAL_TYPES``
всегда ``CONFIRMED``, см. ``classify_level``).
"""

from __future__ import annotations

from masker.detect.resolve import is_validated
from masker.detect.whitelist import is_whitelisted
from masker.entity_types import EntityTypeRegistry
from masker.model import ConfidenceLevel, Entity, EntityType, is_critical

#: Единственные типы, где вообще возможен уровень ``POSSIBLE`` — заглавное
#: имя собственное без формального признака (контрольной суммы, формата).
#: Числовые/форматные типы (телефон, email, дата) не бывают «похоже на
#: имя» — они либо совпали с форматом (``PROBABLE``), либо нет.
OPEN_CLASS_TYPES: frozenset[str] = frozenset({EntityType.ORG_NAME, EntityType.PERSON})

#: Порог согласия независимых детекторов для ``CONFIRMED`` без контрольной
#: суммы — «два разных детектора нашли пересекающиеся спаны» из TASKS.md.
MIN_CONFIRMING_SIGNALS = 2


def _is_capitalized_proper_noun(text: str) -> bool:
    """Похоже ли значение на имя собственное: каждое буквенное слово — с большой буквы."""
    tokens = [token for token in text.split() if token]
    if not tokens:
        return False
    alpha_tokens = [token for token in tokens if any(char.isalpha() for char in token)]
    if not alpha_tokens:
        return False
    return all(token[0].isupper() for token in alpha_tokens)


def classify_level(
    entity: Entity,
    *,
    signal_count: int = 1,
    registry: EntityTypeRegistry | None = None,
) -> ConfidenceLevel:
    """Определить уровень уверенности одной сущности (Р8).

    ``signal_count`` — сколько независимых детекторов нашли пересекающийся
    спан до разрешения перекрытий (см. ``DetectAgent.detect``); по
    умолчанию 1 — сущность, собранная в обход детектора (тест, кандидат
    профиля), считается найденной одним источником.

    Критичный тип (``registry`` или встроенный ``CRITICAL_TYPES``) — всегда
    ``CONFIRMED``: судья не спрашивает про критичное ни при какой политике,
    и уровень уверенности этого правила не отменяет (инвариант AGENTS.md).
    """
    critical = (
        registry.is_critical(entity.type) if registry is not None else is_critical(entity.type)
    )
    if critical:
        return ConfidenceLevel.CONFIRMED
    if is_validated(entity):
        return ConfidenceLevel.CONFIRMED
    if signal_count >= MIN_CONFIRMING_SIGNALS:
        return ConfidenceLevel.CONFIRMED
    if (
        entity.type in OPEN_CLASS_TYPES
        and _is_capitalized_proper_noun(entity.text)
        and not is_whitelisted(entity.text)
    ):
        return ConfidenceLevel.POSSIBLE
    return ConfidenceLevel.PROBABLE
