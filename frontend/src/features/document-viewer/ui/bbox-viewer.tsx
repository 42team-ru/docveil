import { useEffect, useRef, useState } from "react";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { VStack } from "@astryxdesign/core/Stack";

import type {
  PiiDocFormat,
  PiiExtraction,
  PiiPage,
} from "../../../entity/pii/model/types";
import type { HighlightOccurrence, ResolvedRun } from "../lib/apply-highlights";
import {
  normalizeDragRect,
  pixelRectToRegion,
  regionToPixelRect,
  type PixelRect,
} from "../lib/bbox-geometry";
import { paintManualRegionHighlight } from "../lib/manual-highlight";
import { loadPdfDocument, renderPdfPage } from "../lib/pdf-source";
import type { RegionSelectionCapture, SelectionCapture } from "../lib/read-selection";
import { useDocumentRender } from "../lib/use-document-render";

export type VisiblePageInfo = { current: number; total: number };

type BboxViewerProps = {
  format: PiiDocFormat;
  fileUrl: string;
  extraction: PiiExtraction;
  /** Размеры страниц готового артефакта — `report.pages[]`. Пусто, пока
   * отчёт не разобран: вьюер всё равно покажет документ, просто без bbox. */
  pages: PiiPage[];
  onNotFoundChange?: (ids: Set<string>) => void;
  onSelectionCapture?: (capture: SelectionCapture) => void;
  /** Страница, видимая по центру области прокрутки, для счётчика в тулбаре.
   * `null` — счётчик не нужен (один лист, docx/xlsx через этот вьюер не идут). */
  onVisiblePageChange?: (info: VisiblePageInfo | null) => void;
};

/** Атрибут страницы-контейнера: номер страницы 0-based, тот же, что в `regions[].page`. */
const PAGE_ATTR = "data-bbox-page";
/** Протяжка меньше этого в CSS px считается случайным кликом, не выделением. */
const MIN_DRAG_PX = 6;

const IMAGE_MIME: Partial<Record<PiiDocFormat, string>> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  tif: "image/tiff",
  tiff: "image/tiff",
};

/** Страница-контейнер: `position:relative` — система координат для оверлея
 * (найденные сущности и рамка протяжки) поверх канваса этой страницы. */
function createPageContainer(pageIndex: number): HTMLDivElement {
  const container = document.createElement("div");
  container.style.position = "relative";
  container.style.marginBottom = "12px";
  container.style.lineHeight = "0";
  container.setAttribute(PAGE_ATTR, String(pageIndex));
  return container;
}

function styleCanvas(canvas: HTMLCanvasElement): void {
  canvas.style.display = "block";
  canvas.style.maxWidth = "100%";
  canvas.style.height = "auto";
  canvas.style.border = "1px solid var(--color-border-default)";
}

async function renderImage(host: HTMLElement, data: ArrayBuffer, mime: string, signal: AbortSignal): Promise<void> {
  const bitmap = await createImageBitmap(new Blob([data], { type: mime }));
  if (signal.aborted) { bitmap.close(); return; }
  const container = createPageContainer(0);
  const canvas = document.createElement("canvas");
  styleCanvas(canvas);
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("bbox-viewer: canvas 2D context недоступен");
  context.drawImage(bitmap, 0, 0);
  bitmap.close();
  container.appendChild(canvas);
  host.appendChild(container);
}

async function renderPdf(host: HTMLElement, data: ArrayBuffer, signal: AbortSignal): Promise<void> {
  const doc = await loadPdfDocument(data);
  const scale = 1.5;
  for (let pageNumber = 1; pageNumber <= doc.numPages; pageNumber += 1) {
    if (signal.aborted) return;
    const container = createPageContainer(pageNumber - 1);
    const canvas = document.createElement("canvas");
    styleCanvas(canvas);
    container.appendChild(canvas);
    host.appendChild(container);
    // eslint-disable-next-line no-await-in-loop -- страницы рисуются по
    // порядку намеренно: параллельный рендер не экономит время (один поток
    // канваса), а страницы обязаны появляться сверху вниз.
    await renderPdfPage(doc, pageNumber, canvas, scale);
  }
}

function createMarkDiv(rectPx: { x: number; y: number; width: number; height: number }): HTMLDivElement {
  const div = document.createElement("div");
  div.style.position = "absolute";
  div.style.left = `${rectPx.x}px`;
  div.style.top = `${rectPx.y}px`;
  div.style.width = `${rectPx.width}px`;
  div.style.height = `${rectPx.height}px`;
  div.style.lineHeight = "normal";
  return div;
}

/**
 * Найденные сущности → прямоугольники-метки поверх соответствующей страницы.
 *
 * Одна сущность может иметь несколько `regions` (перенос текста через строку).
 * Первый регион — первичная метка, хранится в индексе как `run`; остальные
 * добавляются рядом с атрибутом `data-pii-region-of` и красятся из `paintRun`
 * автоматически.
 *
 * Три прохода, чтобы избежать layout thrashing:
 *   1. Читаем getBoundingClientRect всех страниц разом (один layout flush).
 *   2. Создаём div-ы и считаем пиксельные координаты (чистый JS, без DOM).
 *   3. Записываем все div-ы в DOM (только записи, без промежуточных чтений).
 */
function buildBboxIndex(
  host: HTMLElement,
  occurrences: HighlightOccurrence[],
): Map<string, ResolvedRun> {
  const typed = occurrences as unknown as {
    id: string;
    regions: { page: number; x0: number; y0: number; x1: number; y1: number }[];
  }[];

  // Проход 1: один layout flush — читаем размеры всех канвасов страниц сразу.
  type PageDims = { container: HTMLElement; pageW: number; pageH: number };
  const pageDims = new Map<number, PageDims>();
  for (const el of host.querySelectorAll<HTMLElement>(`[${PAGE_ATTR}]`)) {
    const page = Number(el.getAttribute(PAGE_ATTR));
    const canvas = el.querySelector("canvas");
    if (!canvas) continue;
    const { width: canvasW, height: canvasH } = canvas.getBoundingClientRect();
    const pageW = canvasW > 0 ? canvasW : canvas.width;
    const pageH = canvasH > 0 ? canvasH : canvas.height;
    if (pageW > 0 && pageH > 0) pageDims.set(page, { container: el, pageW, pageH });
  }

  // Проход 2: создаём div-ы (нет чтений из DOM).
  const index = new Map<string, ResolvedRun>();
  const pending: { container: HTMLElement; mark: HTMLDivElement }[] = [];

  for (const occurrence of typed) {
    const allRegions = occurrence.regions;
    if (!allRegions.length) {
      index.set(occurrence.id, { status: "not-found" });
      continue;
    }

    let primaryMark: HTMLDivElement | null = null;

    for (const region of allRegions) {
      const dims = pageDims.get(region.page);
      if (!dims) continue;

      const rectPx = regionToPixelRect(region, dims.pageW, dims.pageH);
      const mark = createMarkDiv(rectPx);
      mark.dataset.piiBbox = "true";
      if (!primaryMark) {
        primaryMark = mark;
      } else {
        mark.dataset.piiRegionOf = occurrence.id;
      }
      pending.push({ container: dims.container, mark });
    }

    index.set(
      occurrence.id,
      primaryMark ? { status: "resolved", run: primaryMark } : { status: "not-found" },
    );
  }

  // Проход 3: батчевая запись в DOM (нет чтений → нет дополнительных reflow).
  for (const { container, mark } of pending) {
    container.appendChild(mark);
  }

  return index;
}

type DragState = {
  page: number;
  canvas: HTMLCanvasElement;
  container: HTMLElement;
  startX: number;
  startY: number;
  currentX: number;
  currentY: number;
  rectEl: HTMLElement;
};

function createDragRectEl(rectPx: PixelRect): HTMLElement {
  const el = document.createElement("div");
  el.style.position = "absolute";
  el.style.left = `${rectPx.x}px`;
  el.style.top = `${rectPx.y}px`;
  el.style.width = `${rectPx.width}px`;
  el.style.height = `${rectPx.height}px`;
  el.style.border = "2px dashed var(--color-border-blue)";
  el.style.background = "var(--color-background-blue)";
  el.style.opacity = "0.35";
  el.style.pointerEvents = "none";
  return el;
}

/**
 * Протяжка мышью → выделение области (добавление маски рамкой). Слушатели
 * вешаются на каждый page-контейнер при рендере; drag-состояние живёт в
 * `dragRef`, который читает `captureSelection` на mouseup — тот же приём,
 * что делает `useDocumentRender` для текстового выделения (Selection API),
 * только источник координат другой (canvas, не DOM-текст).
 */
function attachDragHandlers(
  host: HTMLElement,
  dragRef: React.MutableRefObject<DragState | null>,
): void {
  const containers = Array.from(host.querySelectorAll<HTMLElement>(`[${PAGE_ATTR}]`));
  for (const container of containers) {
    const canvas = container.querySelector("canvas");
    if (!canvas) continue;
    const page = Number(container.getAttribute(PAGE_ATTR));

    container.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const bounds = container.getBoundingClientRect();
      const startX = event.clientX - bounds.left;
      const startY = event.clientY - bounds.top;
      const rectEl = createDragRectEl({ x: startX, y: startY, width: 0, height: 0 });
      container.appendChild(rectEl);
      dragRef.current = { page, canvas, container, startX, startY, currentX: startX, currentY: startY, rectEl };
    });

    container.addEventListener("pointermove", (event) => {
      const drag = dragRef.current;
      if (!drag || drag.container !== container) return;
      const bounds = container.getBoundingClientRect();
      drag.currentX = event.clientX - bounds.left;
      drag.currentY = event.clientY - bounds.top;
      const rectPx = normalizeDragRect(drag.startX, drag.startY, drag.currentX, drag.currentY);
      drag.rectEl.style.left = `${rectPx.x}px`;
      drag.rectEl.style.top = `${rectPx.y}px`;
      drag.rectEl.style.width = `${rectPx.width}px`;
      drag.rectEl.style.height = `${rectPx.height}px`;
    });
  }
}

function finishDrag(
  dragRef: React.MutableRefObject<DragState | null>,
): RegionSelectionCapture | null {
  const drag = dragRef.current;
  dragRef.current = null;
  if (!drag) return null;
  drag.rectEl.remove();

  const rectPx = normalizeDragRect(drag.startX, drag.startY, drag.currentX, drag.currentY);
  if (rectPx.width < MIN_DRAG_PX || rectPx.height < MIN_DRAG_PX) return null;

  const canvasWidth = drag.canvas.clientWidth;
  const canvasHeight = drag.canvas.clientHeight;
  if (canvasWidth <= 0 || canvasHeight <= 0) return null;

  const region = pixelRectToRegion(rectPx, drag.page, canvasWidth, canvasHeight);
  const viewportRect = drag.container.getBoundingClientRect();
  const rect = new DOMRect(
    viewportRect.left + rectPx.x,
    viewportRect.top + rectPx.y,
    rectPx.width,
    rectPx.height,
  );
  return { kind: "region", region, rect };
}

/**
 * Вьюер PDF и картинок — единый и для тех, и для других: разница только в
 * подложке (canvas из pdf.js постранично / картинка на одном канвасе), сама
 * подсветка и выделение работают через общий bbox-оверлей.
 *
 * Не использует `docx-preview`/`exceljs` подход «найти существующий узел
 * текста» — координаты найденных сущностей уже приезжают с бэкендом
 * (`report.entities[].regions`/`report.pages`, план feat/highlight-coords-
 * edits), поэтому вместо резолвера привязки здесь прямое позиционирование.
 */
export function BboxViewer({
  format,
  fileUrl,
  extraction,
  pages,
  onNotFoundChange,
  onSelectionCapture,
  onVisiblePageChange,
}: BboxViewerProps) {
  const isNarrow = useMediaQuery("(max-width: 768px)", false);
  const dragRef = useRef<DragState | null>(null);
  const containerRef = useRef<HTMLElement | null>(null);

  async function render(host: HTMLElement, data: ArrayBuffer, signal: AbortSignal): Promise<void> {
    const mime = IMAGE_MIME[format];
    if (mime) {
      await renderImage(host, data, mime, signal);
    } else {
      await renderPdf(host, data, signal);
    }
    if (!signal.aborted) {
      attachDragHandlers(host, dragRef);
    }
  }

  const { hostRef, status } = useDocumentRender({
    fileUrl,
    extraction,
    render,
    buildIndex: buildBboxIndex,
    captureSelection: () => finishDrag(dragRef),
    paintManualOccurrence: paintManualRegionHighlight,
    onNotFoundChange,
    onSelectionCapture,
  });

  // Счётчик страниц: какая страница сейчас по центру видимой области
  // прокрутки. Только тут — у docx/xlsx нет понятия страницы в этом
  // рендерере, `document-toolbar.tsx` просто не получает колбэк.
  useEffect(() => {
    if (status !== "ready") return;
    const host = hostRef.current;
    const root = containerRef.current;
    if (!host || !root) return;

    const pageEls = Array.from(host.querySelectorAll<HTMLElement>(`[${PAGE_ATTR}]`));
    const total = pageEls.length;
    if (total <= 1) {
      onVisiblePageChange?.(null);
      return;
    }

    const ratios = new Map<number, number>();
    const reportCurrent = () => {
      let bestPage = 0;
      let bestRatio = -1;
      for (const [page, ratio] of ratios) {
        if (ratio > bestRatio) {
          bestRatio = ratio;
          bestPage = page;
        }
      }
      onVisiblePageChange?.({ current: bestPage + 1, total });
    };

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const page = Number(entry.target.getAttribute(PAGE_ATTR));
          ratios.set(page, entry.intersectionRatio);
        }
        reportCurrent();
      },
      { root, threshold: [0, 0.25, 0.5, 0.75, 1] },
    );
    for (const el of pageEls) observer.observe(el);
    onVisiblePageChange?.({ current: 1, total });

    return () => {
      observer.disconnect();
      onVisiblePageChange?.(null);
    };
  }, [status, hostRef, onVisiblePageChange]);

  const hasPageDims = pages.length > 0;

  return (
    <VStack ref={containerRef} hAlign={isNarrow ? "start" : "center"} padding={3} isScrollable height="100%">
      {status === "loading" ? <Skeleton height={800} width="100%" /> : null}
      {status === "error" ? (
        <EmptyState
          title="Не удалось показать документ"
          description="Попробуйте обновить страницу или скачать файл и открыть его локально."
        />
      ) : null}
      {status === "ready" && !hasPageDims ? (
        <EmptyState
          isCompact
          title="Подсветка недоступна"
          description="У отчёта нет геометрии страниц — найденные значения не отмечены на листе, но документ открыт полностью."
        />
      ) : null}
      <VStack ref={hostRef} width="100%" maxWidth={900} />
    </VStack>
  );
}
