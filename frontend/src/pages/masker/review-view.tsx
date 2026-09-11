import { useMemo, useState } from "react";
import { Layout, LayoutContent, LayoutHeader } from "@astryxdesign/core/Layout";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import type { FlatPiiOccurrence } from "../../entity/pii/model/flatten";
import { useReviewStore } from "../../entity/pii/model/review-store";
import type {
  PiiExtraction,
  PiiPage,
  PiiType,
} from "../../entity/pii/model/types";
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
  /** Размеры страниц готового артефакта — нужны только bbox-вьюеру
   * (pdf/картинка); для docx/xlsx `DocumentViewer` их игнорирует. */
  pages: PiiPage[];
  hasUnappliedChanges: boolean;
  isRegenerating: boolean;
  onRegenerate: () => void;
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
  pages,
  hasUnappliedChanges,
  isRegenerating,
  onRegenerate,
  onNotFoundChange,
}: ReviewViewProps) {
  const [pendingSelection, setPendingSelection] =
    useState<SelectionCapture | null>(null);

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
  useReviewHotkeys(orderedOccurrenceIds);

  function handleAddManual({ type, text }: { type: PiiType; text: string }) {
    if (!pendingSelection) return;
    addManual({
      id: `manual-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      type,
      text,
      ...(pendingSelection.kind === "text"
        ? { anchor: pendingSelection.anchor }
        : { region: pendingSelection.region }),
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
          <VStack gap={0} height="100%">
            {hasUnappliedChanges || isRegenerating ? (
              <Banner
                container="section"
                status={isRegenerating ? "info" : "warning"}
                title={
                  <VStack gap={0}>
                    <Text type="label" weight="semibold">
                      {isRegenerating
                        ? "Перегенерируем файл"
                        : "Изменения не применены"}
                    </Text>
                    <Text type="supporting">
                      {isRegenerating
                        ? "Подождите: готовим новый документ и обновляем превью."
                        : "Чтобы применить изменения, перегенерируйте файл."}
                    </Text>
                  </VStack>
                }
                endContent={
                  <Button
                    size="sm"
                    variant="primary"
                    label="Перегенерировать файл"
                    isLoading={isRegenerating}
                    isDisabled={isRegenerating}
                    onClick={onRegenerate}
                  />
                }
              />
            ) : null}
            <DocumentViewer
              format={document.format}
              fileUrl={
                viewMode === "original"
                  ? document.originalFileUrl || document.fileUrl
                  : document.fileUrl
              }
              extraction={extraction}
              pages={pages}
              onNotFoundChange={onNotFoundChange}
              onSelectionCapture={setPendingSelection}
            />
          </VStack>
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
