import { create } from "zustand";

import { defaultEnabledTypes } from "./fixtures";
import type { MaskStyle } from "./types";

type RuleProfileState = {
  selectionMode: "preset" | "manual";
  enabledTypes: string[];
  preset: string;
  maskStyle: MaskStyle;
  highlightChanges: boolean;
  keepTables: boolean;
  stableMarkers: boolean;
  setSelectionMode: (mode: "preset" | "manual") => void;
  toggleType: (id: string) => void;
  /** Список типов приходит извне: сущность правил не знает про словарь ПДн. */
  selectAllTypes: (ids: string[]) => void;
  setPreset: (id: string) => void;
  setMaskStyle: (style: MaskStyle) => void;
  setHighlightChanges: (value: boolean) => void;
  setKeepTables: (value: boolean) => void;
  setStableMarkers: (value: boolean) => void;
};

/** Настройки текущей задачи обезличивания: что удалять и как это показывать. */
export const useRuleProfileStore = create<RuleProfileState>((set) => ({
  selectionMode: "preset",
  enabledTypes: defaultEnabledTypes,
  preset: "tender",
  maskStyle: "marker",
  highlightChanges: true,
  keepTables: true,
  stableMarkers: false,
  setSelectionMode: (selectionMode) => set({ selectionMode }),
  toggleType: (id) =>
    set((state) => ({
      enabledTypes: state.enabledTypes.includes(id)
        ? state.enabledTypes.filter((typeId) => typeId !== id)
        : [...state.enabledTypes, id],
    })),
  selectAllTypes: (ids) => set({ enabledTypes: ids }),
  setPreset: (id) => set({ preset: id }),
  setMaskStyle: (maskStyle) => set({ maskStyle }),
  setHighlightChanges: (highlightChanges) => set({ highlightChanges }),
  setKeepTables: (keepTables) => set({ keepTables }),
  setStableMarkers: (stableMarkers) => set({ stableMarkers }),
}));
