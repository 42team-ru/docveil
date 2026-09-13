import ExcelJS from "exceljs";

function cellKey(row: number, col: number): string {
  return `${row}:${col}`;
}

/** Excel хранит ширину столбца в «символах» дефолтного шрифта; общепринятое
 * приближение для рендера в браузере — 7px на символ плюс отступы ячейки. */
function columnWidthToPx(excelWidth: number | undefined): number {
  const width = excelWidth ?? 8.43;
  return Math.round(width * 7 + 5);
}

function pointsToPx(points: number | undefined, fallback: number): number {
  return Math.round((points ?? fallback) * (96 / 72));
}

function argbToCss(argb: string | undefined): string | null {
  if (!argb || argb.length !== 8) return null;
  const alpha = parseInt(argb.slice(0, 2), 16) / 255;
  const r = argb.slice(2, 4);
  const g = argb.slice(4, 6);
  const b = argb.slice(6, 8);
  return `rgba(${parseInt(r, 16)}, ${parseInt(g, 16)}, ${parseInt(b, 16)}, ${alpha.toFixed(2)})`;
}

function applyFill(cell: HTMLTableCellElement, fill: ExcelJS.Fill | undefined): void {
  if (!fill || fill.type !== "pattern" || fill.pattern !== "solid") return;
  const color = "fgColor" in fill ? argbToCss(fill.fgColor?.argb) : null;
  if (color) cell.style.backgroundColor = color;
}

function applyFont(cell: HTMLTableCellElement, font: Partial<ExcelJS.Font> | undefined): void {
  if (!font) return;
  if (font.bold) cell.style.fontWeight = "bold";
  if (font.italic) cell.style.fontStyle = "italic";
  if (font.size) cell.style.fontSize = `${font.size}pt`;
  const color = argbToCss(font.color?.argb);
  if (color) cell.style.color = color;
}

const BORDER_STYLE: Record<string, string> = {
  thin: "1px solid",
  medium: "2px solid",
  thick: "3px solid",
  dashed: "1px dashed",
  dotted: "1px dotted",
  double: "3px double",
};

function applyBorder(cell: HTMLTableCellElement, border: Partial<ExcelJS.Borders> | undefined): void {
  if (!border) return;
  const sides: Array<[keyof ExcelJS.Borders, keyof CSSStyleDeclaration]> = [
    ["top", "borderTop"],
    ["left", "borderLeft"],
    ["bottom", "borderBottom"],
    ["right", "borderRight"],
  ];
  for (const [side, cssProp] of sides) {
    const spec = border[side];
    if (!spec?.style) continue;
    const style = BORDER_STYLE[spec.style] ?? "1px solid";
    const color = argbToCss(spec.color?.argb) ?? "rgb(0, 0, 0)";
    // CSSStyleDeclaration — индексная сигнатура строкового доступа, TS не
    // видит её как строго типизируемую по конкретному ключу без приведения.
    (cell.style as unknown as Record<string, string>)[cssProp as string] = `${style} ${color}`;
  }
}

/**
 * Парсит `worksheet.model.merges` ("A1:F1") в диапазон 1-based координат.
 * exceljs не даёт готового парсера ссылок, а строить полноценный A1-парсер
 * ради одной операции незачем — нужен только этот частный случай.
 */
function parseMergeRange(ref: string): { r1: number; c1: number; r2: number; c2: number } | null {
  const match = /^([A-Z]+)(\d+):([A-Z]+)(\d+)$/.exec(ref);
  if (!match) return null;
  const [, colA, rowA, colB, rowB] = match;
  return {
    r1: Number(rowA),
    c1: columnLettersToNumber(colA),
    r2: Number(rowB),
    c2: columnLettersToNumber(colB),
  };
}

function columnLettersToNumber(letters: string): number {
  let n = 0;
  for (const char of letters) {
    n = n * 26 + (char.charCodeAt(0) - 64);
  }
  return n;
}

/**
 * Строит настоящую HTML-таблицу из первого листа книги — так же, как
 * docx-preview рендерит настоящий DOM для docx, только рендерер здесь наш
 * собственный: Astryx `Table` рассчитан на однородные колонки данных (его
 * же документация прямо отговаривает от таблиц без единообразных колонок —
 * `astryx component Table`), а склеенные ячейки и заливки — content самой
 * таблицы, не оформление поверх него.
 *
 * v1: рендерит только первый лист книги (`workbook.worksheets[0]`).
 * Многолистовые книги — за пределами этой итерации, как pdf для DocumentViewer.
 */
export async function renderXlsxTable(host: HTMLElement, data: ArrayBuffer, _signal: AbortSignal): Promise<void> {
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(data);

  const worksheet = workbook.worksheets[0];
  if (!worksheet) {
    throw new Error("В книге нет ни одного листа");
  }

  const merges = (worksheet.model.merges ?? [])
    .map(parseMergeRange)
    .filter((m): m is NonNullable<typeof m> => m !== null);
  const mergeStartByCoord = new Map(merges.map((m) => [cellKey(m.r1, m.c1), m]));
  const coveredByMerge = new Set(
    merges.flatMap((m) => {
      const covered: string[] = [];
      for (let r = m.r1; r <= m.r2; r++) {
        for (let c = m.c1; c <= m.c2; c++) {
          if (r === m.r1 && c === m.c1) continue;
          covered.push(cellKey(r, c));
        }
      }
      return covered;
    }),
  );

  const table = document.createElement("table");
  // sheetName — на table, а не только в замыкании: buildXlsxIndex ищет его
  // заново по DOM (render/buildIndex в use-document-render.ts не делятся
  // состоянием напрямую, только через host), так резолвер остаётся простой
  // функцией (host, occurrences) => index, как и docx-резолвер.
  table.dataset.sheetName = worksheet.name;
  table.style.borderCollapse = "collapse";
  table.style.backgroundColor = "rgb(255, 255, 255)";
  table.style.color = "rgb(0, 0, 0)";
  table.style.fontFamily = "Calibri, Arial, sans-serif";
  table.style.fontSize = "11pt";

  const colgroup = document.createElement("colgroup");
  const columnCount = worksheet.columnCount;
  for (let c = 1; c <= columnCount; c++) {
    const col = document.createElement("col");
    col.style.width = `${columnWidthToPx(worksheet.getColumn(c).width)}px`;
    colgroup.appendChild(col);
  }
  table.appendChild(colgroup);

  const tbody = document.createElement("tbody");

  for (let r = 1; r <= worksheet.rowCount; r++) {
    const row = worksheet.getRow(r);
    const tr = document.createElement("tr");
    tr.style.height = `${pointsToPx(row.height, 15)}px`;

    for (let c = 1; c <= columnCount; c++) {
      const key = cellKey(r, c);
      if (coveredByMerge.has(key)) continue;

      const cell = row.getCell(c);
      const td = document.createElement("td");
      td.dataset.row = String(r);
      td.dataset.col = String(c);
      td.style.padding = "2px 6px";
      td.style.verticalAlign = "middle";
      td.textContent = cell.text ?? "";

      const merge = mergeStartByCoord.get(key);
      if (merge) {
        if (merge.r2 > merge.r1) td.rowSpan = merge.r2 - merge.r1 + 1;
        if (merge.c2 > merge.c1) td.colSpan = merge.c2 - merge.c1 + 1;
      }

      applyFill(td, cell.fill);
      applyFont(td, cell.font);
      applyBorder(td, cell.border);
      if (cell.alignment?.horizontal) td.style.textAlign = cell.alignment.horizontal;
      if (cell.alignment?.vertical) {
        td.style.verticalAlign = cell.alignment.vertical === "middle" ? "middle" : cell.alignment.vertical;
      }

      tr.appendChild(td);
    }

    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  host.appendChild(table);
}
