import { create } from "zustand";

import type { RunStatus } from "../../masking-run/api/masking-run";

/** `all` — без фильтра; остальное — статусы прогона как их отдаёт бэкенд. */
export type HistoryStatusFilter = "all" | RunStatus;

type HistoryFilterState = {
  query: string;
  status: HistoryStatusFilter;
  setQuery: (query: string) => void;
  setStatus: (status: HistoryStatusFilter) => void;
  reset: () => void;
};

/**
 * Фильтры журнала. Значения уходят query-параметрами в `GET /api/runs` —
 * фильтрует база, а не клиент: журнал растёт, и грузить его целиком ради
 * поиска по имени незачем.
 */
export const useHistoryFilterStore = create<HistoryFilterState>((set) => ({
  query: "",
  status: "all",
  setQuery: (query) => set({ query }),
  setStatus: (status) => set({ status }),
  reset: () => set({ query: "", status: "all" }),
}));
