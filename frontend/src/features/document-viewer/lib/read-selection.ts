import type { PiiAnchor } from "../../../entity/pii/model/types";

/** Захваченное выделение мышью — текст, готовый якорь для «добавить пропущенное»
 * и координаты выделения в вьюпорте, чтобы показать кнопку добавления рядом с ним. */
export type SelectionCapture = {
  text: string;
  anchor: PiiAnchor;
  rect: DOMRect;
};

/**
 * Текст текущего выделения (Selection API) внутри хоста документа, ближайший
 * элемент, подходящий под `blockSelector`, и рамка выделения в координатах
 * вьюпорта (для позиционирования плавающей кнопки). Формат-агностичное ядро:
 * не знает про абзацы docx или ячейки xlsx — эту интерпретацию делают
 * `captureDocxSelection`/`captureXlsxSelection` ниже.
 */
function readSelectedBlock(
  host: HTMLElement,
  blockSelector: string,
): { text: string; block: Element; rect: DOMRect } | null {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
    return null;
  }

  const range = selection.getRangeAt(0);
  if (!host.contains(range.commonAncestorContainer)) {
    return null;
  }

  const text = range.toString().trim();
  if (!text) {
    return null;
  }

  const container = range.commonAncestorContainer;
  const element =
    container.nodeType === Node.ELEMENT_NODE
      ? (container as Element)
      : container.parentElement;
  const block = element?.closest(blockSelector);
  if (!block) {
    return null;
  }

  return { text, block, rect: range.getBoundingClientRect() };
}

/** docx: блок — абзац, локатор — его индекс среди querySelectorAll("p"). */
export function captureDocxSelection(host: HTMLElement): SelectionCapture | null {
  const found = readSelectedBlock(host, "p");
  if (!found) return null;

  const paragraphs = Array.from(host.querySelectorAll("p"));
  const index = paragraphs.indexOf(found.block as HTMLParagraphElement);
  if (index === -1) return null;

  return {
    text: found.text,
    anchor: {
      format: "docx",
      label: `абзац ${index + 1}`,
      locator: ["body", index],
    },
    rect: found.rect,
  };
}

/** xlsx: блок — ячейка, локатор — координата из `data-row`/`data-col`,
 * которые `render-xlsx-table.ts` проставляет на каждый `<td>`. */
export function captureXlsxSelection(
  sheetName: string,
): (host: HTMLElement) => SelectionCapture | null {
  return (host) => {
    const found = readSelectedBlock(host, "td");
    if (!found) return null;

    const cell = found.block as HTMLElement;
    const row = cell.dataset.row;
    const col = cell.dataset.col;
    if (!row || !col) return null;

    return {
      text: found.text,
      anchor: {
        format: "xlsx",
        label: `${sheetName}!R${row}C${col}`,
        locator: ["sheet", sheetName, Number(row), Number(col)],
      },
      rect: found.rect,
    };
  };
}
