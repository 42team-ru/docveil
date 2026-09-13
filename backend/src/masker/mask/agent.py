"""`PlanAgent` — сущность + профиль + решение → согласованный маркер.

Ядро T1.6: превращает список найденных сущностей в `MaskPlan`, где одно и
то же значение (в любом написании) получает один и тот же маркер во всём
документе. Алгоритм детерминированный и не бросает исключений — все
особые случаи (тип не запрошен, решение «оставить», сегмент без якоря)
оседают в `MaskPlan.skipped`, а не роняют прогон.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from masker.entity_types import EntityTypeRegistry
from masker.mask.keys import group_key
from masker.mask.labels import (
    align_compact_label_number,
    assign_compact_labels,
    belongs_to_subject,
    compact_type_code,
    compose_canonical_label,
    compose_marker,
    contextual_type_label,
    is_anonymous_role,
    short_role_label,
    type_marker_label,
)
from masker.model import (
    Action,
    Anchor,
    Document,
    Entity,
    EntityType,
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

# 12.09.2026: два извлечения на 21 PDF open-contracts дали 48 сроков
# поставки (16--41 символ) и 8 условий оплаты (47--204). Это факты для
# карточки, а не PII: по умолчанию оставляем их в тексте, иначе договор
# теряет коммерческий смысл. Явный выбор типа по-прежнему разрешает маску.
_VISIBLE_CONTRACT_TERMS = frozenset({EntityType.DELIVERY_PERIOD, EntityType.PAYMENT_TERMS})


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
        ``requested_types=None`` — обычный режим: все PII маскируются, а
        условия оплаты и сроки остаются в тексте и в карточке. Явный набор
        типов позволяет оператору замаскировать и их.
        """
        index = EntityIndex(entities)
        anchors_by_order = {segment.order: segment.anchor for segment in document.segments}
        role_label_by_profile_id, profile_id_by_ref = _profile_lookup(profiles)
        ordered = sorted(entities, key=entity_sort_key)

        skipped: list[SkippedRef] = []
        pending: list[_PendingEntity] = []
        for entity in ordered:
            ref = index.ref(entity)
            if requested_types is None and entity.type in _VISIBLE_CONTRACT_TERMS:
                skipped.append(
                    SkippedRef(ref=ref, type=entity.type, reason="visible_contract_term")
                )
                continue
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

        pending = _prefer_contract_amount(pending)

        buckets = _bucket_by_first_occurrence(pending)
        segments_by_order = {segment.order: segment for segment in document.segments}
        display_label_by_bucket = {
            bucket: contextual_type_label(
                items[0].entity.type,
                segments_by_order[items[0].entity.segment_order].text,
                items[0].entity.start,
                items[0].entity.end,
            )
            for bucket, items in buckets.items()
        }
        profile_number_by_id = _profile_numbers(profiles)
        marker_by_bucket, number_by_bucket, canonical_by_bucket = _assign_markers(
            buckets,
            role_label_by_profile_id,
            profile_number_by_id,
            display_label_by_bucket,
            self._registry,
        )
        _align_power_of_attorney_numbers(
            buckets,
            number_by_bucket,
            canonical_by_bucket,
            display_label_by_bucket,
            self._registry,
        )
        # База короткой метки строится в порядке первого появления группы;
        # затем её номер выравнивается по канонической форме ниже.
        compact_label_by_bucket = assign_compact_labels(
            [
                (bucket, items[0].entity.type, display_label_by_bucket[bucket])
                for bucket, items in buckets.items()
            ],
            self._registry,
        )
        for bucket, items in buckets.items():
            # Короткая форма может сократить тип или роль, но не переименовать
            # группу: отдельный сквозной счётчик раньше превращал каноническую
            # «[Сумма 1]» в видимую «[Сумма 3]».
            compact_label_by_bucket[bucket] = align_compact_label_number(
                compact_label_by_bucket[bucket], canonical_by_bucket[bucket]
            )
            profile_id = items[0].profile_id
            profile_number = profile_number_by_id.get(profile_id)
            role_label = role_label_by_profile_id.get(profile_id, "")
            if (
                profile_number is not None
                and belongs_to_subject(items[0].entity.type)
                and not is_anonymous_role(role_label)
            ):
                # 11.09.2026: все написания значения из одного профиля
                # обязаны иметь одну короткую подпись, не свой номер группы.
                entity_type = items[0].entity.type
                if entity_type == EntityType.ORG_NAME:
                    # Каноническая форма для ORG_NAME+роль уже не включает тип
                    # («Поставщик», а не «Поставщик Организация»); компактная
                    # форма должна следовать тому же принципу.
                    compact_label_by_bucket[bucket] = (
                        f"[{short_role_label(role_label)} {profile_number}]"
                    )
                else:
                    compact_label_by_bucket[bucket] = (
                        f"[{short_role_label(role_label)}"
                        f"{compact_type_code(entity_type, self._registry)}{profile_number}]"
                    )

        canonical_by_compact: dict[str, str] = {}
        used_compact_labels: set[str] = set()
        for bucket in buckets:
            label = compact_label_by_bucket[bucket]
            canonical = canonical_by_bucket[bucket]
            previous_canonical = canonical_by_compact.get(label)
            if previous_canonical is None or previous_canonical == canonical:
                # 12.09.2026: повтор канонической метки означает одну
                # читаемую роль стороны, даже если PlanAgent хранит разные
                # значения в отдельных группах. Разная подпись здесь лжёт
                # читателю, будто это разные стороны.
                canonical_by_compact.setdefault(label, canonical)
                used_compact_labels.add(label)
                continue
            # Одинаковая короткая форма у РАЗНЫХ канонических меток делает
            # их неразличимыми. Только в этом случае добавляем различитель;
            # номер канонической метки остаётся последним для отчёта.
            for offset in range(32):
                suffix = chr(ord("а") + offset)
                candidate = re.sub(r"(\d+)\]$", rf"{suffix}\1]", label)
                if candidate not in used_compact_labels:
                    compact_label_by_bucket[bucket] = candidate
                    canonical_by_compact[candidate] = canonical
                    used_compact_labels.add(candidate)
                    break

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
                    canonical_label=canonical_by_bucket[bucket],
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


def _prefer_contract_amount(pending: list[_PendingEntity]) -> list[_PendingEntity]:
    """Не отдавать рендеру две замены для одной суммы.

    Детекция сохраняет ``money`` и ``contract_amount`` для одного спана: это
    позволяет выбрать любой из типов. Когда оба выбраны для маскирования,
    маркер цены договора информативнее общего маркера суммы, поэтому в план
    попадает он один.
    """
    contract_spans = {
        (item.entity.segment_order, item.entity.start, item.entity.end)
        for item in pending
        if item.entity.type == EntityType.CONTRACT_AMOUNT
    }
    return [
        item
        for item in pending
        if item.entity.type != EntityType.MONEY
        or (item.entity.segment_order, item.entity.start, item.entity.end) not in contract_spans
    ]


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


def _profile_numbers(profiles: list[Profile] | None) -> dict[str, int]:
    """Назначить стабильный номер каждому профилю внутри его роли.

    Номер стороны должен происходить из профиля, а не из очереди значений:
    тогда одна и та же персона, сведённая профилировщиком из полной и краткой
    формы, сохраняет номер во всех местах документа.
    """
    if not profiles:
        return {}
    by_role: dict[str, list[Profile]] = {}
    for profile in profiles:
        by_role.setdefault(profile.marker_label, []).append(profile)
    result: dict[str, int] = {}
    for grouped in by_role.values():
        # 11.09.2026: порядок профилей уже задан первым вхождением cluster(),
        # но сортировка id фиксирует номер и для переданных извне профилей.
        for number, profile in enumerate(sorted(grouped, key=lambda item: item.id), start=1):
            result[profile.id] = number
    return result


def _align_power_of_attorney_numbers(
    buckets: dict[_BucketKey, list[_PendingEntity]],
    number_by_bucket: dict[_BucketKey, int],
    canonical_by_bucket: dict[_BucketKey, str],
    display_label_by_bucket: dict[_BucketKey, str],
    registry: EntityTypeRegistry,
) -> None:
    """Дать дате и номеру одной доверенности общий читаемый номер."""
    powers = [
        bucket
        for bucket, items in buckets.items()
        if items[0].entity.type == EntityType.POWER_OF_ATTORNEY_NUMBER
    ]
    for bucket, items in buckets.items():
        entity = items[0].entity
        if entity.type != EntityType.DATE or display_label_by_bucket[bucket] != "Дата доверенности":
            continue
        same_segment = [
            power
            for power in powers
            if buckets[power][0].entity.segment_order == entity.segment_order
            and buckets[power][0].entity.start >= entity.end
        ]
        if not same_segment:
            continue
        power = min(same_segment, key=lambda item: buckets[item][0].entity.start)
        number = number_by_bucket[power]
        # 12.09.2026: в школьном контракте «от 26 октября … №109»
        # превращалось в `[Довер. 2]` и `[Ном. дов. 1]`, потому что date и
        # power_of_attorney_number нумеровались разными очередями.
        number_by_bucket[bucket] = number
        power_entity = buckets[power][0].entity
        canonical_by_bucket[power] = compose_canonical_label(
            "",
            power_entity.type,
            number,
            registry,
            display_type_label=display_label_by_bucket[power],
        )
        canonical_by_bucket[bucket] = compose_canonical_label(
            "",
            entity.type,
            number,
            registry,
            display_type_label=display_label_by_bucket[bucket],
        )


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
    profile_number_by_id: dict[str, int],
    display_label_by_bucket: dict[_BucketKey, str],
    registry: EntityTypeRegistry,
) -> tuple[dict[_BucketKey, str], dict[_BucketKey, int], dict[_BucketKey, str]]:
    """Пронумеровать группы внутри пары (роль, тип) и собрать маркеры.

    Суффикс ``-N`` есть либо у всех групп пары, либо ни у одной: если внутри
    ``(role_label, type)`` ровно одна группа, номер в маркер не идёт, но сам
    номер (``MaskGroup.number``) всё равно фиксируется — он от 1 и внутри
    пары уникален независимо от того, показан ли в строке маркера.

    Возвращает машинный маркер (``compose_marker``, капс — контракт
    ``MaskGroup.marker``), номер и человекочитаемую каноническую метку
    (``compose_canonical_label``, план М4) — обе строки нумеруются одним и
    тем же ``show_suffix``, иначе «номер показан в машинном маркере, но не
    в человеческом» стало бы отдельным, никем не проверяемым рассогласованием.
    """
    pair_order: dict[_PairKey, list[_BucketKey]] = {}
    for bucket, items in buckets.items():
        profile_id = items[0].profile_id
        role_label = role_label_by_profile_id.get(profile_id, "") if profile_id else ""
        pair = (role_label, items[0].entity.type)
        pair_order.setdefault(pair, []).append(bucket)

    marker_by_bucket: dict[_BucketKey, str] = {}
    number_by_bucket: dict[_BucketKey, int] = {}
    canonical_by_bucket: dict[_BucketKey, str] = {}
    for (role_label, entity_type), bucket_keys in pair_order.items():
        type_label = type_marker_label(entity_type, registry)
        marker_role = (
            role_label
            if belongs_to_subject(entity_type) and not is_anonymous_role(role_label)
            else ""
        )
        show_suffix = len(bucket_keys) > 1
        for number, bucket in enumerate(bucket_keys, start=1):
            number_by_bucket[bucket] = number
            profile_id = buckets[bucket][0].profile_id
            role_number = profile_number_by_id.get(profile_id)
            # 11.09.2026: субъектные метки получают номер профиля; условия
            # договора остаются без роли и продолжают различаться значением.
            suffix = (
                role_number
                if role_number is not None and not is_anonymous_role(role_label)
                else (number if show_suffix else None)
            )
            marker_by_bucket[bucket] = compose_marker(marker_role, type_label, suffix)
            canonical_by_bucket[bucket] = compose_canonical_label(
                role_label,
                entity_type,
                suffix,
                registry,
                display_type_label=display_label_by_bucket[bucket],
            )
    return marker_by_bucket, number_by_bucket, canonical_by_bucket
