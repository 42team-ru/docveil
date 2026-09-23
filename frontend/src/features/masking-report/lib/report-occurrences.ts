import { flattenPiiOccurrences, type FlatPiiOccurrence } from "../../../entity/pii/model/flatten";
import type { MaskingReport } from "../../../entity/pii/model/types";

/** Возвращает только вхождения, для которых итоговый отчёт выбрал маскирование. */
export function maskedOccurrences(report: MaskingReport): FlatPiiOccurrence[] {
  const actionByRef = new Map(
    (report.decisions?.byRef ?? []).map((decision) => [decision.ref, decision.action]),
  );

  return flattenPiiOccurrences(report.extraction).filter(
    (occurrence) => (actionByRef.get(occurrence.ref) ?? occurrence.action) === "mask",
  );
}
