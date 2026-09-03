import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

import type { ManualPiiOccurrence, PiiDecisionKind, PiiType } from "./types";

/** Режим показа замен в документе — «Все / Только замены / Оригинал» тулбара. */
export type DocumentViewMode = "all" | "pending" | "original";

type ReviewState = {
  /** Решение по группе — единственный источник состояния «подтв./откл.»: без
   * границ фрагмента отвязать одно вхождение от группы больше нечем, поэтому
   * решение всегда групповое. */
  groupDecisions: Record<string, PiiDecisionKind>;
  /** Переопределение типа на всю группу. */
  typeOverrides: Record<string, PiiType>;
  /** Переопределение типа для одного вхождения — «применить только здесь». */
  occurrenceTypeOverrides: Record<string, PiiType>;
  selectedOccurrenceId: string | null;
  manualOccurrences: ManualPiiOccurrence[];
  viewMode: DocumentViewMode;

  select: (occurrenceId: string) => void;
  setViewMode: (mode: DocumentViewMode) => void;
  confirmGroup: (groupId: string) => void;
  rejectGroup: (groupId: string) => void;
  confirmAllGroups: (groupIds: string[]) => void;
  setGroupType: (groupId: string, type: PiiType) => void;
  setOccurrenceType: (occurrenceId: string, type: PiiType) => void;
  addManual: (occurrence: ManualPiiOccurrence) => void;
  removeManual: (occurrenceId: string) => void;
};

/**
 * Состояние ручной проверки ПДн. Живёт в сущности, а не в фиче — так же, как
 * старый `entity/mask/model/mask-store.ts`: счётчик решений нужен и правой
 * панели, и бейджу в рейле навигации, которые не должны знать друг о друге.
 *
 * `subscribeWithSelector` — чтобы `highlight-sync.ts` мог точечно перекрашивать
 * уже расставленные маркеры в чужом DOM документа без прогона через React.
 */
export const useReviewStore = create<ReviewState>()(
  subscribeWithSelector((set) => ({
    groupDecisions: {},
    typeOverrides: {},
    occurrenceTypeOverrides: {},
    selectedOccurrenceId: null,
    manualOccurrences: [],
    viewMode: "all",

    select: (occurrenceId) => set({ selectedOccurrenceId: occurrenceId }),
    setViewMode: (mode) => set({ viewMode: mode }),

    confirmGroup: (groupId) =>
      set((state) => ({
        groupDecisions: { ...state.groupDecisions, [groupId]: "confirmed" },
      })),

    rejectGroup: (groupId) =>
      set((state) => ({
        groupDecisions: { ...state.groupDecisions, [groupId]: "rejected" },
      })),

    confirmAllGroups: (groupIds) =>
      set((state) => ({
        groupDecisions: {
          ...state.groupDecisions,
          ...Object.fromEntries(groupIds.map((id) => [id, "confirmed" as const])),
        },
      })),

    setGroupType: (groupId, type) =>
      set((state) => ({
        typeOverrides: { ...state.typeOverrides, [groupId]: type },
      })),

    setOccurrenceType: (occurrenceId, type) =>
      set((state) => ({
        occurrenceTypeOverrides: {
          ...state.occurrenceTypeOverrides,
          [occurrenceId]: type,
        },
      })),

    addManual: (occurrence) =>
      set((state) => ({
        manualOccurrences: [...state.manualOccurrences, occurrence],
      })),

    removeManual: (occurrenceId) =>
      set((state) => ({
        manualOccurrences: state.manualOccurrences.filter(
          (o) => o.id !== occurrenceId,
        ),
      })),
  })),
);

export const useGroupDecision = (groupId: string): PiiDecisionKind =>
  useReviewStore((state) => state.groupDecisions[groupId] ?? "pending");

export const useEffectiveType = (
  occurrenceId: string,
  groupId: string,
  fallback: PiiType,
): PiiType =>
  useReviewStore(
    (state) =>
      state.occurrenceTypeOverrides[occurrenceId] ??
      state.typeOverrides[groupId] ??
      fallback,
  );
