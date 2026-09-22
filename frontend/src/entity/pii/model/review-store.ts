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
  /** Решение, уже отражённое в опубликованном файле. */
  appliedDecision: Exclude<PiiDecisionKind, "pending">;
  /** Решения по отдельным вхождениям, если группа маскируется не целиком. */
  appliedOccurrenceDecisions?: Record<string, Exclude<PiiDecisionKind, "pending">>;
};

export type ReviewState = {
  /**
   * Группы открытого сейчас документа. Держим их здесь, потому что счётчик
   * нужен и правой панели, и бейджу в рейле навигации (`masker-layout.tsx`),
   * а рейл про проверяемый документ ничего не знает и знать не должен.
   * Раньше счётчики читали docx-фикстуру напрямую и на любом другом документе
   * показывали чужие числа.
   */
  documentGroups: ReviewGroup[];
  /** Ключ `(runId, artifactRevision)` последней опубликованной версии. */
  documentKey: string | null;
  /** Правки относительно опубликованной версии. Отсутствие ключа означает,
   * что в файле уже отображается применённое сервером решение. */
  groupDecisions: Record<string, PiiDecisionKind>;
  appliedGroupDecisions: Record<string, Exclude<PiiDecisionKind, "pending">>;
  /** Черновые решения по одному вхождению; сильнее решения всей группы. */
  occurrenceDecisions: Record<string, PiiDecisionKind>;
  /** Решения отдельных вхождений, уже попавшие в опубликованный файл. */
  appliedOccurrenceDecisions: Record<string, Exclude<PiiDecisionKind, "pending">>;
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

  /** Сменить опубликованную версию документа и сбросить только её черновик. */
  setDocumentGroups: (documentKey: string, groups: ReviewGroup[]) => void;
  select: (occurrenceId: string) => void;
  setViewMode: (mode: DocumentViewMode) => void;
  confirmGroup: (groupId: string) => void;
  rejectGroup: (groupId: string) => void;
  confirmOccurrence: (occurrenceId: string, groupId: string) => void;
  rejectOccurrence: (occurrenceId: string, groupId: string) => void;
  confirmAllGroups: (groupIds: string[]) => void;
  hasUnappliedChanges: () => boolean;
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
    documentKey: null,
    groupDecisions: {},
    appliedGroupDecisions: {},
    occurrenceDecisions: {},
    appliedOccurrenceDecisions: {},
    typeOverrides: {},
    occurrenceTypeOverrides: {},
    selectedOccurrenceId: null,
    manualOccurrences: [],
    viewMode: "all",
    questionAnswers: {},

    setDocumentGroups: (documentKey, groups) => {
      // Повторный рендер той же версии не должен стереть черновик. Список
      // групп недостаточен: две версии могут содержать одинаковые ID.
      if (get().documentKey === documentKey) return;

      set({
        documentGroups: groups,
        documentKey,
        groupDecisions: {},
        appliedGroupDecisions: Object.fromEntries(
          groups.map((group) => [group.id, group.appliedDecision]),
        ),
        occurrenceDecisions: {},
        appliedOccurrenceDecisions: Object.assign(
          {},
          ...groups.map((group) => group.appliedOccurrenceDecisions ?? {}),
        ),
        typeOverrides: {},
        occurrenceTypeOverrides: {},
        selectedOccurrenceId: null,
        manualOccurrences: [],
        questionAnswers: {},
      });
    },

    select: (occurrenceId) => set({ selectedOccurrenceId: occurrenceId }),
    setViewMode: (mode) => set({ viewMode: mode }),

    confirmGroup: (groupId) => setGroupDecision(set, get, groupId, "confirmed"),

    rejectGroup: (groupId) => setGroupDecision(set, get, groupId, "rejected"),

    confirmOccurrence: (occurrenceId, groupId) =>
      setOccurrenceDecision(set, get, occurrenceId, groupId, "confirmed"),

    rejectOccurrence: (occurrenceId, groupId) =>
      setOccurrenceDecision(set, get, occurrenceId, groupId, "rejected"),

    confirmAllGroups: (groupIds) =>
      groupIds.forEach((groupId) => setGroupDecision(set, get, groupId, "confirmed")),

    hasUnappliedChanges: () => {
      const state = get();
      return Object.keys(state.groupDecisions).length > 0
        || Object.keys(state.occurrenceDecisions).length > 0
        || Object.keys(state.typeOverrides).length > 0
        || Object.keys(state.occurrenceTypeOverrides).length > 0
        || state.manualOccurrences.length > 0;
    },

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
  useReviewStore((state) => effectiveGroupDecision(state, groupId));

/** Текущее намерение для строки списка: черновик сильнее опубликованного. */
export function effectiveGroupDecision(
  state: Pick<ReviewState, "groupDecisions" | "appliedGroupDecisions">,
  groupId: string,
): Exclude<PiiDecisionKind, "pending"> {
  const draft = state.groupDecisions[groupId];
  return (draft === "confirmed" || draft === "rejected" ? draft : undefined)
    ?? state.appliedGroupDecisions[groupId]
    ?? "confirmed";
}

/** Текущее решение для одного вхождения: его черновик сильнее группового. */
export function effectiveOccurrenceDecision(
  state: Pick<
    ReviewState,
    | "groupDecisions"
    | "appliedGroupDecisions"
    | "occurrenceDecisions"
    | "appliedOccurrenceDecisions"
  >,
  occurrenceId: string,
  groupId: string,
): Exclude<PiiDecisionKind, "pending"> {
  const own = state.occurrenceDecisions[occurrenceId];
  if (own === "confirmed" || own === "rejected") return own;
  const group = effectiveGroupDecision(state, groupId);
  if (state.groupDecisions[groupId] !== undefined) return group;
  return state.appliedOccurrenceDecisions[occurrenceId] ?? group;
}

/** Решение, которое действительно есть в открытых байтах документа. */
export function appliedGroupDecision(
  state: Pick<ReviewState, "appliedGroupDecisions">,
  groupId: string,
): Exclude<PiiDecisionKind, "pending"> {
  return state.appliedGroupDecisions[groupId] ?? "confirmed";
}

function setGroupDecision(
  set: (partial: Partial<ReviewState> | ((state: ReviewState) => Partial<ReviewState>)) => void,
  get: () => ReviewState,
  groupId: string,
  decision: Exclude<PiiDecisionKind, "pending">,
): void {
  const applied = appliedGroupDecision(get(), groupId);
  set((state) => {
    const next = { ...state.groupDecisions };
    if (decision === applied) delete next[groupId];
    else next[groupId] = decision;
    return { groupDecisions: next };
  });
}

function setOccurrenceDecision(
  set: (partial: Partial<ReviewState> | ((state: ReviewState) => Partial<ReviewState>)) => void,
  get: () => ReviewState,
  occurrenceId: string,
  groupId: string,
  decision: Exclude<PiiDecisionKind, "pending">,
): void {
  const state = get();
  const applied = state.appliedOccurrenceDecisions[occurrenceId]
    ?? appliedGroupDecision(state, groupId);
  const groupDraft = state.groupDecisions[groupId];
  set((current) => {
    const next = { ...current.occurrenceDecisions };
    if (decision === groupDraft || (groupDraft === undefined && decision === applied)) {
      delete next[occurrenceId];
    } else {
      next[occurrenceId] = decision;
    }
    return { occurrenceDecisions: next };
  });
}

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
