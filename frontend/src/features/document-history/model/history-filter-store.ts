import { create } from "zustand";

export type HistoryStatusFilter = "all" | "review" | "ok";

/** Псевдо-значение «все проекты» для выпадающего списка. */
export const ALL_PROJECTS = "all";

type HistoryFilterState = {
  query: string;
  project: string;
  status: HistoryStatusFilter;
  /** Идентификатор раскрытой строки, либо null. */
  expandedId: string | null;
  setQuery: (query: string) => void;
  setProject: (project: string) => void;
  setStatus: (status: HistoryStatusFilter) => void;
  toggleExpanded: (id: string) => void;
};

export const useHistoryFilterStore = create<HistoryFilterState>((set) => ({
  query: "",
  project: ALL_PROJECTS,
  status: "all",
  expandedId: "h2",
  setQuery: (query) => set({ query }),
  setProject: (project) => set({ project }),
  setStatus: (status) => set({ status }),
  toggleExpanded: (id) =>
    set((state) => ({ expandedId: state.expandedId === id ? null : id })),
}));
