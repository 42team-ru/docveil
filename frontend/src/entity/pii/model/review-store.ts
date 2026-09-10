import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

import type {
  AnswerOption,
  ManualPiiOccurrence,
  PiiDecisionKind,
  PiiType,
} from "./types";

/** Режим показа документа — «Все / Оригинал» тулбара. */
export type DocumentViewMode = "all" | "original";

/** Группа открытого документа в том виде, в каком её считают счётчики. */
export type ReviewGroup = {
  id: string;
  /** Самая низкая уверенность среди вхождений группы. */
  minConfidence: number;
};

type ReviewState = {
  /**
   * Группы открытого сейчас документа. Держим их здесь, потому что счётчик
   * нужен и правой панели, и бейджу в рейле навигации (`masker-layout.tsx`),
   * а рейл про проверяемый документ ничего не знает и знать не должен.
   * Раньше счётчики читали docx-фикстуру напрямую и на любом другом документе
   * показывали чужие числа.
   */
  documentGroups: ReviewGroup[];
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
  /**
   * Ответы на вопросы, которыми движок остановил прогон. Ключ — `id` вопроса
   * (`TYPE-inn`, `PROFILE-P1`, `Q3`), значение — строка ровно из
   * `question.options`.
   */
  questionAnswers: Record<string, AnswerOption>;

  /** Сменить проверяемый документ: сбрасывает решения вместе с группами. */
  setDocumentGroups: (groups: ReviewGroup[]) => void;
  select: (occurrenceId: string) => void;
  setViewMode: (mode: DocumentViewMode) => void;
  confirmGroup: (groupId: string) => void;
  rejectGroup: (groupId: string) => void;
  confirmAllGroups: (groupIds: string[]) => void;
  setGroupType: (groupId: string, type: PiiType) => void;
  setOccurrenceType: (occurrenceId: string, type: PiiType) => void;
  addManual: (occurrence: ManualPiiOccurrence) => void;
  removeManual: (occurrenceId: string) => void;
  answerQuestion: (questionId: string, answer: AnswerOption) => void;
};

/**
 * Состояние ручной проверки ПДн. Живёт в сущности, а не в фиче — так же, как
 * прежний стор масок: счётчик решений нужен и правой панели, и бейджу в рейле
 * навигации, которые не должны знать друг о друге.
 *
 * `subscribeWithSelector` — чтобы `highlight-sync.ts` мог точечно перекрашивать
 * уже расставленные маркеры в чужом DOM документа без прогона через React.
 */
export const useReviewStore = create<ReviewState>()(
  subscribeWithSelector((set, get) => ({
    documentGroups: [],
    groupDecisions: {},
    typeOverrides: {},
    occurrenceTypeOverrides: {},
    selectedOccurrenceId: null,
    manualOccurrences: [],
    viewMode: "all",
    questionAnswers: {},

    setDocumentGroups: (groups) => {
      // Тот же набор групп — тот же документ: молча выходим, иначе каждый
      // повторный рендер экрана стирал бы решения оператора.
      const current = get().documentGroups;
      const same =
        current.length === groups.length &&
        current.every((group, index) => group.id === groups[index].id);
      if (same) return;

      set({
        documentGroups: groups,
        groupDecisions: {},
        typeOverrides: {},
        occurrenceTypeOverrides: {},
        selectedOccurrenceId: null,
        manualOccurrences: [],
        questionAnswers: {},
      });
    },

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

    answerQuestion: (questionId, answer) =>
      set((state) => ({
        questionAnswers: { ...state.questionAnswers, [questionId]: answer },
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
