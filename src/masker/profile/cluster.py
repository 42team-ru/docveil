"""Структурная кластеризация профилей без модели."""

from __future__ import annotations

from collections import defaultdict

from masker.model import Document, EntityType, Profile, ProfileMember, Source
from masker.profile.blocks import ContextBlock
from masker.profile.keys import merge_key
from masker.profile.labels import marker_label, role_title, slugify
from masker.refs import EntityIndex, entity_sort_key


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, first: int, second: int) -> None:
        first_root, second_root = self.find(first), self.find(second)
        if first_root != second_root:
            self.parent[max(first_root, second_root)] = min(first_root, second_root)


def cluster(document: Document, blocks: list[ContextBlock], index: EntityIndex) -> list[Profile]:
    """Собрать блоки в профили по сильным реквизитам и явным меткам."""
    occupied = [block for block in blocks if block.entities]
    union = _UnionFind(len(occupied))
    by_label: dict[str, list[int]] = defaultdict(list)
    by_key: dict[str, list[int]] = defaultdict(list)
    for block_index, block in enumerate(occupied):
        if block.label:
            by_label[block.label].append(block_index)
        for entity in block.entities:
            if entity.type in {EntityType.INN, EntityType.OGRN, EntityType.ORG_NAME}:
                by_key[merge_key(entity)].append(block_index)
    for group in [*by_label.values(), *by_key.values()]:
        for item in group[1:]:
            union.union(group[0], item)
    grouped: dict[int, list[ContextBlock]] = defaultdict(list)
    for position, block in enumerate(occupied):
        grouped[union.find(position)].append(block)
    anchors = {segment.order: segment.anchor for segment in document.segments}
    provisional: list[Profile] = []
    for group_blocks in grouped.values():
        members = sorted(
            (entity for block in group_blocks for entity in block.entities), key=entity_sort_key
        )
        labels = sorted({block.label for block in group_blocks if block.label})
        strong = any(entity.type in {EntityType.INN, EntityType.OGRN} for entity in members)
        confidence = (
            1.0
            if strong
            else (
                0.8
                if labels
                else (0.6 if any(entity.type is EntityType.ORG_NAME for entity in members) else 0.4)
            )
        )
        label = labels[0] if labels else ""
        provisional.append(
            Profile(
                id="",
                members=[
                    ProfileMember(entity, anchors[entity.segment_order], index.ref(entity))
                    for entity in members
                ],
                role_id=slugify(label) if label else "",
                role_title=role_title(label) if label else "",
                marker_label=marker_label(label) if label else "",
                confidence=confidence,
                role_confidence=0.9 if label else 0.0,
                source=Source.RULE,
                evidence=[f"метка: {label}"] if label else ["структурный блок"],
            )
        )
    provisional.sort(key=lambda profile: entity_sort_key(profile.members[0].entity))
    for number, profile in enumerate(provisional, 1):
        profile.id = f"P{number}"
        if not profile.marker_label:
            profile.marker_label = f"СТОРОНА-{number}"
    return provisional
