import { useMemo, useState } from "react";
import {
  Layout,
  LayoutContent,
  LayoutHeader,
} from "@astryxdesign/core/Layout";

import type { FlatPiiOccurrence } from "../../entity/pii/model/flatten";
import { useReviewStore } from "../../entity/pii/model/review-store";
import type { PiiExtraction, PiiType } from "../../entity/pii/model/types";
import { DocumentViewer } from "../../features/document-viewer/ui/document-viewer";
import type { SelectionCapture } from "../../features/document-viewer/lib/read-selection";
import type { ReviewedDocument } from "../../features/pii-review/api/use-review-data";
import { useReviewHotkeys } from "../../features/pii-review/lib/use-review-hotkeys";
import { AddPiiTrigger } from "../../features/pii-review/ui/add-pii-trigger";
import { DocumentToolbar } from "../../features/pii-review/ui/document-toolbar";

type ReviewViewProps = {
  document: ReviewedDocument;
  extraction: PiiExtraction;
  /** Плоские вхождения документа — общие для счётчиков и хоткеев. */
  occurrences: FlatPiiOccurrence[];
  onNotFoundChange: (ids: Set<string>) => void;
};

/**
 * Тело вкладки «Проверка»: лист документа и тулбар режима просмотра.
 * Горячие клавиши живут здесь же — на вкладке «Отчёт» им листать нечего.
 */
export function ReviewView({
  document,
  extraction,
  occurrences,
  onNotFoundChange,
}: ReviewViewProps) {
  const [pendingSelection, setPendingSelection] = useState<SelectionCapture | null>(null);

  const viewMode = useReviewStore((state) => state.viewMode);
  const setViewMode = useReviewStore((state) => state.setViewMode);
  const addManual = useReviewStore((state) => state.addManual);

  const orderedOccurrenceIds = useMemo(
    () =>
      [...occurrences]
        .sort((a, b) =>
          a.segmentOrder !== b.segmentOrder
            ? a.segmentOrder - b.segmentOrder
            : a.chunkStart - b.chunkStart,
        )
        .map((o) => o.id),
    [occurrences],
  );
  const groupIdByOccurrenceId = useMemo(
    () => new Map(occurrences.map((o) => [o.id, o.groupId])),
    [occurrences],
  );

  useReviewHotkeys(orderedOccurrenceIds, groupIdByOccurrenceId);

  function handleAddManual(type: PiiType) {
    if (!pendingSelection) return;
    addManual({
      id: `manual-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      type,
      text: pendingSelection.text,
      anchor: pendingSelection.anchor,
    });
    setPendingSelection(null);
  }

  return (
    <Layout
      height="fill"
      header={
        <LayoutHeader hasDivider>
          <DocumentToolbar
            documentName={document.name}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
          />
        </LayoutHeader>
      }
      content={
        <LayoutContent padding={0} label="Лист документа">
          <DocumentViewer
            format={document.format}
            fileUrl={
              viewMode === "original"
                ? document.originalFileUrl || document.fileUrl
                : document.fileUrl
            }
            extraction={extraction}
            onNotFoundChange={onNotFoundChange}
            onSelectionCapture={setPendingSelection}
          />
          <AddPiiTrigger
            capture={pendingSelection}
            onAdd={handleAddManual}
            onDismiss={() => setPendingSelection(null)}
          />
        </LayoutContent>
      }
    />
  );
}
