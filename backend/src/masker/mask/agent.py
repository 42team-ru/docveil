"""`PlanAgent` — сущность + профиль + решение → согласованный маркер.

Ядро T1.6: превращает список найденных сущностей в `MaskPlan`, где одно и
то же значение (в любом написании) получает один и тот же маркер во всём
документе. Алгоритм детерминированный и не бросает исключений — все
особые случаи (тип не запрошен, решение «оставить», сегмент без якоря)
оседают в `MaskPlan.skipped`, а не роняют прогон.
"""

from __future__ import annotations

from collections.abc import Mapping

from masker.entity_types import EntityTypeRegistry
from masker.mask.keys import group_key
from masker.mask.labels import assign_compact_labels, compose_marker, type_marker_label
from masker.model import (
    Action,
    Anchor,
    Document,
    Entity,
    MaskGroup,
    MaskPlan,
    Profile,
    Replacement,
    SkippedRef,
)
from masker.refs import EntityIndex, entity_sort_key

#: Ключ бакета группы: значение (нормализованное) + профиль, которому оно
#: принадлежит. Профиль входит в ключ, иначе один и тот же ИНН, встреченный
#: у двух разных сторон документа (редкая, но возможная опечатка/совпадение),
#: получил бы маркер только одной из них — см. раздел «Алгоритм» плана T1.6.
_BucketKey = tuple[str, str]
#: Ключ пары, внутри которой ведётся нумерация маркеров: роль стороны + тип
#: сущности. `[ПОСТАВЩИК-ФИО-1]`/`[ПОСТАВЩИК-ФИО-2]` нумеруются в одной паре,
#: `[ПОСТАВЩИК-ИНН]` — в другой.
_PairKey = tuple[str, str]  # (role_label, entity_type_id)


class _PendingEntity:
    """Сущность, прошедшая фильтры и готовая к группировке."""

    __slots__ = ("anchor", "bucket", "entity", "profile_id", "ref")

    def __init__(self, ref: str, entity: Entity, profile_id: str, anchor: Anchor) -> None:
        self.ref = ref
        self.entity = entity
        self.profile_id = profile_id
        self.anchor = anchor
        self.bucket: _BucketKey = (group_key(entity), profile_id)


class PlanAgent:
    """Строит `MaskPlan` — единственный источник маркеров для рендера и отчёта."""

    def __init__(self, registry: EntityTypeRegistry | None = None) -> None:
        self._registry = registry or EntityTypeRegistry.builtin()

    def plan(
        self,
        document: Document,
        entities: list[Entity],
        *,
        profiles: list[Profile] | None = None,
        requested_types: frozenset[str] | None = None,
        actions: Mapping[str, Action] | None = None,
    ) -> MaskPlan:
        """Построить план по документу, найденным сущностям и решениям.

        ``actions=None`` — маскировать всё найденное (путь простого CLI без
        ``--profile``). ``profiles=None`` — маркеры без ролевого префикса.
        ``requested_types=None`` — все типы: сущность не может быть отфильтрована
        по типу, но всё ещё может быть исключена решением ``actions``.
        """
        index = EntityIndex(entities)
        anchors_by_order = {segment.order: segment.anchor for segment in document.segments}
        role_label_by_profile_id, profile_id_by_ref = _profile_lookup(profiles)
        ordered = sorted(entities, key=entity_sort_key)

        skipped: list[SkippedRef] = []
        pending: list[_PendingEntity] = []
        for entity in ordered:
            ref = index.ref(entity)
            if requested_types is not None and entity.type not in requested_types:
                skipped.append(SkippedRef(ref=ref, type=entity.type, reason="type_not_requested"))
                continue
            if actions is not None and actions.get(ref, Action.MASK) is not Action.MASK:
                skipped.append(SkippedRef(ref=ref, type=entity.type, reason="kept"))
                continue
            anchor = anchors_by_order.get(entity.segment_order)
            if anchor is None:
                skipped.append(SkippedRef(ref=ref, type=entity.type, reason="no_anchor"))
                continue
            profile_id = profile_id_by_ref.get(ref, "")
            pending.append(_PendingEntity(ref, entity, profile_id, anchor))

        buckets = _bucket_by_first_occurrence(pending)
        marker_by_bucket, number_by_bucket = _assign_markers(
            buckets, role_label_by_profile_id, self._registry
        )
        # Компактная метка (план М1) нумеруется сквозным счётчиком по типу
        # для всего документа, а не по паре (роль, тип) — иначе два профиля
        # с разными ролями схлопнутся в одинаковый `[Ф1]` (обе пары
        # начинают свой номер с 1). Порядок — порядок вставки `buckets`,
        # то есть порядок первого появления в тексте (детерминизм).
        compact_label_by_bucket = assign_compact_labels(
            [(bucket, items[0].entity.type) for bucket, items in buckets.items()],
            self._registry,
        )

        groups: list[MaskGroup] = []
        group_id_by_bucket: dict[_BucketKey, str] = {}
        for position, (bucket, items) in enumerate(buckets.items(), start=1):
            group_id = f"G{position}"
            group_id_by_bucket[bucket] = group_id
            first = items[0]
            groups.append(
                MaskGroup(
                    id=group_id,
                    key=bucket[0],
                    type=first.entity.type,
                    marker=marker_by_bucket[bucket],
                    profile_id=first.profile_id,
                    role_label=role_label_by_profile_id.get(first.profile_id, ""),
                    number=number_by_bucket[bucket],
                    refs=tuple(item.ref for item in items),
                    sample=first.entity.text,
                    canonical_label=marker_by_bucket[bucket],
                    compact_label=compact_label_by_bucket[bucket],
                )
            )

        replacements = tuple(
            Replacement(
                ref=item.ref,
                entity=item.entity,
                marker=marker_by_bucket[item.bucket],
                group_id=group_id_by_bucket[item.bucket],
                profile_id=item.profile_id,
                anchor=item.anchor,
            )
            for item in pending
        )

        effective_types: frozenset[str] = (
            requested_types if requested_types is not None else frozenset(self._registry.ids())
        )
        return MaskPlan(
            replacements=replacements,
            groups=tuple(groups),
            skipped=tuple(skipped),
            requested_types=tuple(sorted(effective_types)),
        )


def _profile_lookup(
    profiles: list[Profile] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Вернуть (роль по id профиля, id профиля по ref сущности)."""
    role_label_by_profile_id: dict[str, str] = {}
    profile_id_by_ref: dict[str, str] = {}
    if not profiles:
        return role_label_by_profile_id, profile_id_by_ref
    for profile in profiles:
        role_label_by_profile_id[profile.id] = profile.marker_label
        for member in profile.members:
            profile_id_by_ref[member.ref] = profile.id
    return role_label_by_profile_id, profile_id_by_ref


def _bucket_by_first_occurrence(
    pending: list[_PendingEntity],
) -> dict[_BucketKey, list[_PendingEntity]]:
    """Сгруппировать сущности по бакету в порядке первого вхождения в тексте.

    ``pending`` уже отсортирован по ``entity_sort_key`` вызывающим кодом,
    поэтому порядок ключей словаря (Python гарантирует порядок вставки)
    равен порядку первого появления группы в документе — без сортировки по
    хэшу и без зависимости от порядка входного списка сущностей.
    """
    buckets: dict[_BucketKey, list[_PendingEntity]] = {}
    for item in pending:
        buckets.setdefault(item.bucket, []).append(item)
    return buckets


def _assign_markers(
    buckets: dict[_BucketKey, list[_PendingEntity]],
    role_label_by_profile_id: dict[str, str],
    registry: EntityTypeRegistry,
) -> tuple[dict[_BucketKey, str], dict[_BucketKey, int]]:
    """Пронумеровать группы внутри пары (роль, тип) и собрать маркеры.

    Суффикс ``-N`` есть либо у всех групп пары, либо ни у одной: если внутри
    ``(role_label, type)`` ровно одна группа, номер в маркер не идёт, но сам
    номер (``MaskGroup.number``) всё равно фиксируется — он от 1 и внутри
    пары уникален независимо от того, показан ли в строке маркера.
    """
    pair_order: dict[_PairKey, list[_BucketKey]] = {}
    for bucket, items in buckets.items():
        profile_id = items[0].profile_id
        role_label = role_label_by_profile_id.get(profile_id, "") if profile_id else ""
        pair = (role_label, items[0].entity.type)
        pair_order.setdefault(pair, []).append(bucket)

    marker_by_bucket: dict[_BucketKey, str] = {}
    number_by_bucket: dict[_BucketKey, int] = {}
    for (role_label, entity_type), bucket_keys in pair_order.items():
        type_label = type_marker_label(entity_type, registry)
        show_suffix = len(bucket_keys) > 1
        for number, bucket in enumerate(bucket_keys, start=1):
            number_by_bucket[bucket] = number
            marker_by_bucket[bucket] = compose_marker(
                role_label, type_label, number if show_suffix else None
            )
    return marker_by_bucket, number_by_bucket
