import { create } from "zustand";

import type { CompiledTypeOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";

type CustomTypesState = {
  /** Типы, добавленные оператором для текущего прогона. */
  types: CompiledTypeOut[];
  addType: (type: CompiledTypeOut) => void;
  removeType: (index: number) => void;
  clear: () => void;
};

export const useCustomTypesStore = create<CustomTypesState>((set) => ({
  types: [],
  addType: (type) => set((state) => ({ types: [...state.types, type] })),
  removeType: (index) =>
    set((state) => ({ types: state.types.filter((_, i) => i !== index) })),
  clear: () => set({ types: [] }),
}));
