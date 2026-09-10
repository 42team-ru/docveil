import type { PiiDecisionKind } from "../../../entity/pii/model/types";
import { paintRun, type PaintState } from "./paint-run";

export type HighlightOccurrence = {
  id: string;
  groupId: string;
};

/** Форма, которую отдаёт любой резолвер привязки (docx: anchor-index.ts,
 * xlsx: xlsx-anchor-index.ts) — единственное, что здесь важно: удалось ли
 * найти узел DOM для вхождения. Откуда он взялся (абзац, ячейка) — заботы
 * конкретного вьюера, этому модулю всё равно. */
export type ResolvedRun =
  | { status: "resolved"; run: HTMLElement }
  | { status: "not-found" };

export type HighlightResult = {
  /** Раны, которые удалось привязать — по ним строится highlight-sync и клик. */
  runByOccurrenceId: Map<string, HTMLElement>;
  /** Вхождения без привязки — отображаются в панели без скролла к документу. */
  notFoundIds: Set<string>;
};

export function resolvePaintState(
  decision: PiiDecisionKind,
  viewMode: "all" | "original",
): PaintState {
  if (viewMode === "original") return "original";
  return decision;
}

/**
 * Первичная расстановка: для каждого привязанного узла проставляет
 * `data-pii-id`/`data-pii-group-id` и красит его в статусный цвет через
 * paintRun. Дальнейшие изменения решения/режима показа красит уже
 * `highlight-sync.ts` — этот модуль не подписывается на стор, только
 * расставляет один раз после рендера документа.
 *
 * Формат-агностично: сам поиск узла по вхождению (`index`) строит вызывающий
 * вьюер своим резолвером — docx через `anchor-index.ts` (поиск маркер-рана по
 * тексту абзаца), xlsx через `xlsx-anchor-index.ts` (прямой адрес по
 * координате ячейки). Здесь общая для обоих часть: покраска и учёт
 * непривязанных вхождений.
 */
export function applyHighlights(
  index: Map<string, ResolvedRun>,
  occurrences: HighlightOccurrence[],
  getDecision: (occurrenceId: string, groupId: string) => PiiDecisionKind,
  selectedOccurrenceId: string | null,
  viewMode: "all" | "original",
): HighlightResult {
  const runByOccurrenceId = new Map<string, HTMLElement>();
  const notFoundIds = new Set<string>();

  for (const occurrence of occurrences) {
    const resolution = index.get(occurrence.id);
    if (!resolution || resolution.status === "not-found") {
      notFoundIds.add(occurrence.id);
      continue;
    }

    const run = resolution.run;
    run.dataset.piiId = occurrence.id;
    run.dataset.piiGroupId = occurrence.groupId;
    const decision = getDecision(occurrence.id, occurrence.groupId);
    paintRun(
      run,
      resolvePaintState(decision, viewMode),
      occurrence.id === selectedOccurrenceId,
    );
    runByOccurrenceId.set(occurrence.id, run);
  }

  return { runByOccurrenceId, notFoundIds };
}
