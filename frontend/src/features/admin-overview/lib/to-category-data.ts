import { STATUS_LABEL } from "../../../entity/document/ui/run-status-token";
import type { RunStatus } from "../../masking-run/api/masking-run";
import {
  buildCategoryData,
  type CategoryDatum,
} from "../../../shared/ui/charts/category-bar-chart";

/** Порядок статусов в диаграмме — от «в работе» к «завершено», как в
 * `document-history/ui/history-filters.tsx#STATUS_ORDER`. */
const STATUS_ORDER: RunStatus[] = [
  "queued",
  "running",
  "awaiting_answers",
  "awaiting_review",
  "done",
  "leaked",
  "failed",
];

/** `AdminRunsStatsOut.by_status` → диаграмма, подписи и порядок — как в
 * фильтре журнала, чтобы статус читался одинаково по всему продукту. */
export function runStatusCategoryData(byStatus: Record<string, number>): CategoryDatum[] {
  return buildCategoryData(byStatus, STATUS_LABEL, STATUS_ORDER);
}

/** `AdminRunsStatsOut.by_format` → диаграмма; формат из бэкенда — нижний
 * регистр расширения (`pdf`), подпись — то же самое в верхнем. */
export function documentFormatCategoryData(byFormat: Record<string, number>): CategoryDatum[] {
  const labels = Object.fromEntries(
    Object.keys(byFormat).map((format) => [format, format.toUpperCase()]),
  );
  return buildCategoryData(byFormat, labels);
}

const MASK_STYLE_LABEL: Record<string, string> = {
  marker: "Маркер",
  blackbox: "Чёрный прямоугольник",
  both: "Маркер + прямоугольник",
};

/** `AdminOptionsStatsOut.by_mask_style` → диаграмма. */
export function maskStyleCategoryData(byMaskStyle: Record<string, number>): CategoryDatum[] {
  return buildCategoryData(byMaskStyle, MASK_STYLE_LABEL);
}
