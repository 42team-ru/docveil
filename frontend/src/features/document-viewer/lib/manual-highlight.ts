import type { ManualPiiOccurrence } from "../../../entity/pii/model/types";
import { resolvePaintState } from "./apply-highlights";
import { regionToPixelRect } from "./bbox-geometry";
import { paintRun } from "./paint-run";

/**
 * Подсветка ручных отметок (`review-store.manualOccurrences`) прямо в
 * документе — отдельно от `apply-highlights.ts`/`anchor-index.ts`, которые
 * ищут уже вписанный бэкендом маркер в готовом ране. У ручной отметки
 * маркера ещё нет (см. пояснение в `pii-list-tab.tsx`): движок узнает о ней
 * только после перегенерации. Поэтому здесь не поиск существующего узла, а
 * создание нового — оборачивание выбранного текста в свежий `<span>` (docx/
 * xlsx) либо новый оверлей поверх страницы (bbox: pdf/картинка).
 *
 * Красится состоянием `"pending"` того же `paint-run.ts` — семантически
 * верно: как и решение оператора, ручная отметка ещё не применена к файлу,
 * `hasUnappliedChanges` уже считает её черновиком (`document-page.tsx`).
 */

const PAGE_ATTR = "data-bbox-page";

/** Найти первое вхождение `needle` среди текстовых узлов `block` и обернуть его в `<span>`.
 * `null` — совпадения нет (текст не нашёлся, например абзац успели перерисовать). */
function wrapTextInBlock(block: Element, needle: string): HTMLElement | null {
  if (!needle) return null;

  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
  const textNodes: Text[] = [];
  let fullText = "";
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const textNode = node as Text;
    textNodes.push(textNode);
    fullText += textNode.data;
  }

  const start = fullText.indexOf(needle);
  if (start === -1) return null;
  const end = start + needle.length;

  let pos = 0;
  let startNode: Text | null = null;
  let startOffset = 0;
  let endNode: Text | null = null;
  let endOffset = 0;
  for (const textNode of textNodes) {
    const len = textNode.data.length;
    if (startNode === null && start < pos + len) {
      startNode = textNode;
      startOffset = start - pos;
    }
    if (endNode === null && end <= pos + len) {
      endNode = textNode;
      endOffset = end - pos;
    }
    pos += len;
    if (startNode && endNode) break;
  }
  // Совпадение упирается в конец последнего текстового узла ровно на границе.
  if (startNode && !endNode && pos === end) {
    endNode = textNodes[textNodes.length - 1] ?? null;
    endOffset = endNode?.data.length ?? 0;
  }
  if (!startNode || !endNode) return null;

  const range = document.createRange();
  range.setStart(startNode, startOffset);
  range.setEnd(endNode, endOffset);

  const span = document.createElement("span");
  span.appendChild(range.extractContents());
  range.insertNode(span);
  return span;
}

/** docx: абзац по тому же глобальному индексу `querySelectorAll("p")`, каким его увидел `captureDocxSelection`. */
export function paintManualDocxHighlight(
  host: HTMLElement,
  occurrence: ManualPiiOccurrence,
  viewMode: "all" | "original",
): HTMLElement | null {
  if (!occurrence.anchor || occurrence.anchor.format !== "docx") return null;
  const index = Number(occurrence.anchor.locator[1]);
  const paragraph = host.querySelectorAll("p")[index];
  if (!paragraph) return null;

  const span = wrapTextInBlock(paragraph, occurrence.text);
  if (!span) return null;

  span.dataset.piiId = occurrence.id;
  span.dataset.piiManual = "true";
  paintRun(span, resolvePaintState("pending", viewMode), false);
  return span;
}

/** xlsx: ячейка по `data-row`/`data-col`, которые проставляет `render-xlsx-table.ts`. */
export function paintManualXlsxHighlight(
  host: HTMLElement,
  occurrence: ManualPiiOccurrence,
  viewMode: "all" | "original",
): HTMLElement | null {
  if (!occurrence.anchor || occurrence.anchor.format !== "xlsx") return null;
  const [, , row, col] = occurrence.anchor.locator;
  const cell = host.querySelector<HTMLElement>(
    `td[data-row="${CSS.escape(String(row))}"][data-col="${CSS.escape(String(col))}"]`,
  );
  if (!cell) return null;

  const span = wrapTextInBlock(cell, occurrence.text);
  if (!span) return null;

  span.dataset.piiId = occurrence.id;
  span.dataset.piiManual = "true";
  paintRun(span, resolvePaintState("pending", viewMode), false);
  return span;
}

/** bbox (pdf/картинка): та же геометрия, что и у найденных сущностей
 * (`bbox-viewer.tsx`'s `buildBboxIndex`) — оверлей поверх канваса страницы. */
export function paintManualRegionHighlight(
  host: HTMLElement,
  occurrence: ManualPiiOccurrence,
  viewMode: "all" | "original",
): HTMLElement | null {
  const region = occurrence.region;
  if (!region) return null;

  const container = host.querySelector<HTMLElement>(`[${PAGE_ATTR}="${region.page}"]`);
  const canvas = container?.querySelector("canvas");
  if (!container || !canvas) return null;

  const { width: pageW, height: pageH } = canvas.getBoundingClientRect();
  if (pageW <= 0 || pageH <= 0) return null;

  const rectPx = regionToPixelRect(region, pageW, pageH);
  const mark = document.createElement("div");
  mark.style.position = "absolute";
  mark.style.left = `${rectPx.x}px`;
  mark.style.top = `${rectPx.y}px`;
  mark.style.width = `${rectPx.width}px`;
  mark.style.height = `${rectPx.height}px`;
  mark.style.lineHeight = "normal";
  mark.dataset.piiId = occurrence.id;
  mark.dataset.piiManual = "true";
  container.appendChild(mark);
  paintRun(mark, resolvePaintState("pending", viewMode), false);
  return mark;
}

/** Снять подсветку убранной вручную отметки: сбросить покраску и перестать
 * откликаться на клики. Для текстовых `<span>` — не разворачиваем DOM назад
 * (риск задеть соседние раны сильнее, чем польза от точного восстановления
 * текстовых узлов): пустой неокрашенный span вокруг исходного текста ничем
 * не отличается от текста без него. */
export function unpaintManualHighlight(host: HTMLElement, occurrenceId: string): void {
  const el = host.querySelector<HTMLElement>(`[data-pii-id="${CSS.escape(occurrenceId)}"]`);
  if (!el) return;
  if (el.tagName === "DIV") {
    // bbox-оверлей — синтетический div без исходного содержимого, просто убрать его.
    el.remove();
    return;
  }
  // Текстовая обёртка (docx/xlsx) — оставляем span вокруг исходного текста
  // нейтральным, а не разворачиваем DOM обратно: риск задеть соседний ран
  // выше пользы от точного восстановления текстовых узлов.
  delete el.dataset.piiId;
  delete el.dataset.piiManual;
  paintRun(el, "original", false);
}
