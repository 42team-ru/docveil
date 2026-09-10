import { useReviewStore } from "./review-store";

/**
 * Счётчики проверки. Считают по группам документа, который открыт **сейчас**
 * (`review-store.documentGroups`), а не по импортированной фикстуре: раньше
 * `useTotalGroupCount` читал docx-фикстуру напрямую, и на любом другом
 * документе бейдж «N/M подтверждено» показывал чужие числа.
 *
 * Группы кладёт экран проверки, когда получает данные, — счётчики ничего не
 * знают ни про источник данных, ни про формат документа.
 */
export const useTotalGroupCount = (): number =>
  useReviewStore((state) => state.documentGroups.length);

export const useConfirmedGroupCount = (): number =>
  useReviewStore(
    (state) =>
      Object.values(state.groupDecisions).filter((k) => k === "confirmed")
        .length,
  );

export const usePendingGroupCount = (): number =>
  useReviewStore(
    (state) =>
      state.documentGroups.length -
      Object.values(state.groupDecisions).filter((k) => k !== "pending").length,
  );

/** Группы с низкой уверенностью хотя бы одного вхождения — им нужен взгляд оператора в первую очередь. */
const LOW_CONFIDENCE = 0.6;

export const useLowConfidenceGroupCount = (): number =>
  useReviewStore(
    (state) =>
      state.documentGroups.filter(
        (group) => group.minConfidence < LOW_CONFIDENCE,
      ).length,
  );
