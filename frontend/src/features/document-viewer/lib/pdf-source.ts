import type { PDFDocumentProxy } from "pdfjs-dist";

/**
 * `pdfjs-dist` импортируется только динамически, изнутри вызова этой функции
 * — а вызывается она только из `useEffect` вьюера (`use-document-render.ts`
 * рендерит документ после монтирования, не при SSR). Топ-уровневый импорт в
 * `bbox-viewer.tsx` сломал бы серверную сборку: пакет трогает браузерные
 * глобали (`DOMMatrix`, воркеры) на уровне модуля.
 */
let workerConfigured = false;

async function pdfjs() {
  const lib = await import("pdfjs-dist");
  if (!workerConfigured) {
    // `new URL(...)` — способ Vite резолвить ассет из node_modules что при
    // сборке, что в dev-режиме; `?url`-импорт того же файла в динамическом
    // виде у части бандлеров резолвится нестабильно.
    lib.GlobalWorkerOptions.workerSrc = new URL(
      "pdfjs-dist/build/pdf.worker.min.mjs",
      import.meta.url,
    ).href;
    workerConfigured = true;
  }
  return lib;
}

/**
 * Открыть PDF из уже скачанных байт. `data` переходит во владение pdf.js
 * (detached после вызова) — вызывающий не должен читать буфер повторно.
 */
export async function loadPdfDocument(data: ArrayBuffer): Promise<PDFDocumentProxy> {
  const lib = await pdfjs();
  const task = lib.getDocument({ data });
  return task.promise;
}

/**
 * Отрендерить одну страницу (1-based, как в pdf.js) на канвас в заданном
 * масштабе. Возвращает размер страницы в CSS-пикселях канваса — тот же
 * базис, что нужен `bbox-geometry.ts` для перевода 0..1-регионов в пиксели.
 */
export async function renderPdfPage(
  doc: PDFDocumentProxy,
  pageNumber: number,
  canvas: HTMLCanvasElement,
  scale: number,
): Promise<{ widthPx: number; heightPx: number }> {
  const page = await doc.getPage(pageNumber);
  const viewport = page.getViewport({ scale });
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("pdf-source: canvas 2D context недоступен");
  }
  await page.render({ canvasContext: context, viewport, canvas }).promise;
  return { widthPx: viewport.width, heightPx: viewport.height };
}
