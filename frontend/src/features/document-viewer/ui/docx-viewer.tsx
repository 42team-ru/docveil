import { renderAsync } from "docx-preview";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { VStack } from "@astryxdesign/core/Stack";

import type { PiiExtraction } from "../../../entity/pii/model/types";
import {
  buildAnchorIndex,
  parseDocxLocator,
  type DocxOutline,
} from "../lib/anchor-index";
import type { HighlightOccurrence } from "../lib/apply-highlights";
import { fixTableCellDirection } from "../lib/fix-table-cell-direction";
import { captureDocxSelection, type SelectionCapture } from "../lib/read-selection";
import { useDocumentRender } from "../lib/use-document-render";

type DocxViewerProps = {
  fileUrl: string;
  extraction: PiiExtraction;
  onNotFoundChange?: (ids: Set<string>) => void;
  onSelectionCapture?: (capture: SelectionCapture) => void;
};

async function renderDocx(host: HTMLElement, data: ArrayBuffer): Promise<void> {
  await renderAsync(data, host, undefined, {
    inWrapper: true,
    breakPages: false,
    renderHeaders: false,
    renderFooters: false,
    renderFootnotes: false,
    ignoreLastRenderedPageBreak: true,
    className: "docx",
  });
  fixTableCellDirection(host);
}

/**
 * Разложить отрендеренный документ на то, что адресуют локаторы бэкенда:
 * абзацы тела (`["body", N]` считает только прямые `w:p` тела, без абзацев
 * внутри таблиц) и верхнеуровневые таблицы (`["table", t, …]` считает только
 * их, вложенные бэкенд не разбирает вовсе).
 */
function outlineOf(host: HTMLElement): DocxOutline {
  return {
    bodyParagraphs: Array.from(host.querySelectorAll("p")).filter(
      (paragraph) => paragraph.closest("table") === null,
    ),
    tables: Array.from(host.querySelectorAll("table")).filter(
      (table) => table.parentElement?.closest("table") == null,
    ),
  };
}

function buildDocxIndex(host: HTMLElement, occurrences: HighlightOccurrence[]) {
  // occurrences здесь на деле FlatPiiOccurrence — anchor-index.ts нужны только
  // marker/anchor/порядок, остальные поля из HighlightOccurrence он не видит
  // благодаря структурной типизации TS.
  const inputs = (
    occurrences as unknown as {
      id: string;
      marker: string;
      anchor: { locator: (string | number)[] };
      segmentOrder: number;
      chunkStart: number;
    }[]
  ).flatMap((occurrence) => {
    const hint = parseDocxLocator(occurrence.anchor.locator);
    // Неизвестная форма локатора — вхождение остаётся непривязанным в панели.
    // Привязывать его наугад к нулевому абзацу хуже, чем показать not-found.
    if (!hint) return [];
    return [
      {
        id: occurrence.id,
        marker: occurrence.marker,
        hint,
        segmentOrder: occurrence.segmentOrder,
        chunkStart: occurrence.chunkStart,
      },
    ];
  });
  return buildAnchorIndex(outlineOf(host), inputs);
}

/**
 * Хост для docx-preview: `<VStack ref={hostRef} />` вместо `<div>` — Stack
 * пробрасывает `ref` на HTMLElement (node_modules/@astryxdesign/core/dist/
 * Stack/Stack.d.ts:31), поэтому правило Astryx «нет <div>» не нарушается, а
 * внутри хоста живёт DOM самого docx-preview, который мы не авторизуем как
 * JSX и не обязаны подгонять под компоненты дизайн-системы.
 */
export function DocxViewer({
  fileUrl,
  extraction,
  onNotFoundChange,
  onSelectionCapture,
}: DocxViewerProps) {
  const { hostRef, status } = useDocumentRender({
    fileUrl,
    extraction,
    render: renderDocx,
    buildIndex: buildDocxIndex,
    captureSelection: captureDocxSelection,
    onNotFoundChange,
    onSelectionCapture,
  });

  return (
    <VStack hAlign="center" padding={6} isScrollable height="100%">
      {status === "loading" ? <Skeleton height={800} width={720} /> : null}
      {status === "error" ? (
        <EmptyState
          title="Не удалось показать документ"
          description="Попробуйте обновить страницу или скачать файл и открыть его локально."
        />
      ) : null}
      <VStack
        ref={hostRef}
        width="100%"
        maxWidth={760}
        style={{ color: "var(--color-on-light)", colorScheme: "light" }}
      />
    </VStack>
  );
}
