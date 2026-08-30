"""PolicyAgent: вопросы человеку по типам и профилям, ref-центричные решения."""

from __future__ import annotations

from collections import Counter, defaultdict

from masker.detect.result import DetectionResult
from masker.model import (
    KEEP_CRITICAL_OPTION,
    KEEP_OPTION,
    MASK_OPTION,
    Anchor,
    Entity,
    EntityType,
    PolicyQuestion,
    Profile,
    is_critical,
)
from masker.profile.agent import ProfileResult
from masker.profile.keys import merge_key
from masker.refs import EntityIndex, entity_sort_key

#: Идентификатор группового вопроса про сущности вне профилей — раздел 5 плана T1.5.1.
PROFILE_UNASSIGNED = "PROFILE-UNASSIGNED"

#: До скольких образцов значений и якорей показывать в карточке вопроса — раздел 8.
SAMPLE_LIMIT = 5
ANCHOR_LIMIT = 3
SAMPLE_TRUNCATE = 60

#: Типы, для которых нормализованное значение (не текст) связывает профили —
#: критичные реквизиты плюс ФИО, см. раздел 8 плана T1.5.1.
_LINK_TYPES = frozenset({EntityType.INN, EntityType.OGRN, EntityType.SNILS, EntityType.PERSON})

_TYPE_TITLES: dict[EntityType, str] = {
    EntityType.ORG_NAME: "Название организации",
    EntityType.PERSON: "ФИО",
    EntityType.INN: "ИНН",
    EntityType.KPP: "КПП",
    EntityType.OGRN: "ОГРН",
    EntityType.SNILS: "СНИЛС",
    EntityType.BANK_ACCOUNT: "Банковский счёт",
    EntityType.BIK: "БИК",
    EntityType.BANK_NAME: "Название банка",
    EntityType.ADDRESS: "Адрес",
    EntityType.PHONE: "Телефон",
    EntityType.EMAIL: "Email",
    EntityType.PASSPORT: "Паспорт",
    EntityType.CONTRACT_NUMBER: "Номер договора",
    EntityType.MONEY: "Сумма",
    EntityType.DATE: "Дата",
    EntityType.SITE: "Сайт",
}


def _title(entity_type: EntityType) -> str:
    return _TYPE_TITLES.get(entity_type, entity_type.value)


def _truncate(value: str) -> str:
    if len(value) <= SAMPLE_TRUNCATE:
        return value
    return value[: SAMPLE_TRUNCATE - 1] + "…"


def _samples(entities: list[Entity]) -> tuple[str, ...]:
    ordered = sorted(entities, key=entity_sort_key)
    return tuple(_truncate(entity.text) for entity in ordered[:SAMPLE_LIMIT])


def _anchors_for(entities: list[Entity], anchors: dict[int, Anchor]) -> tuple[Anchor, ...]:
    ordered = sorted(entities, key=entity_sort_key)
    result: list[Anchor] = []
    seen_labels: set[str] = set()
    for entity in ordered:
        anchor = anchors.get(entity.segment_order)
        if anchor is None or anchor.label in seen_labels:
            continue
        seen_labels.add(anchor.label)
        result.append(anchor)
        if len(result) >= ANCHOR_LIMIT:
            break
    return tuple(result)


def _mask_options(*, critical: bool, allow_unmask_critical: bool) -> tuple[str, ...]:
    if not critical:
        return (MASK_OPTION, KEEP_OPTION)
    if allow_unmask_critical:
        return (MASK_OPTION, KEEP_CRITICAL_OPTION)
    return (MASK_OPTION,)


class PolicyAgent:
    """Строит вопросы политики по фактически найденным типам и профилям.

    ``PolicyQuestion`` адресует класс (тип или субъект), а не ссылку — единица
    решения `ref` разворачивается позже, в ``PolicyAgent.apply``, по приоритету
    ``DECISION_PRECEDENCE`` (``model.py``): персональное решение по сущности
    сильнее решения по её профилю, решение по профилю сильнее решения по её
    типу. См. раздел 4 плана T1.5.1.
    """

    def questions(
        self,
        detection: DetectionResult,
        profiles: ProfileResult,
        *,
        allow_unmask_critical: bool = False,
    ) -> list[PolicyQuestion]:
        """Вернуть вопросы по типам и профилям в детерминированном порядке."""
        all_entities = [*detection.entities, *profiles.candidates]
        type_questions = self._type_questions(all_entities, profiles.anchors, allow_unmask_critical)
        profile_questions = self._profile_questions(detection, profiles, allow_unmask_critical)
        return [*type_questions, *profile_questions]

    def _type_questions(
        self,
        entities: list[Entity],
        anchors: dict[int, Anchor],
        allow_unmask_critical: bool,
    ) -> list[PolicyQuestion]:
        by_type: dict[EntityType, list[Entity]] = defaultdict(list)
        for entity in entities:
            by_type[entity.type].append(entity)
        questions: list[PolicyQuestion] = []
        for entity_type in sorted(by_type, key=lambda item: item.value):
            items = by_type[entity_type]
            critical = is_critical(entity_type)
            title = _title(entity_type)
            questions.append(
                PolicyQuestion(
                    id=f"TYPE-{entity_type.value}",
                    kind="type",
                    target=entity_type.value,
                    title=title,
                    prompt=f"Маскировать все «{title}» (найдено {len(items)})?",
                    options=_mask_options(
                        critical=critical, allow_unmask_critical=allow_unmask_critical
                    ),
                    default=MASK_OPTION,
                    critical=critical,
                    found=len(items),
                    by_type=(),
                    samples=_samples(items),
                    anchors=_anchors_for(items, anchors),
                    linked=(),
                    role_title="",
                )
            )
        return questions

    def _profile_questions(
        self,
        detection: DetectionResult,
        profiles: ProfileResult,
        allow_unmask_critical: bool,
    ) -> list[PolicyQuestion]:
        index = EntityIndex(detection.entities)
        linked_map = self._linked_profiles(profiles.profiles)
        questions: list[PolicyQuestion] = []
        for profile in sorted(profiles.profiles, key=lambda item: item.id):
            entities = [member.entity for member in profile.members]
            questions.append(
                self._profile_question(
                    question_id=f"PROFILE-{profile.id}",
                    title=profile.marker_label or profile.id,
                    role_title=profile.role_title,
                    entities=entities,
                    anchors=profiles.anchors,
                    linked=linked_map.get(profile.id, ()),
                    allow_unmask_critical=allow_unmask_critical,
                )
            )
        unassigned_entities = [index.entity(ref) for ref in profiles.unassigned]
        if unassigned_entities:
            questions.append(
                self._profile_question(
                    question_id=PROFILE_UNASSIGNED,
                    title="Без профиля",
                    role_title="",
                    entities=unassigned_entities,
                    anchors=profiles.anchors,
                    linked=(),
                    allow_unmask_critical=allow_unmask_critical,
                )
            )
        return questions

    def _profile_question(
        self,
        *,
        question_id: str,
        title: str,
        role_title: str,
        entities: list[Entity],
        anchors: dict[int, Anchor],
        linked: tuple[str, ...],
        allow_unmask_critical: bool,
    ) -> PolicyQuestion:
        critical = any(is_critical(entity.type) for entity in entities)
        counter = Counter(entity.type.value for entity in entities)
        role_suffix = f" ({role_title})" if role_title else ""
        return PolicyQuestion(
            id=question_id,
            kind="profile",
            target=question_id.removeprefix("PROFILE-"),
            title=title,
            prompt=(
                f"Маскировать реквизиты субъекта {title}{role_suffix} "
                f"(найдено сущностей: {len(entities)})?"
            ),
            options=_mask_options(critical=critical, allow_unmask_critical=allow_unmask_critical),
            default=MASK_OPTION,
            critical=critical,
            found=len(entities),
            by_type=tuple(sorted(counter.items())),
            samples=_samples(entities),
            anchors=_anchors_for(entities, anchors),
            linked=linked,
            role_title=role_title,
        )

    def _linked_profiles(self, profiles: list[Profile]) -> dict[str, tuple[str, ...]]:
        """Связать профили, делящие нормализованный критичный ключ или ФИО.

        Подсказка человеку про фрагментацию профилей (раздел 8 плана
        T1.5.1); слияния не делает.
        """
        keys_by_profile: dict[str, set[str]] = {}
        for profile in profiles:
            keys_by_profile[profile.id] = {
                merge_key(member.entity)
                for member in profile.members
                if member.entity.type in _LINK_TYPES
            }
        linked: dict[str, set[str]] = defaultdict(set)
        ids = sorted(keys_by_profile)
        for position, first in enumerate(ids):
            for second in ids[position + 1 :]:
                if keys_by_profile[first] & keys_by_profile[second]:
                    linked[first].add(second)
                    linked[second].add(first)
        return {profile_id: tuple(sorted(values)) for profile_id, values in linked.items()}
