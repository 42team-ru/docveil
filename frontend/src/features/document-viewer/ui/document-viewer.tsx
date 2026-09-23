import { lazy, Suspense } from "react";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { Spinner } from "@astryxdesign/core/Spinner";
import { VStack } from "@astryxdesign/core/Stack";

import type {
  PiiDocFormat,
  PiiExtraction,
  PiiPage,
} from "../../../entity/pii/model/types";
import type { SelectionCapture } from "../lib/read-selection";
import type { VisiblePageInfo } from "./bbox-viewer";
import { UnsupportedFormat } from "./unsupported-format";

// docx-preview, exceljs и pdfjs-dist тянут больше 1 МБ в бандл каждый (см.
// вывод `yarn build`) — динамический импорт, чтобы открывающий один формат
// не грузил остальные. Каждый формат уходит в свой чанк.
const DocxViewer = lazy(() =>
  import("./docx-viewer").then((m) => ({ default: m.DocxViewer })),
);
const XlsxViewer = lazy(() =>
  import("./xlsx-viewer").then((m) => ({ default: m.XlsxViewer })),
);
const BboxViewer = lazy(() =>
  import("./bbox-viewer").then((m) => ({ default: m.BboxViewer })),
);

/** Форматы, которые открываются через bbox-оверлей — pdf.js для PDF,
 * канвас-картинка для сканов; подсветка идёт по координатам из отчёта, а не
 * по поиску узла DOM. */
const BBOX_FORMATS: PiiDocFormat[] = [
  "pdf",
  "jpg",
  "jpeg",
  "png",
  "tif",
  "tiff",
];

type DocumentViewerProps = {
  format: PiiDocFormat;
  fileUrl: string;
  extraction: PiiExtraction;
  /** Размеры страниц готового артефакта — нужны только `BboxViewer`; для
   * docx/xlsx игнорируются. */
  pages?: PiiPage[];
  onNotFoundChange?: (ids: Set<string>) => void;
  onSelectionCapture?: (capture: SelectionCapture) => void;
  /** Только для bbox-форматов (pdf/скан) — у docx/xlsx странице неоткуда взяться. */
  onVisiblePageChange?: (info: VisiblePageInfo | null) => void;
};

/** Диспетчер по формату документа — единственная точка входа для страницы. */
export function DocumentViewer({
  format,
  fileUrl,
  extraction,
  pages,
  ...handlers
}: DocumentViewerProps) {
  // Пустой адрес — это не сбой: пока прогон стоит на вопросах, узел `render`
  // не выполнялся и обезличенного файла ещё нет. Грузить пустой URL нельзя.
  if (!fileUrl) {
    return (
      <VStack hAlign="center" vAlign="center" padding={6} height="100%">
        <EmptyState
          isCompact
          icon={<Spinner size="lg" />}
          title="Документ загружается"
          description="Подождите: готовим файл для проверки."
        />
      </VStack>
    );
  }

  if (format === "docx" || format === "xlsx") {
    const Viewer = format === "docx" ? DocxViewer : XlsxViewer;
    return (
      <Suspense
        fallback={
          <VStack hAlign="center" padding={3} height="100%">
            <Skeleton height={400} width="100%" />
          </VStack>
        }
      >
        <Viewer fileUrl={fileUrl} extraction={extraction} {...handlers} />
      </Suspense>
    );
  }

  if (BBOX_FORMATS.includes(format)) {
    return (
      <Suspense
        fallback={
          <VStack hAlign="center" padding={3} height="100%">
            <Skeleton height={400} width="100%" />
          </VStack>
        }
      >
        <BboxViewer
          format={format}
          fileUrl={fileUrl}
          extraction={extraction}
          pages={pages ?? []}
          {...handlers}
        />
      </Suspense>
    );
  }

  return <UnsupportedFormat format={format} fileUrl={fileUrl} />;
}
