import type { RunListItem } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";

/** Первые записи ответа журнала уже отсортированы API от нового прогона к старому. */
export function recentRuns(
  runs: RunListItem[],
  limit = 5,
): RunListItem[] {
  return runs.slice(0, limit);
}
