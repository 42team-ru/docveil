import type { ReviewState } from "./review-store";
import { effectiveGroupDecision, useReviewStore } from "./review-store";

/**
 * Счётчики проверки. Считают по группам документа, который открыт **сейчас**
 * (`review-store.documentGroups`), а не по импортированной фикстуре: раньше
 * `useTotalGroupCount` читал docx-фикстуру напрямую, и на любом другом
 * документе бейдж «N/M подтверждено» показывал чужие числа.
 *
 * Группы кладёт экран проверки, когда получает данные, — счётчики ничего не
 * знают ни про источник данных, ни про формат документа.
 *
 * `useConfirmedGroupCount` считает по `effectiveGroupDecision` (черновик
 * поверх уже применённого решения), а не по сырому `groupDecisions`: черновик
 * пуст для любой группы, где оператор ничего не менял, а `setGroupDecision`
 * вообще не кладёт туда запись, если новое решение совпадает с применённым.
 * Раньше это давало «0/N подтверждено» на только что открытом, полностью
 * замаскированном документе — счётчик мерил клики оператора в этой сессии,
 * а не то, что реально попадёт в выходной файл.
 */
export const useTotalGroupCount = (): number =>
  useReviewStore((state) => state.documentGroups.length);

/** Вынесено из хука отдельной функцией, чтобы счёт можно было проверить юнит-тестом без рендера. */
export function confirmedGroupCount(
  state: Pick<ReviewState, "documentGroups" | "groupDecisions" | "appliedGroupDecisions">,
): number {
  return state.documentGroups.filter(
    (group) => effectiveGroupDecision(state, group.id) === "confirmed",
  ).length;
}

export const useConfirmedGroupCount = (): number =>
  useReviewStore(confirmedGroupCount);

/** Группы с низкой уверенностью хотя бы одного вхождения — им нужен взгляд оператора в первую очередь. */
const LOW_CONFIDENCE = 0.6;

export const useLowConfidenceGroupCount = (): number =>
  useReviewStore(
    (state) =>
      state.documentGroups.filter(
        (group) => group.minConfidence < LOW_CONFIDENCE,
      ).length,
  );
