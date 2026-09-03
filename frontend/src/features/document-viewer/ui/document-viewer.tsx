import { lazy, Suspense } from "react";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { VStack } from "@astryxdesign/core/Stack";

import type { PiiDocFormat, PiiExtraction } from "../../../entity/pii/model/types";
import type { SelectionCapture } from "../lib/read-selection";
import { UnsupportedFormat } from "./unsupported-format";

// docx-preview и exceljs вместе тянут больше 1 МБ в бандл (см. вывод `yarn
// build`) — динамический импорт, чтобы открывающий DOCX не грузил exceljs и
// наоборот. Каждый формат уходит в свой чанк.
const DocxViewer = lazy(() =>
  import("./docx-viewer").then((m) => ({ default: m.DocxViewer })),
);
const XlsxViewer = lazy(() =>
  import("./xlsx-viewer").then((m) => ({ default: m.XlsxViewer })),
);

type DocumentViewerProps = {
  format: PiiDocFormat;
  fileUrl: string;
  extraction: PiiExtraction;
  onNotFoundChange?: (ids: Set<string>) => void;
  onSelectionCapture?: (capture: SelectionCapture) => void;
};

/** Диспетчер по формату документа — единственная точка входа для страницы. */
export function DocumentViewer({ format, fileUrl, extraction, ...handlers }: DocumentViewerProps) {
  if (format === "docx" || format === "xlsx") {
    const Viewer = format === "docx" ? DocxViewer : XlsxViewer;
    return (
      <Suspense
        fallback={
          <VStack hAlign="center" padding={6} height="100%">
            <Skeleton height={400} width={600} />
          </VStack>
        }
      >
        <Viewer fileUrl={fileUrl} extraction={extraction} {...handlers} />
      </Suspense>
    );
  }

  return <UnsupportedFormat format={format} fileUrl={fileUrl} />;
}
