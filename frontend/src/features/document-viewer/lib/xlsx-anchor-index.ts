/**
 * Привязка вхождений ПДн к ячейкам уже отрисованной xlsx-таблицы.
 *
 * В отличие от docx, здесь нет промежуточного слоя вроде docx-preview,
 * который мы не контролируем — таблицу строит наш собственный
 * `render-xlsx-table.ts`, поэтому каждая ячейка уже несёт точный адрес
 * (`data-row`/`data-col`) в момент создания. Задача не «искать», а
 * «посмотреть по ключу» — на порядок проще, чем монотонное выравнивание
 * абзацев в docx.
 *
 * Единственный источник риска — форма `anchor.locator` для xlsx ещё не
 * подтверждена бэкендом (реального примера JSON нет, в отличие от docx).
 * Design-допущение: `["sheet", <имя листа>, <row>, <col>]`, 1-based, тем же
 * счётом, что использует exceljs. Если бэкенд считает иначе — координата не
 * совпадёт, и резолвер падает на подстраховку: точный поиск ячейки с текстом,
 * равным `marker`, по всему листу. Не найдено — `not-found`, как и в docx:
 * вхождение остаётся в панели без привязки, а не привязывается наугад.
 */

import type { ResolvedRun } from "./apply-highlights";

export type XlsxAnchorOccurrenceInput = {
  id: string;
  marker: string;
  anchor: { locator: (string | number)[] };
};

function parseLocator(
  locator: (string | number)[],
): { sheetName: string; row: number; col: number } | null {
  if (locator[0] !== "sheet") return null;
  const sheetName = locator[1];
  const row = Number(locator[2]);
  const col = Number(locator[3]);
  if (typeof sheetName !== "string" || !Number.isFinite(row) || !Number.isFinite(col)) {
    return null;
  }
  return { sheetName, row, col };
}

export function buildXlsxAnchorIndex(
  sheetName: string,
  cellByCoord: Map<string, HTMLTableCellElement>,
  occurrences: XlsxAnchorOccurrenceInput[],
): Map<string, ResolvedRun> {
  const result = new Map<string, ResolvedRun>();
  const occupied = new Set<HTMLTableCellElement>();

  const findByMarkerText = (marker: string): HTMLTableCellElement | null => {
    for (const cell of cellByCoord.values()) {
      if (occupied.has(cell)) continue;
      if ((cell.textContent ?? "").trim() === marker) return cell;
    }
    return null;
  };

  for (const occurrence of occurrences) {
    const parsed = parseLocator(occurrence.anchor.locator);

    let cell: HTMLTableCellElement | null = null;
    if (parsed && parsed.sheetName === sheetName) {
      const candidate = cellByCoord.get(`${parsed.row}:${parsed.col}`);
      if (candidate && (candidate.textContent ?? "").trim() === occurrence.marker && !occupied.has(candidate)) {
        cell = candidate;
      }
    }

    if (!cell) {
      cell = findByMarkerText(occurrence.marker);
    }

    if (!cell) {
      result.set(occurrence.id, { status: "not-found" });
      continue;
    }

    occupied.add(cell);
    result.set(occurrence.id, { status: "resolved", run: cell });
  }

  return result;
}
