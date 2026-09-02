"""PolicyAgent: вопросы человеку по типам и профилям, ref-центричные решения."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from masker.detect.result import DetectionResult
from masker.model import (
    DECISION_PRECEDENCE,
    KEEP_CRITICAL_OPTION,
    KEEP_OPTION,
    MASK_OPTION,
    Action,
    Anchor,
    Decision,
    DecisionSource,
    Entity,
    EntityType,
    PolicyQuestion,
    Profile,
    Question,
    Verdict,
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


def _type_mask_options(*, critical: bool, allow_unmask_critical: bool) -> tuple[str, ...]:
    """Варианты ответа на вопрос о типе: у типа все сущности критичны разом.

    Обычным «оставить» критичный тип снять нельзя — только двойным
    подтверждением, отсюда бинарный выбор без промежуточного варианта.
    """
    if not critical:
        return (MASK_OPTION, KEEP_OPTION)
    if allow_unmask_critical:
        return (MASK_OPTION, KEEP_CRITICAL_OPTION)
    return (MASK_OPTION,)


def _profile_mask_options(*, critical: bool, allow_unmask_critical: bool) -> tuple[str, ...]:
    """Варианты ответа на вопрос о профиле: критичность — не всё-или-ничего.

    Профиль обычно смешивает критичные и некритичные реквизиты. Обычное
    «оставить» всегда доступно и снимает маску с некритичной части субъекта;
    критичные реквизиты профиля остаются замаскированными (``critical_guard``),
    пока не выбран отдельный вариант ``KEEP_CRITICAL_OPTION`` при явном
    ``--unmask-critical`` — см. раздел 3 плана T1.5.1.
    """
    options = (MASK_OPTION, KEEP_OPTION)
    if critical and allow_unmask_critical:
        return (*options, KEEP_CRITICAL_OPTION)
    return options


def _action_for_option(option: str) -> Action:
    """MASK_OPTION → маскировать, любой другой действительный вариант → оставить."""
    return Action.MASK if option == MASK_OPTION else Action.KEEP


def _group_reason(source: str, label: str) -> str:
    if source == "human":
        return f"{label}: выбор человека"
    return f"{label}: ответа не было, применён вариант по умолчанию"


@dataclass(frozen=True, slots=True)
class GroupAnswer:
    """Итог группового вопроса (по типу или профилю) после применения ответа."""

    id: str
    kind: str
    target: str
    answer: str
    source: str  # "human" | "default"


@dataclass(frozen=True, slots=True)
class CriticalUnmask:
    """Запись о снятой маске с критичного типа/профиля — раздел 3 плана T1.5.1."""

    question_id: str
    kind: str
    target: str
    count: int


@dataclass(slots=True)
class PolicyResult:
    """Итог ``PolicyAgent.apply``: по одному решению на каждую ``ref``.

    ``overridden`` хранит проигравшие, но применимые решения — по ним человек
    видит, почему его групповая галочка не сработала на конкретной ссылке
    (раздел 7 плана T1.5.1).
    """

    decisions: list[Decision]
    overridden: dict[str, list[Decision]] = field(default_factory=dict)
    types: list[GroupAnswer] = field(default_factory=list)
    profiles: list[GroupAnswer] = field(default_factory=list)
    critical_unmasked: list[CriticalUnmask] = field(default_factory=list)
    unanswered_defaults: list[str] = field(default_factory=list)
    ignored_answers: list[str] = field(default_factory=list)
    invalid_answers: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


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

    def apply(
        self,
        detection: DetectionResult,
        profiles: ProfileResult,
        verdicts: list[Verdict],
        judge_questions: list[Question],
        policy_questions: list[PolicyQuestion],
        answers: dict[str, str],
        *,
        allow_unmask_critical: bool = False,
    ) -> PolicyResult:
        """Свести решения судьи и человека к одному действию на каждую ``ref``.

        Порядок разрешения конфликтов — ``DECISION_PRECEDENCE`` (``model.py``):
        персональный ответ на вопрос судьи (``entity``) сильнее ответа на вопрос
        о профиле (``profile``), тот сильнее ответа на вопрос о типе (``type``),
        тот сильнее решения судьи по уверенности (``judge``), а всё это слабее
        молчаливого «маскировать» (``default``). Критичный тип или профиль,
        снятие маски с которого не подтверждено дважды (``allow_unmask_critical``
        плюс явный ответ ``KEEP_CRITICAL_OPTION``), защищён решением уровня 0
        ``critical_guard`` — оно добавляется последним и побеждает всё.
        """
        entity_by_ref = self._entity_by_ref(detection, profiles)
        profile_id_by_ref = self._profile_id_by_ref(profiles, entity_by_ref)

        policy_by_id = {question.id: question for question in policy_questions}
        judge_by_id = {question.id: question for question in judge_questions}
        known_ids = set(policy_by_id) | set(judge_by_id)

        ignored_answers = sorted(key for key in answers if key not in known_ids)
        unanswered_defaults: list[str] = []
        invalid_answers: list[str] = []
        resolved: dict[str, tuple[str, str]] = {}
        all_questions: dict[str, PolicyQuestion | Question] = {**policy_by_id, **judge_by_id}
        for question_id, question in all_questions.items():
            raw = answers.get(question_id)
            if raw is None:
                unanswered_defaults.append(question_id)
                resolved[question_id] = (question.default, "default")
            elif raw not in question.options:
                invalid_answers.append(question_id)
                resolved[question_id] = (question.default, "default")
            else:
                resolved[question_id] = (raw, "human")
        unanswered_defaults.sort()
        invalid_answers.sort()

        verdict_by_ref = {verdict.ref: verdict for verdict in verdicts}
        decisions: list[Decision] = []
        overridden: dict[str, list[Decision]] = {}
        critical_events: dict[tuple[str, str], int] = {}
        diagnostics: list[str] = []

        for ref, entity in entity_by_ref.items():
            applicable: dict[str, Decision] = {}

            verdict = verdict_by_ref.get(ref)
            if verdict is not None and verdict.question_id and verdict.question_id in judge_by_id:
                option, source = resolved[verdict.question_id]
                applicable[DecisionSource.ENTITY] = Decision(
                    ref,
                    _action_for_option(option),
                    DecisionSource.ENTITY,
                    verdict.question_id,
                    _group_reason(source, "конкретная сущность"),
                )
            elif verdict is not None and verdict.action is Action.MASK:
                applicable[DecisionSource.JUDGE] = Decision(
                    ref, Action.MASK, DecisionSource.JUDGE, "", verdict.reason
                )

            profile_question_id = profile_id_by_ref.get(ref)
            if profile_question_id is not None and profile_question_id in resolved:
                option, source = resolved[profile_question_id]
                applicable[DecisionSource.PROFILE] = Decision(
                    ref,
                    _action_for_option(option),
                    DecisionSource.PROFILE,
                    profile_question_id,
                    _group_reason(source, "профиль"),
                )

            type_question_id = f"TYPE-{entity.type.value}"
            if type_question_id in resolved:
                option, source = resolved[type_question_id]
                applicable[DecisionSource.TYPE] = Decision(
                    ref,
                    _action_for_option(option),
                    DecisionSource.TYPE,
                    type_question_id,
                    _group_reason(source, "тип отключён человеком" if source == "human" else "тип"),
                )

            applicable[DecisionSource.DEFAULT] = Decision(
                ref, Action.MASK, DecisionSource.DEFAULT, "", "маскировать по умолчанию"
            )

            winner = min(
                applicable.values(), key=lambda item: DECISION_PRECEDENCE.index(item.decided_by)
            )

            if is_critical(entity.type):
                # Обычное «оставить» на профиль или тип не снимает маску с
                # критичного реквизита — только явный KEEP_CRITICAL_OPTION при
                # запущенном --unmask-critical, раздел 3 плана T1.5.1.
                winning_option = resolved.get(winner.question_id, ("", ""))[0]
                confirmed = (
                    allow_unmask_critical
                    and winner.action is Action.KEEP
                    and winning_option == KEEP_CRITICAL_OPTION
                )
                if confirmed:
                    key = (winner.question_id, entity.type.value)
                    critical_events[key] = critical_events.get(key, 0) + 1
                else:
                    guard = Decision(
                        ref,
                        Action.MASK,
                        DecisionSource.CRITICAL_GUARD,
                        "",
                        "критичный тип: снятие требует явного подтверждения",
                    )
                    diagnostics.append(
                        f"{ref}: критичный тип «{entity.type.value}» — снятие маски "
                        "требует двойного подтверждения (--unmask-critical и осознанный ответ)"
                    )
                    applicable[DecisionSource.CRITICAL_GUARD] = guard
                    winner = guard

            losers = sorted(
                (item for item in applicable.values() if item is not winner),
                key=lambda item: DECISION_PRECEDENCE.index(item.decided_by),
            )
            overridden[ref] = losers
            decisions.append(winner)

        decisions.sort(key=lambda item: entity_sort_key(entity_by_ref[item.ref]))

        critical_unmasked = [
            CriticalUnmask(
                question_id=question_id,
                kind="type" if question_id.startswith("TYPE-") else "profile",
                target=target,
                count=count,
            )
            for (question_id, target), count in sorted(critical_events.items())
        ]

        types = [
            GroupAnswer(question.id, "type", question.target, *resolved[question.id])
            for question in policy_questions
            if question.kind == "type"
        ]
        profile_summaries = [
            GroupAnswer(question.id, "profile", question.target, *resolved[question.id])
            for question in policy_questions
            if question.kind == "profile"
        ]

        return PolicyResult(
            decisions=decisions,
            overridden=overridden,
            types=types,
            profiles=profile_summaries,
            critical_unmasked=critical_unmasked,
            unanswered_defaults=unanswered_defaults,
            ignored_answers=ignored_answers,
            invalid_answers=invalid_answers,
            diagnostics=diagnostics,
        )

    def _entity_by_ref(
        self, detection: DetectionResult, profiles: ProfileResult
    ) -> dict[str, Entity]:
        index = EntityIndex(detection.entities)
        result = {ref: index.entity(ref) for ref in index.refs()}
        for number, candidate in enumerate(profiles.candidates, 1):
            result[f"C{number}"] = candidate
        return result

    def _profile_id_by_ref(
        self, profiles: ProfileResult, entity_by_ref: dict[str, Entity]
    ) -> dict[str, str]:
        assigned: dict[str, str] = {}
        for profile in profiles.profiles:
            for member in profile.members:
                assigned[member.ref] = f"PROFILE-{profile.id}"
        for ref in entity_by_ref:
            assigned.setdefault(ref, PROFILE_UNASSIGNED)
        return assigned

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
                    options=_type_mask_options(
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
            options=_profile_mask_options(
                critical=critical, allow_unmask_critical=allow_unmask_critical
            ),
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
