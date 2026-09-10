/** Тип персональных данных, который можно включить в маскирование. */
export type DataType = {
  id: string;
  name: string;
  /** Шаблон маркера, который встанет вместо значения. */
  marker: string;
};

/** Готовый профиль правил маскирования. */
export type RulePreset = {
  id: string;
  name: string;
  description: string;
};

/**
 * Как выглядит маска в выходном документе. Значения — те же, что у движка
 * (`_STYLE_BY_ROLE`, `backend/src/masker/graph/nodes.py`):
 * `marker` даёт артефакт `masked_highlight.*` (маркер с подсветкой),
 * `blackbox` — `masked_black.*` (сплошная заливка).
 */
export type MaskStyle = "marker" | "blackbox";
