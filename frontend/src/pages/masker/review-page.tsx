import { useEffect, useMemo, useState } from "react";
import { FileBarChart2, Download, CheckCircle2 } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Badge } from "@astryxdesign/core/Badge";
import { HStack } from "@astryxdesign/core/Stack";
import {
  Layout,
  LayoutContent,
  LayoutHeader,
} from "@astryxdesign/core/Layout";
import { useToast } from "@astryxdesign/core/Toast";

import type { DocumentFormat } from "../../entity/document/model/types";
import { FormatToken } from "../../entity/document/ui/format-token";
import { flattenPiiOccurrences } from "../../entity/pii/model/flatten";
import { buildReviewEdits } from "../../entity/pii/model/review-edits";
import { useReviewStore } from "../../entity/pii/model/review-store";
import {
  useConfirmedGroupCount,
  useTotalGroupCount,
} from "../../entity/pii/model/selectors";
import type { PiiType } from "../../entity/pii/model/types";
import { DocumentViewer } from "../../features/document-viewer/ui/document-viewer";
import {
  downloadArtifact,
  hasRunResult,
  useSubmitReview,
} from "../../features/masking-run/api/masking-run";
import type { SelectionCapture } from "../../features/document-viewer/lib/read-selection";
import { useReviewData } from "../../features/pii-review/api/use-review-data";
import { useReviewHotkeys } from "../../features/pii-review/lib/use-review-hotkeys";
import { DocumentToolbar } from "../../features/pii-review/ui/document-toolbar";
import { ReviewPanel } from "../../features/pii-review/ui/review-panel";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";

/** Экран ручной проверки замен: лист документа слева, решения — справа. */
export function ReviewPage() {
  const {
    runId,
    status,
    extraction,
    document: reviewedDocument,
    report,
    ask,
  } = useReviewData();

  const [notFoundIds, setNotFoundIds] = useState<Set<string>>(new Set());
  const [pendingSelection, setPendingSelection] = useState<SelectionCapture | null>(null);
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

  const ready = hasRunResult(status);
  const submitReview = useSubmitReview(runId);

  /**
   * Утверждение документа. Правки уходят вторым прерыванием в граф, и
   * документ пересобирается там же — интерфейс ничего не «применяет» сам,
   * поэтому маркеры остаются согласованными, а результат заново проверяется
   * на утечки.
   */
  function handleApprove() {
    const state = useReviewStore.getState();
    submitReview.mutate(buildReviewEdits(extraction, state), {
      onSuccess: () =>
        showToast({
          body: "Правки приняты: документ пересобирается с ними",
          type: "info",
        }),
      onError: () =>
        showToast({
          body: "Прогон уже не ждёт правок — обновите страницу",
          type: "error",
        }),
    });
  }

  /** Скачивает подсвеченный вариант — тот же файл, что открыт во вьюере. */
  async function handleDownload() {
    if (runId === null) return;
    try {
      await downloadArtifact(runId, "masked_highlight", reviewedDocument.name);
    } catch {
      showToast({ body: "Не удалось скачать обезличенный документ", type: "error" });
    }
  }

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
          <Button
            size="sm"
            variant="ghost"
            label="Отчёт"
            icon={<Icon icon={FileBarChart2} size="sm" />}
            href={runId ? `/report?run=${runId}` : "/report"}
          />
          <Button
            size="sm"
            variant="secondary"
            label="Скачать"
            icon={<Icon icon={Download} size="sm" />}
            isDisabled={!ready}
            onClick={() => void handleDownload()}
          />
          <Button
            size="sm"
            variant={allConfirmed ? "primary" : "secondary"}
            label="Утвердить документ"
            icon={<Icon icon={CheckCircle2} size="sm" />}
            isDisabled={status !== "awaiting_review" || submitReview.isPending}
            isLoading={submitReview.isPending}
            onClick={handleApprove}
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
          runId={runId}
          totalCount={totalCount}
          notFoundIds={notFoundIds}
        />
      }
    >
      <Layout
        height="fill"
        header={
          <LayoutHeader hasDivider>
            <DocumentToolbar
              documentName={reviewedDocument.name}
              viewMode={viewMode}
              onViewModeChange={setViewMode}
              pendingSelection={pendingSelection}
              onAddManual={handleAddManual}
              onDismissSelection={() => setPendingSelection(null)}
            />
          </LayoutHeader>
        }
        content={
          <LayoutContent padding={0} label="Лист документа">
            <DocumentViewer
              format={reviewedDocument.format}
              fileUrl={
                viewMode === "original"
                  ? reviewedDocument.originalFileUrl || reviewedDocument.fileUrl
                  : reviewedDocument.fileUrl
              }
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
