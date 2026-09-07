import { useEffect, useMemo, useState } from "react";
import { FileBarChart2, Download, CheckCircle2 } from "lucide-react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Badge } from "@astryxdesign/core/Badge";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import {
  Layout,
  LayoutContent,
  LayoutHeader,
} from "@astryxdesign/core/Layout";
import { useToast } from "@astryxdesign/core/Toast";

import type { DocumentFormat } from "../../entity/document/model/types";
import { FormatToken } from "../../entity/document/ui/format-token";
import { flattenPiiOccurrences } from "../../entity/pii/model/flatten";
import { useReviewStore } from "../../entity/pii/model/review-store";
import {
  useConfirmedGroupCount,
  useTotalGroupCount,
} from "../../entity/pii/model/selectors";
import type { PiiType } from "../../entity/pii/model/types";
import { DocumentViewer } from "../../features/document-viewer/ui/document-viewer";
import type { SelectionCapture } from "../../features/document-viewer/lib/read-selection";
import { useReviewData } from "../../features/pii-review/api/use-review-data";
import { useReviewHotkeys } from "../../features/pii-review/lib/use-review-hotkeys";
import { DocumentToolbar } from "../../features/pii-review/ui/document-toolbar";
import { ReviewPanel } from "../../features/pii-review/ui/review-panel";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";

/** Экран ручной проверки замен: лист документа слева, решения — справа. */
export function ReviewPage() {
  const { extraction, document: reviewedDocument, report, ask } = useReviewData();

  const [notFoundIds, setNotFoundIds] = useState<Set<string>>(new Set());
  const [pendingSelection, setPendingSelection] = useState<SelectionCapture | null>(null);
  const [isPreviewNoticeVisible, setIsPreviewNoticeVisible] = useState(true);
  const showToast = useToast();

  const viewMode = useReviewStore((state) => state.viewMode);
  const setViewMode = useReviewStore((state) => state.setViewMode);
  const addManual = useReviewStore((state) => state.addManual);
  const setDocumentGroups = useReviewStore((state) => state.setDocumentGroups);

  const confirmedCount = useConfirmedGroupCount();
  const totalCount = useTotalGroupCount();
  const allConfirmed = confirmedCount === totalCount;

  const occurrences = useMemo(() => flattenPiiOccurrences(extraction), [extraction]);
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

  // Счётчики проверки живут в сторе и должны считать по открытому документу,
  // а не по фикстуре: без этого «N/M подтверждено» врало на всём, кроме
  // docx-фикстуры.
  const documentGroups = useMemo(() => {
    const minConfidence = new Map<string, number>();
    for (const occurrence of occurrences) {
      const known = minConfidence.get(occurrence.groupId);
      minConfidence.set(
        occurrence.groupId,
        known === undefined ? occurrence.confidence : Math.min(known, occurrence.confidence),
      );
    }
    return [...minConfidence].map(([id, confidence]) => ({
      id,
      minConfidence: confidence,
    }));
  }, [occurrences]);

  useEffect(() => {
    setDocumentGroups(documentGroups);
  }, [documentGroups, setDocumentGroups]);

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
    <ScreenLayout
      title={reviewedDocument.name}
      startContent={
        <FormatToken format={reviewedDocument.format.toUpperCase() as DocumentFormat} />
      }
      meta={
        <HStack gap={2} vAlign="center">
          <Badge
            variant={allConfirmed ? "success" : "neutral"}
            label={`${confirmedCount}/${totalCount} подтверждено`}
          />
        </HStack>
      }
      actions={
        <HStack gap={2}>
          <Button size="sm" variant="ghost" label="Отчёт" icon={<Icon icon={FileBarChart2} size="sm" />} href="/report" />
          <Button size="sm" variant="secondary" label="Скачать .pdf" icon={<Icon icon={Download} size="sm" />} />
          <Button
            size="sm"
            variant={allConfirmed ? "primary" : "secondary"}
            label="Утвердить документ"
            icon={<Icon icon={CheckCircle2} size="sm" />}
            onClick={() =>
              showToast({
                body: "Документ утверждён. Отправка на бэкенд появится вместе с реальным эндпоинтом.",
                type: "info",
              })
            }
          />
        </HStack>
      }
      contentPadding={0}
      isContentScrollable={false}
      panel={
        <ReviewPanel
          extraction={extraction}
          report={report}
          ask={ask}
          totalCount={totalCount}
          notFoundIds={notFoundIds}
        />
      }
    >
      <Layout
        height="fill"
        header={
          <LayoutHeader hasDivider>
            <VStack gap={0} width="100%">
              {isPreviewNoticeVisible ? (
                <Banner
                  status="warning"
                  container="section"
                  title="Предпросмотр документа"
                  description="Вёрстка, шрифты и разбиение на страницы — приближение к оригиналу. Итоговый файл для скачивания собирается отдельно и может отличаться от этого отображения."
                  isDismissable
                  onDismiss={() => setIsPreviewNoticeVisible(false)}
                />
              ) : null}
              <DocumentToolbar
                documentName={reviewedDocument.name}
                viewMode={viewMode}
                onViewModeChange={setViewMode}
                pendingSelection={pendingSelection}
                onAddManual={handleAddManual}
                onDismissSelection={() => setPendingSelection(null)}
              />
            </VStack>
          </LayoutHeader>
        }
        content={
          <LayoutContent padding={0} label="Лист документа">
            <DocumentViewer
              format={reviewedDocument.format}
              fileUrl={reviewedDocument.fileUrl}
              extraction={extraction}
              onNotFoundChange={setNotFoundIds}
              onSelectionCapture={setPendingSelection}
            />
          </LayoutContent>
        }
      />
    </ScreenLayout>
  );
}
