/**
 * Как выглядит маска в выходном документе. Значения — те же, что у движка
 * (`_STYLE_BY_ROLE`, `backend/src/masker/graph/nodes.py`):
 * `marker` даёт артефакт `masked_highlight.*` (маркер с подсветкой),
 * `blackbox` — `masked_black.*` (сплошная заливка).
 */
export type MaskStyle = "marker" | "blackbox";
