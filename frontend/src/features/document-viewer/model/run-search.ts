import type { SearchableItem } from "@astryxdesign/core/Typeahead";

import type { RunListItem } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";

export type RunSearchItem = SearchableItem<RunListItem>;

const REVIEWABLE_STATUSES: ReadonlySet<RunListItem["status"]> = new Set([
  "awaiting_review",
  "done",
]);

/** Оставляет только прогоны, для которых собран документ для ручной проверки. */
export function toReviewableRunSearchItems(items: RunListItem[]): RunSearchItem[] {
  return items
    .filter((run) => REVIEWABLE_STATUSES.has(run.status))
    .map((run) => ({
      id: run.id,
      label: run.document.name,
      auxiliaryData: run,
    }));
}
