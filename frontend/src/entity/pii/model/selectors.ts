import { piiExtractionFixture } from "./fixtures";
import { flattenPiiOccurrences, groupOccurrences } from "./flatten";
import { useReviewStore } from "./review-store";

/**
 * Считает по фикстуре напрямую — тот же приём, что и в старом
 * `entity/mask/model/mask-store.ts` (`useTotalCount` читает `maskFragments`).
 * Когда появится `features/pii-review/api/use-review-data.ts` поверх Orval,
 * счётчики примут данные аргументом вместо импорта фикстуры.
 */
function groupsFromFixture() {
  return groupOccurrences(flattenPiiOccurrences(piiExtractionFixture));
}

export const useTotalGroupCount = (): number => groupsFromFixture().size;

export const useConfirmedGroupCount = (): number =>
  useReviewStore(
    (state) =>
      Object.values(state.groupDecisions).filter((k) => k === "confirmed")
        .length,
  );

export const usePendingGroupCount = (): number => {
  const total = useTotalGroupCount();
  return useReviewStore(
    (state) =>
      total -
      Object.values(state.groupDecisions).filter((k) => k !== "pending")
        .length,
  );
};

/** Группы с низкой уверенностью хотя бы одного вхождения — им нужен взгляд оператора в первую очередь. */
const LOW_CONFIDENCE = 0.6;

export const useLowConfidenceGroupCount = (): number => {
  let count = 0;
  for (const occurrences of groupsFromFixture().values()) {
    const min = Math.min(...occurrences.map((o) => o.confidence));
    if (min < LOW_CONFIDENCE) count++;
  }
  return count;
};
