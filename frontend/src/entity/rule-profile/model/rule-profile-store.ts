import { create } from "zustand";

import type { MaskStyle } from "./types";

type RuleProfileState = {
  maskStyle: MaskStyle;
  highlightChanges: boolean;
  keepTables: boolean;
  stableMarkers: boolean;
  setMaskStyle: (style: MaskStyle) => void;
  setHighlightChanges: (value: boolean) => void;
  setKeepTables: (value: boolean) => void;
  setStableMarkers: (value: boolean) => void;
};

/**
 * Настройки текущей задачи обезличивания: как показывать маску в документе.
 *
 * Раньше здесь же жил выбор типов ПДн (`enabledTypes`/`preset`), но
 * `POST /api/runs` уходил с `types: []` независимо от него — движок читает
 * пустой список как «весь реестр» (`plan_node`, `backend/src/masker/graph/
 * nodes.py`), а подсвеченный на экране пресет ни на что не влиял. Стор
 * хранил решение, которое никто не читал; убрано вместе с `DataTypePicker`
 * (см. `UploadDropzone` — там теперь явно написано, что маскируется весь
 * реестр).
 */
export const useRuleProfileStore = create<RuleProfileState>((set) => ({
  maskStyle: "marker",
  highlightChanges: true,
  keepTables: true,
  stableMarkers: false,
  setMaskStyle: (maskStyle) => set({ maskStyle }),
  setHighlightChanges: (highlightChanges) => set({ highlightChanges }),
  setKeepTables: (keepTables) => set({ keepTables }),
  setStableMarkers: (stableMarkers) => set({ stableMarkers }),
}));
