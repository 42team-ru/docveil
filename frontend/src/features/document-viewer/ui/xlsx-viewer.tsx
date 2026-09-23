import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { VStack } from "@astryxdesign/core/Stack";

import type { PiiExtraction } from "../../../entity/pii/model/types";
import type { HighlightOccurrence } from "../lib/apply-highlights";
import { paintManualXlsxHighlight } from "../lib/manual-highlight";
import { captureXlsxSelection, type SelectionCapture } from "../lib/read-selection";
import { renderXlsxTable } from "../lib/render-xlsx-table";
import { useDocumentRender } from "../lib/use-document-render";
import { buildXlsxAnchorIndex } from "../lib/xlsx-anchor-index";

type XlsxViewerProps = {
  fileUrl: string;
  extraction: PiiExtraction;
  onNotFoundChange?: (ids: Set<string>) => void;
  onSelectionCapture?: (capture: SelectionCapture) => void;
};

function buildXlsxIndex(host: HTMLElement, occurrences: HighlightOccurrence[]) {
  const table = host.querySelector<HTMLTableElement>("table[data-sheet-name]");
  const sheetName = table?.dataset.sheetName ?? "";

  const cellByCoord = new Map<string, HTMLTableCellElement>();
  for (const cell of host.querySelectorAll<HTMLTableCellElement>("td[data-row][data-col]")) {
    cellByCoord.set(`${cell.dataset.row}:${cell.dataset.col}`, cell);
  }

  // occurrences здесь на деле FlatPiiOccurrence — резолверу нужны только
  // id/marker/anchor.locator, остальные поля скрыты структурной типизацией TS.
  const inputs = occurrences as unknown as {
    id: string;
    marker: string;
    anchor: { locator: (string | number)[] };
  }[];

  return buildXlsxAnchorIndex(sheetName, cellByCoord, inputs);
}

/**
 * Хост для сгенерированной таблицы: `<VStack ref={hostRef} />` вместо
 * `<div>` — тот же приём, что и в `docx-viewer.tsx`. Таблицу строит
 * `render-xlsx-table.ts` через `document.createElement`, поэтому она такое же
 * «чужое» содержимое хоста, как и вывод docx-preview — авторской JSX-разметки
 * в ней нет.
 */
export function XlsxViewer({
  fileUrl,
  extraction,
  onNotFoundChange,
  onSelectionCapture,
}: XlsxViewerProps) {
  const { hostRef, status } = useDocumentRender({
    fileUrl,
    extraction,
    render: renderXlsxTable,
    buildIndex: buildXlsxIndex,
    // Имя листа для локатора выделения читаем с уже отрисованной таблицы —
    // на момент mouseup рендер гарантированно завершён (иначе выделять нечего).
    captureSelection: (host) => {
      const table = host.querySelector<HTMLTableElement>("table[data-sheet-name]");
      return captureXlsxSelection(table?.dataset.sheetName ?? "")(host);
    },
    paintManualOccurrence: paintManualXlsxHighlight,
    onNotFoundChange,
    onSelectionCapture,
  });

  return (
    <VStack hAlign="start" padding={3} isScrollable height="100%">
      {status === "loading" ? <Skeleton height={400} width="100%" /> : null}
      {status === "error" ? (
        <EmptyState
          title="Не удалось показать таблицу"
          description="Попробуйте обновить страницу или скачать файл и открыть его локально."
        />
      ) : null}
      <VStack ref={hostRef} isScrollable width="100%" />
    </VStack>
  );
}
