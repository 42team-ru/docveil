import { create } from "zustand";

import type { MaskStyle } from "./types";

/** `#RRGGBB` фона маски-маркера — тот же формат, что принимает бэкенд
 * (`RunCreateRequest.highlight_background`, `masker.highlight.parse_highlight_background`). */
export type HighlightColor = string;

/** Тот же янтарный, что и `DEFAULT_HIGHLIGHT_BACKGROUND` бэкенда
 * (`backend/src/masker/highlight.py`) — поле необязательное, но дефолт
 * должен совпадать, иначе выбор «оставить как есть» на самом деле менял бы цвет. */
export const DEFAULT_HIGHLIGHT_COLOR: HighlightColor = "#FFDE66";

type RuleProfileState = {
  maskStyle: MaskStyle;
  /** Цвет фона маркера — только для стиля "marker", «Заливка» всегда чёрная на бэкенде. */
  highlightColor: HighlightColor;
  /** `null` = все встроенные типы, `[]` = ни одного, массив = выбранное подмножество. */
  enabledTypes: string[] | null;
  setMaskStyle: (style: MaskStyle) => void;
  setHighlightColor: (value: HighlightColor) => void;
  setEnabledTypes: (types: string[] | null) => void;
};

/**
 * Настройки текущей задачи обезличивания: как показывать маску в документе.
 *
 * Раньше здесь же жили `highlightChanges`/`keepTables`/`stableMarkers` —
 * три чекбокса в диалоге настроек, ни один из которых не уходил на бэкенд
 * (`useStartRun` их не читал вовсе). Убраны вместе с самим диалогом
 * (`mask-style-picker.tsx`) 23.09.2026 — тот же класс проблемы, что уже
 * был с `enabledTypes`/`preset` до этого: стор хранил решение, которое
 * никто не читал.
 */
export const useRuleProfileStore = create<RuleProfileState>((set) => ({
  maskStyle: "marker",
  highlightColor: DEFAULT_HIGHLIGHT_COLOR,
  enabledTypes: null,
  setMaskStyle: (maskStyle) => set({ maskStyle }),
  setHighlightColor: (highlightColor) => set({ highlightColor }),
  setEnabledTypes: (enabledTypes) => set({ enabledTypes }),
}));
