import { create } from "zustand";

import type { RunStatus } from "../../masking-run/api/masking-run";

/** `all` — без фильтра; остальное — статусы прогона как их отдаёт бэкенд. */
export type AdminRunStatusFilter = "all" | RunStatus;

/** Окно агрегатов вкладки «Обзор» — дни назад, за которые считаются ряды и
 * «за период»-метрики (`AdminOverviewOut.window_days` на бэкенде). */
export type AdminWindowDays = 7 | 30 | 90;

type AdminFiltersState = {
  windowDays: AdminWindowDays;
  runQuery: string;
  runStatus: AdminRunStatusFilter;
  /** `null` — без фильтра по владельцу. */
  runOwnerId: string | null;
  setWindowDays: (days: AdminWindowDays) => void;
  setRunQuery: (query: string) => void;
  setRunStatus: (status: AdminRunStatusFilter) => void;
  setRunOwnerId: (ownerId: string | null) => void;
  reset: () => void;
};

const INITIAL_STATE = {
  windowDays: 30 as AdminWindowDays,
  runQuery: "",
  runStatus: "all" as AdminRunStatusFilter,
  runOwnerId: null as string | null,
};

/**
 * Фильтры админки. Как и `document-history/model/history-filter-store.ts` —
 * значения уходят query-параметрами в `GET /api/admin/runs`, фильтрует база,
 * а не клиент.
 */
export const useAdminFiltersStore = create<AdminFiltersState>((set) => ({
  ...INITIAL_STATE,
  setWindowDays: (windowDays) => set({ windowDays }),
  setRunQuery: (runQuery) => set({ runQuery }),
  setRunStatus: (runStatus) => set({ runStatus }),
  setRunOwnerId: (runOwnerId) => set({ runOwnerId }),
  reset: () => set({ ...INITIAL_STATE }),
}));
