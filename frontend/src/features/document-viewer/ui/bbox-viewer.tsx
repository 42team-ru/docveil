import { useRef } from "react";
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
  primaryRegion,
  regionToPixelRect,
  type PixelRect,
} from "../lib/bbox-geometry";
import { loadPdfDocument, renderPdfPage } from "../lib/pdf-source";
import type { RegionSelectionCapture, SelectionCapture } from "../lib/read-selection";
import { useDocumentRender } from "../lib/use-document-render";

type BboxViewerProps = {
  format: PiiDocFormat;
  fileUrl: string;
  extraction: PiiExtraction;
  /** Размеры страниц готового артефакта — `report.pages[]`. Пусто, пока
   * отчёт не разобран: вьюер всё равно покажет документ, просто без bbox. */
  pages: PiiPage[];
  onNotFoundChange?: (ids: Set<string>) => void;
  onSelectionCapture?: (capture: SelectionCapture) => void;
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

async function renderImage(host: HTMLElement, data: ArrayBuffer, mime: string): Promise<void> {
  const bitmap = await createImageBitmap(new Blob([data], { type: mime }));
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

async function renderPdf(host: HTMLElement, data: ArrayBuffer): Promise<void> {
  const doc = await loadPdfDocument(data);
  const scale = 1.5;
  for (let pageNumber = 1; pageNumber <= doc.numPages; pageNumber += 1) {
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

/** Найденные сущности → прямоугольники-метки поверх соответствующей страницы. */
function buildBboxIndex(
  host: HTMLElement,
  occurrences: HighlightOccurrence[],
): Map<string, ResolvedRun> {
  // occurrences здесь на деле FlatPiiOccurrence — той же структурной
  // типизацией, что и в docx/xlsx-вьюерах (см. docx-viewer.tsx).
  const typed = occurrences as unknown as {
    id: string;
    regions: { page: number; x0: number; y0: number; x1: number; y1: number }[];
  }[];
  const index = new Map<string, ResolvedRun>();

  for (const occurrence of typed) {
    const region = primaryRegion(occurrence.regions);
    const container = region
      ? host.querySelector<HTMLElement>(`[${PAGE_ATTR}="${region.page}"]`)
      : null;
    const canvas = container?.querySelector("canvas");
    if (!region || !container || !canvas) {
      index.set(occurrence.id, { status: "not-found" });
      continue;
    }
    const rectPx = regionToPixelRect(region, canvas.clientWidth, canvas.clientHeight);
    const mark = document.createElement("div");
    mark.style.position = "absolute";
    mark.style.left = `${rectPx.x}px`;
    mark.style.top = `${rectPx.y}px`;
    mark.style.width = `${rectPx.width}px`;
    mark.style.height = `${rectPx.height}px`;
    mark.style.lineHeight = "normal";
    container.appendChild(mark);
    index.set(occurrence.id, { status: "resolved", run: mark });
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
}: BboxViewerProps) {
  const dragRef = useRef<DragState | null>(null);

  async function render(host: HTMLElement, data: ArrayBuffer): Promise<void> {
    const mime = IMAGE_MIME[format];
    if (mime) {
      await renderImage(host, data, mime);
    } else {
      await renderPdf(host, data);
    }
    attachDragHandlers(host, dragRef);
  }

  const { hostRef, status } = useDocumentRender({
    fileUrl,
    extraction,
    render,
    buildIndex: buildBboxIndex,
    captureSelection: () => finishDrag(dragRef),
    onNotFoundChange,
    onSelectionCapture,
  });

  const hasPageDims = pages.length > 0;

  return (
    <VStack hAlign="center" padding={6} isScrollable height="100%">
      {status === "loading" ? <Skeleton height={800} width={720} /> : null}
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
