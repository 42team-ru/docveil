import { create } from "zustand";

import type { MaskStyle } from "./types";

/** `#RRGGBB` фона маски-маркера — тот же формат, что принимает бэкенд
 * (`RunCreateRequest.highlight_background`, `masker.highlight.parse_highlight_background`). */
export type HighlightColor = string;

type RuleProfileState = {
  maskStyle: MaskStyle;
  highlightChanges: boolean;
  keepTables: boolean;
  stableMarkers: boolean;
  /** Цвет фона маркера — только для стиля "marker", «Заливка» всегда чёрная на бэкенде. */
  highlightColor: HighlightColor;
  /** Выбранные типы ПДн. Пустой массив = всё (бэкенд интерпретирует `types: []` как «весь реестр»). */
  enabledTypes: string[];
  setMaskStyle: (style: MaskStyle) => void;
  setHighlightChanges: (value: boolean) => void;
  setKeepTables: (value: boolean) => void;
  setStableMarkers: (value: boolean) => void;
  setHighlightColor: (value: HighlightColor) => void;
  setEnabledTypes: (types: string[]) => void;
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
/** Тот же янтарный, что и `DEFAULT_HIGHLIGHT_BACKGROUND` бэкенда
 * (`backend/src/masker/highlight.py`) — поле необязательное, но дефолт
 * должен совпадать, иначе выбор «оставить как есть» на самом деле менял бы цвет. */
export const DEFAULT_HIGHLIGHT_COLOR: HighlightColor = "#FFDE66";

export const useRuleProfileStore = create<RuleProfileState>((set) => ({
  maskStyle: "marker",
  highlightChanges: true,
  keepTables: true,
  stableMarkers: false,
  highlightColor: DEFAULT_HIGHLIGHT_COLOR,
  enabledTypes: [],
  setMaskStyle: (maskStyle) => set({ maskStyle }),
  setHighlightChanges: (highlightChanges) => set({ highlightChanges }),
  setKeepTables: (keepTables) => set({ keepTables }),
  setStableMarkers: (stableMarkers) => set({ stableMarkers }),
  setHighlightColor: (highlightColor) => set({ highlightColor }),
  setEnabledTypes: (enabledTypes) => set({ enabledTypes }),
}));
