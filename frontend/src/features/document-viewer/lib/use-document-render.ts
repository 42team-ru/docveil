import { useEffect, useRef, useState, type RefObject } from "react";

import { flattenPiiOccurrences } from "../../../entity/pii/model/flatten";
import { useReviewStore } from "../../../entity/pii/model/review-store";
import type { PiiExtraction } from "../../../entity/pii/model/types";
import { applyHighlights, type HighlightOccurrence, type ResolvedRun } from "./apply-highlights";
import { subscribeHighlightSync } from "./highlight-sync";
import type { SelectionCapture } from "./read-selection";

export type DocumentRenderStatus = "loading" | "ready" | "error";

type UseDocumentRenderOptions = {
  fileUrl: string;
  extraction: PiiExtraction;
  /** Заполняет host DOM-содержимым документа (docx-preview / рендер таблицы
   * xlsx) и делает любые форматно-специфичные пост-фиксы (напр.
   * fixTableCellDirection для docx). */
  render: (host: HTMLElement, data: ArrayBuffer) => Promise<void>;
  /** Строит привязку occurrence → узел DOM после того, как host заполнен. */
  buildIndex: (
    host: HTMLElement,
    occurrences: HighlightOccurrence[],
  ) => Map<string, ResolvedRun>;
  /** Читает текущее выделение мыши внутри host в координату для «добавить пропущенное». */
  captureSelection: (host: HTMLElement) => SelectionCapture | null;
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
    let cleanupSync: (() => void) | null = null;
    let handleClick: ((event: MouseEvent) => void) | null = null;
    let handleMouseUp: (() => void) | null = null;

    setStatus("loading");
    host.innerHTML = "";

    fetch(fileUrl)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Не удалось загрузить документ: ${response.status}`);
        }
        return response.arrayBuffer();
      })
      .then((buffer) => render(host, buffer))
      .then(() => {
        if (cancelled) return;

        const occurrences = flattenPiiOccurrences(extraction);
        const index = buildIndex(host, occurrences);
        const getDecision = (_occurrenceId: string, groupId: string) =>
          useReviewStore.getState().groupDecisions[groupId] ?? "pending";

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

        handleClick = (event) => {
          const targetEl = event.target as HTMLElement;
          const run = targetEl.closest<HTMLElement>("[data-pii-id]");
          if (run?.dataset.piiId) {
            select(run.dataset.piiId);
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
      cleanupSync?.();
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
