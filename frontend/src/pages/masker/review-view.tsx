import { useState } from "react";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Layout, LayoutContent, LayoutHeader } from "@astryxdesign/core/Layout";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { useReviewStore } from "../../entity/pii/model/review-store";
import type {
  PiiExtraction,
  PiiPage,
  PiiType,
} from "../../entity/pii/model/types";
import { DocumentViewer } from "../../features/document-viewer/ui/document-viewer";
import type { VisiblePageInfo } from "../../features/document-viewer/ui/bbox-viewer";
import type { SelectionCapture } from "../../features/document-viewer/lib/read-selection";
import type { ReviewedDocument } from "../../features/pii-review/api/use-review-data";
import { AddPiiTrigger } from "../../features/pii-review/ui/add-pii-trigger";
import { DocumentToolbar } from "../../features/pii-review/ui/document-toolbar";

type ReviewViewProps = {
  document: ReviewedDocument;
  extraction: PiiExtraction;
  /** Размеры страниц готового артефакта — нужны только bbox-вьюеру
   * (pdf/картинка); для docx/xlsx `DocumentViewer` их игнорирует. */
  pages: PiiPage[];
  hasUnappliedChanges: boolean;
  isRegenerating: boolean;
  onRegenerate: () => void;
  onDiscardChanges: () => void;
  onNotFoundChange: (ids: Set<string>) => void;
};

/**
 * Тело вкладки «Проверка»: лист документа и тулбар режима просмотра.
 */
export function ReviewView({
  document,
  extraction,
  pages,
  hasUnappliedChanges,
  isRegenerating,
  onRegenerate,
  onDiscardChanges,
  onNotFoundChange,
}: ReviewViewProps) {
  const [pendingSelection, setPendingSelection] =
    useState<SelectionCapture | null>(null);
  const [pageInfo, setPageInfo] = useState<VisiblePageInfo | null>(null);
  const [isDiscardDialogOpen, setIsDiscardDialogOpen] = useState(false);
  const [isApplyDialogOpen, setIsApplyDialogOpen] = useState(false);

  const viewMode = useReviewStore((state) => state.viewMode);
  const setViewMode = useReviewStore((state) => state.setViewMode);
  const addManual = useReviewStore((state) => state.addManual);

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

  function handleDiscardChanges() {
    setPendingSelection(null);
    onDiscardChanges();
  }

  function confirmDiscardChanges() {
    setIsDiscardDialogOpen(false);
    handleDiscardChanges();
  }

  function confirmApplyChanges() {
    setIsApplyDialogOpen(false);
    onRegenerate();
  }

  return (
    <>
      <Layout
        height="fill"
        header={
          <LayoutHeader hasDivider>
            <DocumentToolbar
              viewMode={viewMode}
              onViewModeChange={setViewMode}
              pageInfo={pageInfo}
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
                    <HStack gap={2} wrap="wrap">
                      {hasUnappliedChanges && !isRegenerating ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          label="Отменить изменения"
                          onClick={() => setIsDiscardDialogOpen(true)}
                        />
                      ) : null}
                      <Button
                        size="sm"
                        variant="primary"
                        label="Перегенерировать файл"
                        isLoading={isRegenerating}
                        isDisabled={isRegenerating}
                        onClick={() => setIsApplyDialogOpen(true)}
                      />
                    </HStack>
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
                onVisiblePageChange={setPageInfo}
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
      <AlertDialog
        isOpen={isDiscardDialogOpen}
        onOpenChange={setIsDiscardDialogOpen}
        title="Отменить изменения?"
        description="Черновые решения, изменения типов и ручные отметки будут удалены. Уже собранный файл не изменится."
        cancelLabel="Вернуться"
        actionLabel="Да, отменить"
        actionVariant="destructive"
        onAction={confirmDiscardChanges}
      />
      <AlertDialog
        isOpen={isApplyDialogOpen}
        onOpenChange={setIsApplyDialogOpen}
        title="Применить изменения?"
        description="Будет собрана новая версия обезличенного файла с текущими решениями. Предпросмотр обновится после завершения обработки."
        cancelLabel="Продолжить проверку"
        actionLabel="Применить и пересобрать"
        actionVariant="primary"
        onAction={confirmApplyChanges}
      />
    </>
  );
}
