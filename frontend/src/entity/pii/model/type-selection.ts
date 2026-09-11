import { MASK_OPTION, type AnswerOption, type PolicyQuestion } from "./types";

/** Ответ чекбокса — только из вариантов, разрешённых движком. */
export function typeSelectionAnswer(question: PolicyQuestion, checked: boolean): AnswerOption {
  return (checked ? question.options.find((option) => option === MASK_OPTION)
    : question.options.find((option) => option !== MASK_OPTION)) ?? question.default;
}

/** Заполняет выбранные типы, сохраняя ответы на остальные уточнения. */
export function withTypeSelectionDefaults(
  questions: PolicyQuestion[],
  answers: Record<string, AnswerOption>,
): Record<string, AnswerOption> {
  const result = { ...answers };
  for (const question of questions) {
    if (question.kind === "type" && !question.options.includes(result[question.id])) {
      result[question.id] = question.default;
    }
  }
  return result;
}
