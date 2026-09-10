import { flattenPiiOccurrences } from "./flatten";
import type {
  ManualPiiOccurrence,
  PiiDecisionKind,
  PiiExtraction,
  PiiType,
} from "./types";

/** Правки оператора в форме, которую разбирает `masker.graph.review`. */
export type ReviewEdits = {
  /** `{ref: "mask"|"keep"}` — решение по конкретной ссылке отчёта. */
  decisions: Record<string, "mask" | "keep">;
  /** `{ref: type_id}` — поправленный тип; маркер пересоберёт движок. */
  type_overrides: Record<string, string>;
  /** Значения, которые движок пропустил, а оператор нашёл глазами. */
  manual: { type: string; text: string }[];
};

type ReviewState = {
  groupDecisions: Record<string, PiiDecisionKind>;
  typeOverrides: Record<string, PiiType>;
  occurrenceTypeOverrides: Record<string, PiiType>;
  manualOccurrences: ManualPiiOccurrence[];
};

/**
 * Переводит решения оператора из состояния экрана в правки для графа.
 *
 * Единица решения на стороне движка — ссылка `ref`, а не группа: групповые
 * решения оператора разворачиваются по вхождениям здесь, ровно как движок
 * разворачивает ответы по типам и профилям в решения по ссылкам. Второго
 * понятия «группа» на бэкенде заводить незачем.
 *
 * Три правила, продиктованные поведением движка:
 *
 * 1. `pending` не отправляется вовсе. Молчание значит «решение движка в
 *    силе»; отправить `mask` за оператора, который ничего не нажал, значит
 *    приписать ему согласие.
 * 2. Адресное переопределение типа сильнее группового — тот же порядок, что
 *    и `DECISION_PRECEDENCE` на бэкенде: персональное решение по сущности
 *    сильнее решения по её группе.
 * 3. Снятие маски с критичного типа здесь не фильтруется. Это решает
 *    движок (`critical_guard`), и подменять его проверкой в интерфейсе —
 *    значит завести второе место, где живёт защита критичных данных.
 */
export function buildReviewEdits(
  extraction: PiiExtraction,
  state: ReviewState,
): ReviewEdits {
  const occurrences = flattenPiiOccurrences(extraction);

  const decisions: Record<string, "mask" | "keep"> = {};
  const typeOverrides: Record<string, string> = {};

  for (const occurrence of occurrences) {
    const decision = state.groupDecisions[occurrence.groupId];
    if (decision === "confirmed") decisions[occurrence.ref] = "mask";
    if (decision === "rejected") decisions[occurrence.ref] = "keep";

    const groupType = state.typeOverrides[occurrence.groupId];
    if (groupType) typeOverrides[occurrence.ref] = groupType;

    const ownType = state.occurrenceTypeOverrides[occurrence.id];
    if (ownType) typeOverrides[occurrence.ref] = ownType;
  }

  return {
    decisions,
    type_overrides: typeOverrides,
    manual: state.manualOccurrences.map((item) => ({
      type: item.type,
      text: item.text,
    })),
  };
}
