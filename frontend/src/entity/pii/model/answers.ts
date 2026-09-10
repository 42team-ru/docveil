import type {
  AnswerEnvelope,
  AnswerOption,
  PolicyQuestion,
} from "./types";
import { MASK_OPTION } from "./types";

/**
 * Собирает конверт ответов — то, что движок ждёт обратно при возобновлении
 * прогона (`Command(resume=...)`, `backend/src/masker/run.py`).
 *
 * Два правила, оба продиктованы поведением движка, а не вкусом:
 *
 * 1. **Отвечаем только на заданные вопросы.** Лишний ключ движок отбросит и
 *    запишет в `ignored_answers` — молча промолчать лучше, чем слать мусор.
 * 2. **Вариант берём из самого вопроса.** `parse_answers` заменяет незнакомую
 *    строку на `default`, то есть на «маскировать»: оператор нажал бы
 *    «оставить», а получил бы маску и никогда об этом не узнал. Поэтому
 *    вариант, которого нет в `question.options`, сюда не попадает.
 *
 * Из второго правила следует и поведение с критичными типами. Движок сам
 * решает, предлагать ли снятие маски: без флага прогона `--unmask-critical` у
 * вопроса про ИНН остаётся единственный вариант «маскировать», а с флагом
 * появляется «оставить (осознанное решение)». Интерфейс не изобретает
 * вариантов сверх этого списка и не подменяет один другим — воля оператора
 * уходит ровно в той форме, которую движок примет.
 */
export function buildAnswerEnvelope(
  questions: PolicyQuestion[],
  answers: Record<string, AnswerOption>,
  schemaVersion = 1,
): AnswerEnvelope {
  const result: Record<string, AnswerOption> = {};

  for (const question of questions) {
    const answer = answers[question.id];
    if (answer === undefined) continue;
    if (!question.options.includes(answer)) continue;
    result[question.id] = answer;
  }

  return { schema_version: schemaVersion, answers: result };
}

/**
 * На какие вопросы оператор ещё не ответил. Движок подставит им `default`
 * (всегда «маскировать») и запишет в `unanswered_defaults` — то есть
 * неотвеченный вопрос это не «ничего не произойдёт», а «замаскируем».
 */
export function unansweredQuestions(
  questions: PolicyQuestion[],
  answers: Record<string, AnswerOption>,
): PolicyQuestion[] {
  return questions.filter((question) => answers[question.id] === undefined);
}

/**
 * Вопрос, на который движок разрешает единственный ответ. Так выглядит защита
 * критичного типа: снятие маски требует и флага прогона, и осознанного
 * варианта ответа, поэтому без флага выбора у оператора нет вовсе.
 */
export function isForcedQuestion(question: PolicyQuestion): boolean {
  return question.options.length === 1 && question.options[0] === MASK_OPTION;
}
