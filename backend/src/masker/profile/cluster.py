"""Структурная кластеризация профилей без модели."""

from __future__ import annotations

from collections import defaultdict

from masker.model import Document, EntityType, Profile, ProfileMember, Source
from masker.profile.blocks import ContextBlock
from masker.profile.keys import merge_key
from masker.profile.labels import marker_label, role_title, slugify
from masker.refs import EntityIndex, entity_sort_key

#: Типы, само присутствие которых делает группу блоков «стороной» —
#: организацией или человеком, а не голым реквизитом (телефон, e-mail,
#: адрес), который сам по себе ничьей стороной не является.
_PARTY_FORMING_TYPES = frozenset(
    {EntityType.INN, EntityType.OGRN, EntityType.ORG_NAME, EntityType.PERSON}
)


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


def _merge_if_compatible(
    union: _UnionFind, label_of_root: dict[int, str], first: int, second: int
) -> None:
    """Объединить компоненты, если их метки не конфликтуют.

    Конфликт — метки обеих компонент непусты и различны: `first` и
    `second` относятся к разным ролям, объединять их по общему
    ИНН/ОГРН/ФИО нельзя (см. комментарий у вызова на `by_key`). Проверка —
    на КОМПОНЕНТАХ (через `label_of_root`), а не на паре блоков: без этого
    цепочка «заказчик → безымянный → поставщик» законна для каждой пары
    по отдельности и транзитивно склеивает обе стороны в одну — ровно так
    на `ipklh-2022-01-11.pdf` получался профиль «Заказчик» на 139
    участников вместо двух отдельных сторон (12.09.2026).
    """
    first_root, second_root = union.find(first), union.find(second)
    if first_root == second_root:
        return
    first_label = label_of_root.get(first_root, "")
    second_label = label_of_root.get(second_root, "")
    if first_label and second_label and first_label != second_label:
        return
    union.union(first, second)
    label_of_root[union.find(first)] = first_label or second_label


def cluster(document: Document, blocks: list[ContextBlock], index: EntityIndex) -> list[Profile]:
    """Собрать блоки в профили по сильным реквизитам и явным меткам."""
    occupied = [block for block in blocks if block.entities]
    union = _UnionFind(len(occupied))
    label_of_root: dict[int, str] = {
        position: block.label for position, block in enumerate(occupied) if block.label
    }
    by_label: dict[str, list[int]] = defaultdict(list)
    by_key: dict[str, list[int]] = defaultdict(list)
    for block_index, block in enumerate(occupied):
        if block.label:
            by_label[block.label].append(block_index)
        for entity in block.entities:
            if entity.type in _PARTY_FORMING_TYPES:
                by_key[merge_key(entity)].append(block_index)
    for group in by_label.values():
        for item in group[1:]:
            _merge_if_compatible(union, label_of_root, group[0], item)
    # 12.09.2026: один ИНН/ОГРН/ФИО может встретиться в двух колонках с
    # разными ролями (например, реквизиты исполнителя и подпись заказчика,
    # либо преамбула, где метка стоит после названия обеих сторон — см.
    # `blocks.py::build_context_blocks`). Склеивать такие блоки по сильному
    # ключу нельзя: профиль первой колонки иначе переименовывает банк/ОГРН
    # второй стороны в «Заказчика». Ключи объединяем только внутри одной
    # роли либо через безымянные блоки — и конфликт проверяется на всей
    # компоненте (`_merge_if_compatible`), а не только на паре блоков.
    for group in by_key.values():
        for left_index, left in enumerate(group):
            for right in group[left_index + 1 :]:
                _merge_if_compatible(union, label_of_root, left, right)
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
        if not labels and not any(entity.type in _PARTY_FORMING_TYPES for entity in members):
            # Ни роли, ни ИНН/ОГРН/наименования/ФИО — это одинокий реквизит
            # (телефон, e-mail, адрес), а не сторона договора. Собственный
            # маркер `СТОРОНА-N` он не получает: остаётся в `unassigned»
            # (`profile/agent.py`) и получает общий маркер через
            # `mask/keys.py::group_key`, как и любая другая непрофилированная
            # сущность. Без этого фильтра `edukirovsk-2018-659372.pdf` давал
            # 190 профилей-одиночек из 315 сущностей (12.09.2026).
            continue
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
