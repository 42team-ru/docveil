"""JudgeAgent: критичное маскирует, о сомнительном спрашивает одной пачкой."""

from __future__ import annotations

from dataclasses import dataclass

from masker.detect.result import DetectionResult
from masker.judge.scoring import ASK_BELOW, score
from masker.model import Action, Entity, Profile, Question, Verdict, is_critical
from masker.profile.agent import ProfileResult
from masker.refs import EntityIndex, entity_sort_key

MASK_OPTION = "маскировать"
KEEP_OPTION = "оставить"


@dataclass(slots=True)
class JudgeResult:
    verdicts: list[Verdict]
    questions: list[Question]


class JudgeAgent:
    """Принимает решения, не меняя ни детекцию, ни профили."""

    def __init__(self, ask_below: float = ASK_BELOW) -> None:
        self._ask_below = ask_below

    def judge(self, detection: DetectionResult, profiles: ProfileResult) -> JudgeResult:
        """Выдать вердикт для каждой сущности и дедуплицированные вопросы."""
        entities = [*detection.entities, *profiles.candidates]
        index = EntityIndex(detection.entities)
        candidate_refs = {
            id(entity): f"C{number}" for number, entity in enumerate(profiles.candidates, 1)
        }
        profile_for_ref = {
            member.ref: profile for profile in profiles.profiles for member in profile.members
        }
        raw: list[tuple[Entity, str, Profile | None, float]] = []
        for entity in sorted(entities, key=entity_sort_key):
            ref = candidate_refs.get(id(entity), index.ref(entity))
            profile = profile_for_ref.get(ref)
            confidence = score(entity, profile)
            raw.append((entity, ref, profile, confidence))
        groups: dict[str, list[tuple[Entity, str, Profile | None, float]]] = {}
        for item in raw:
            entity = item[0]
            if not is_critical(entity.type) and item[3] < self._ask_below:
                key = f"{entity.type.value}:{entity.normalized or entity.text.casefold()}"
                groups.setdefault(key, []).append(item)
        questions: list[Question] = []
        question_for_ref: dict[str, str] = {}
        ordered_groups = sorted(groups.items(), key=lambda item: entity_sort_key(item[1][0][0]))
        for number, (key, items) in enumerate(ordered_groups, 1):
            question_id = f"Q{number}"
            first = items[0][0]
            question = Question(
                id=question_id,
                kind="entity",
                key=key,
                prompt=f"Маскировать «{first.text}» как {first.type.value}?",
                options=(MASK_OPTION, KEEP_OPTION),
                default=MASK_OPTION,
                refs=tuple(item[1] for item in items),
                anchors=tuple(
                    item[2]
                    .members[[member.ref for member in item[2].members].index(item[1])]
                    .anchor
                    if item[2] is not None
                    else profiles.anchors[item[0].segment_order]
                    for item in items
                ),
            )
            questions.append(question)
            question_for_ref.update({item[1]: question_id for item in items})
        verdicts: list[Verdict] = []
        for entity, ref, profile, confidence in raw:
            question_id = question_for_ref.get(ref, "")
            if is_critical(entity.type):
                action, reason = Action.MASK, "критичный тип маскируется без вопроса"
            elif question_id:
                action, reason = Action.ASK, "низкая уверенность, требуется решение человека"
            else:
                action, reason = Action.MASK, "уверенность достаточна"
            verdicts.append(
                Verdict(ref, action, confidence, reason, profile.id if profile else "", question_id)
            )
        return JudgeResult(verdicts=verdicts, questions=questions)

    def apply_answers(self, result: JudgeResult, answers: dict[str, str]) -> list[Verdict]:
        """Применить ответы; отсутствие или неизвестный ответ остаётся маскировкой."""
        answer_by_ref = {
            ref: answers.get(question.id, question.default)
            for question in result.questions
            for ref in question.refs
        }
        return [
            Verdict(
                verdict.ref,
                Action.KEEP
                if verdict.action is Action.ASK and answer_by_ref.get(verdict.ref) == KEEP_OPTION
                else (Action.MASK if verdict.action is Action.ASK else verdict.action),
                verdict.confidence,
                verdict.reason,
                verdict.profile_id,
                verdict.question_id,
            )
            for verdict in result.verdicts
        ]
