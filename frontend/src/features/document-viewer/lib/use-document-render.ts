import { useEffect, useRef, useState, type RefObject } from "react";

import { flattenPiiOccurrences } from "../../../entity/pii/model/flatten";
import type { DocumentViewMode } from "../../../entity/pii/model/review-store";
import { appliedGroupDecision, useReviewStore } from "../../../entity/pii/model/review-store";
import type { ManualPiiOccurrence, PiiExtraction } from "../../../entity/pii/model/types";
import {
  applyHighlights,
  resolvePaintState,
  type HighlightOccurrence,
  type ResolvedRun,
} from "./apply-highlights";
import { subscribeHighlightSync } from "./highlight-sync";
import { unpaintManualHighlight } from "./manual-highlight";
import { paintRun } from "./paint-run";
import type { SelectionCapture } from "./read-selection";

export type DocumentRenderStatus = "loading" | "ready" | "error";

type UseDocumentRenderOptions = {
  fileUrl: string;
  extraction: PiiExtraction;
  /** Заполняет host DOM-содержимым документа (docx-preview / рендер таблицы
   * xlsx) и делает любые форматно-специфичные пост-фиксы (напр.
   * fixTableCellDirection для docx). Получает сигнал отмены: если он сработал
   * (cleanup эффекта), рендер должен прекратить добавлять элементы в host. */
  render: (host: HTMLElement, data: ArrayBuffer, signal: AbortSignal) => Promise<void>;
  /** Строит привязку occurrence → узел DOM после того, как host заполнен. */
  buildIndex: (
    host: HTMLElement,
    occurrences: HighlightOccurrence[],
  ) => Map<string, ResolvedRun>;
  /** Читает текущее выделение мыши внутри host в координату для «добавить пропущенное». */
  captureSelection: (host: HTMLElement) => SelectionCapture | null;
  /** Красит ручную отметку (`review-store.manualOccurrences`) прямо в host —
   * в отличие от `buildIndex`, создаёт новый узел, а не ищет существующий
   * (`manual-highlight.ts`). `null` — привязка не удалась (например, абзац
   * успел перерисоваться), тогда отметка просто не подсвечивается. */
  paintManualOccurrence?: (
    host: HTMLElement,
    occurrence: ManualPiiOccurrence,
    viewMode: DocumentViewMode,
  ) => HTMLElement | null;
  onNotFoundChange?: (ids: Set<string>) => void;
  onSelectionCapture?: (capture: SelectionCapture) => void;
};

type UseDocumentRenderResult = {
  hostRef: RefObject<HTMLElement | null>;
  status: DocumentRenderStatus;
};

/**
 * Общий цикл просмотра документа: загрузка файла, рендер, привязка ПДн к
 * DOM, покраска, подписка на решения (`highlight-sync.ts`) и делегированные
 * click/mouseup на хосте. Формат-специфичные шаги — как рендерить
 * (docx-preview / собственный рендер таблицы xlsx), как искать узел
 * (`anchor-index.ts` / `xlsx-anchor-index.ts`) и как читать выделение
 * (`captureDocxSelection` / `captureXlsxSelection`) — вьюер передаёт
 * колбэками. Один и тот же эффект обслуживает оба формата без дублирования
 * загрузки/подписки/клика.
 */
export function useDocumentRender({
  fileUrl,
  extraction,
  render,
  buildIndex,
  captureSelection,
  paintManualOccurrence,
  onNotFoundChange,
  onSelectionCapture,
}: UseDocumentRenderOptions): UseDocumentRenderResult {
  const hostRef = useRef<HTMLElement | null>(null);
  const [status, setStatus] = useState<DocumentRenderStatus>("loading");
  const select = useReviewStore((state) => state.select);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    let cancelled = false;
    const abortController = new AbortController();
    let cleanupSync: (() => void) | null = null;
    let cleanupManualSync: (() => void) | null = null;
    let handleClick: ((event: MouseEvent) => void) | null = null;
    let handleMouseUp: (() => void) | null = null;

    setStatus("loading");
    host.innerHTML = "";

    fetch(fileUrl, { signal: abortController.signal })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Не удалось загрузить документ: ${response.status}`);
        }
        return response.arrayBuffer();
      })
      .then((buffer) => {
        // Эффект уже пересоздан (в т.ч. двойной mount StrictMode в dev):
        // `render` пишет в host напрямую и сам сигнал не проверяет, поэтому
        // устаревший запуск не должен доходить до него — иначе в host
        // остаётся осиротевшая таблица без подсветки поверх свежей.
        if (cancelled) return undefined;
        return render(host, buffer, abortController.signal);
      })
      .then(() => {
        if (cancelled) return;

        const occurrences = flattenPiiOccurrences(extraction);
        const index = buildIndex(host, occurrences);
        // До перегенерации открытый файл остаётся последней опубликованной
        // версией: черновик не имеет права перекрашивать его как готовый.
        const getDecision = (_occurrenceId: string, groupId: string) =>
          appliedGroupDecision(useReviewStore.getState(), groupId);

        const { runByOccurrenceId, notFoundIds } = applyHighlights(
          index,
          occurrences,
          getDecision,
          useReviewStore.getState().selectedOccurrenceId,
          useReviewStore.getState().viewMode,
        );
        onNotFoundChange?.(notFoundIds);

        const targets = occurrences
          .filter((occurrence) => runByOccurrenceId.has(occurrence.id))
          .map((occurrence) => ({
            occurrenceId: occurrence.id,
            groupId: occurrence.groupId,
            run: runByOccurrenceId.get(occurrence.id) as HTMLElement,
          }));
        cleanupSync = subscribeHighlightSync(targets);

        if (paintManualOccurrence) {
          const painted = new Map<string, HTMLElement>();

          const paintOne = (occurrence: ManualPiiOccurrence) => {
            const run = paintManualOccurrence(host, occurrence, useReviewStore.getState().viewMode);
            if (run) painted.set(occurrence.id, run);
          };

          for (const occurrence of useReviewStore.getState().manualOccurrences) paintOne(occurrence);

          const unsubManual = useReviewStore.subscribe(
            (state) => state.manualOccurrences,
            (occurrences, previous) => {
              const nextIds = new Set(occurrences.map((o) => o.id));
              for (const prev of previous) {
                if (!nextIds.has(prev.id)) {
                  unpaintManualHighlight(host, prev.id);
                  painted.delete(prev.id);
                }
              }
              for (const occurrence of occurrences) {
                if (!painted.has(occurrence.id)) paintOne(occurrence);
              }
            },
          );
          const unsubManualViewMode = useReviewStore.subscribe(
            (state) => state.viewMode,
            (viewMode) => {
              for (const run of painted.values()) {
                paintRun(run, resolvePaintState("pending", viewMode), false);
              }
            },
          );
          cleanupManualSync = () => {
            unsubManual();
            unsubManualViewMode();
          };
        }

        handleClick = (event) => {
          const targetEl = event.target as HTMLElement;
          const run = targetEl.closest<HTMLElement>("[data-pii-id]");
          if (run?.dataset.piiId) {
            select(run.dataset.piiId);
            return;
          }
          // Secondary bbox divs (multi-region occurrences) carry data-pii-region-of
          // instead of data-pii-id. They should still select the same occurrence.
          const secondary = targetEl.closest<HTMLElement>("[data-pii-region-of]");
          if (secondary?.dataset.piiRegionOf) {
            select(secondary.dataset.piiRegionOf);
          }
        };
        host.addEventListener("click", handleClick);

        handleMouseUp = () => {
          const capture = captureSelection(host);
          if (capture) onSelectionCapture?.(capture);
        };
        host.addEventListener("mouseup", handleMouseUp);

        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });

    return () => {
      cancelled = true;
      abortController.abort();
      cleanupSync?.();
      cleanupManualSync?.();
      if (handleClick) host.removeEventListener("click", handleClick);
      if (handleMouseUp) host.removeEventListener("mouseup", handleMouseUp);
      host.innerHTML = "";
    };
    // Перестраиваем документ при смене файла и при смене разбора: раньше в
    // зависимостях был только `fileUrl`, и новая выдача по тому же файлу
    // оставляла на экране старую подсветку.
    //
    // Колбэки (`render`, `buildIndex`, `captureSelection`) в зависимости
    // намеренно не входят: вьюеры создают их заново на каждый рендер, и от их
    // добавления эффект зациклился бы. Мемоизировать их на стороне вьюеров —
    // отдельная правка, не эта.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileUrl, extraction]);

  return { hostRef, status };
}
