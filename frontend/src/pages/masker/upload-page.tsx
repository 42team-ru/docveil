import { useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Play } from "lucide-react";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { useToast } from "@astryxdesign/core/Toast";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import {
  Layout,
  LayoutContent,
  LayoutHeader,
  LayoutPanel,
} from "@astryxdesign/core/Layout";
import { Icon } from "@astryxdesign/core/Icon";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { useUploadQueueStore } from "../../entity/document/model/upload-queue-store";
import { useRuleProfileStore } from "../../entity/rule-profile/model/rule-profile-store";
import { RecentDocuments } from "../../features/document-history/ui/recent-documents";
import { useStartRun } from "../../features/masking-run/api/masking-run";
import { CustomTypesCompilerDialog } from "../../features/custom-types-compiler/ui/compiler-dialog";
import { useCustomTypesStore } from "../../features/custom-types-compiler/model/store";
import { hasAnyTypeSelected } from "../../features/document-upload/lib/masking-type-selection";
import { MaskStylePicker } from "../../features/document-upload/ui/mask-style-picker";
import { UploadDropzone } from "../../features/document-upload/ui/upload-dropzone";
import { UploadQueue } from "../../features/document-upload/ui/upload-queue";
import { pluralRu } from "../../shared/lib/plural-ru";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";
import { uploadApiFilesUploadPost } from "../../shared/api/generated/core/files/files";

/** Ширина правой колонки настроек — структурный размер региона. */
const SETTINGS_WIDTH = 380;

/** Шаг 1: что обезличиваем и по каким правилам. */
export function UploadPage() {
  const navigate = useNavigate();
  const showToast = useToast();

  const items = useUploadQueueStore((state) => state.items);
  const markStarting = useUploadQueueStore((state) => state.markStarting);
  const markStarted = useUploadQueueStore((state) => state.markStarted);
  const markFailed = useUploadQueueStore((state) => state.markFailed);
  const clearQueue = useUploadQueueStore((state) => state.clear);

  const maskStyle = useRuleProfileStore((state) => state.maskStyle);
  const enabledTypes = useRuleProfileStore((state) => state.enabledTypes);
  const highlightColor = useRuleProfileStore((state) => state.highlightColor);

  const customTypes = useCustomTypesStore((state) => state.types);
  const hasSelectedTypes = hasAnyTypeSelected(enabledTypes, customTypes.length);

  const [isCompilerOpen, setIsCompilerOpen] = useState(false);
  const [compilerObjectName, setCompilerObjectName] = useState<string | null>(null);
  const [isUploadingForCompiler, setIsUploadingForCompiler] = useState(false);

  const startRun = useStartRun();
  // Кандидаты на (повторную) отправку: всё, что ещё не заведено прогоном —
  // включая уже упавшие файлы, их можно отправить повторно тем же кликом.
  const submittable = items.filter(
    (item) => item.state === "pending" || item.state === "failed",
  );
  // «Готово» в шапке очереди — только по-настоящему свободные от ошибки
  // файлы, а не всё, что уйдёт по кнопке (которая retry-ит и упавшие).
  const readyCount = items.filter((item) => item.state === "pending").length;

  const [isSubmitting, setIsStarting] = useState(false);
  const isStarting =
    isSubmitting || items.some((item) => item.state === "starting");
  const startingRef = useRef(false);

  // Ниже 1024px фиксированная боковая панель настроек сжимает основной
  // столбец до нечитаемой ширины — на таких экранах очередь и кнопка
  // отправки переезжают под основной контент, без бокового региона.
  const isNarrow = useMediaQuery("(max-width: 1024px)", false);

  /**
   * Загружает первый файл из очереди в MinIO (если ещё не загружен) и открывает
   * диалог компилятора кастомных типов.
   */
  async function handleOpenCompiler() {
    const item = submittable[0] ?? items[0];
    if (!item) {
      showToast({ body: "Сначала добавьте файл в очередь", type: "info" });
      return;
    }
    if (item.source.kind === "existing") {
      setCompilerObjectName(item.source.objectName);
      setIsCompilerOpen(true);
      return;
    }
    setIsUploadingForCompiler(true);
    try {
      const uploaded = await uploadApiFilesUploadPost({ file: item.source.file });
      if (uploaded.status === 200) {
        setCompilerObjectName(uploaded.data.object_name);
        setIsCompilerOpen(true);
      } else {
        showToast({ body: "Не удалось загрузить файл для компилятора", type: "error" });
      }
    } catch {
      showToast({ body: "Не удалось загрузить файл для компилятора", type: "error" });
    } finally {
      setIsUploadingForCompiler(false);
    }
  }

  /**
   * Один прогон на документ: движок принимает файл, а не пачку. Файлы
   * заводятся по очереди, чтобы порядок прогонов в журнале совпадал с
   * порядком в очереди, а первый открылся на проверку.
   */
  async function handleStart() {
    if (startingRef.current || submittable.length === 0 || !hasSelectedTypes) return;
    startingRef.current = true;
    setIsStarting(true);
    let firstRunId: string | null = null;
    let failedCount = 0;

    for (const item of submittable) markStarting(item.id);
    for (const item of submittable) {
      try {
        const run = await startRun.mutateAsync({
          source: item.source,
          maskStyle,
          types: enabledTypes,
          customTypes,
          highlightColor,
        });
        markStarted(item.id, run.id);
        if (firstRunId === null) {
          firstRunId = run.id;
          void navigate(`/documents/${run.id}`, {
            state: {
              uploadIds: submittable.map((upload) => upload.id),
              chooseUpload: submittable.length > 1,
            },
            viewTransition: true,
          });
        }
      } catch (error) {
        failedCount += 1;
        markFailed(
          item.id,
          error instanceof Error ? error.message : "не удалось запустить",
        );
      }
    }

    startingRef.current = false;
    setIsStarting(false);

    if (firstRunId === null) {
      showToast({
        body: "Ни один файл не удалось отправить на обезличивание",
        type: "error",
      });
      return;
    }
    if (failedCount > 0) {
      // Частичный сбой — не только полный: без этого тоста оператор
      // не узнаёт, что часть файлов осталась в очереди с ошибкой, потому
      // что экран уже переключился на проверку первого успешного прогона.
      showToast({
        body: `Не удалось запустить ${failedCount} ${pluralRu(failedCount, ["файл", "файла", "файлов"])} из ${submittable.length} — они остались в очереди с описанием ошибки`,
        type: "error",
      });
    }
  }

  const queueHeader = (
    <HStack gap={3} vAlign="center" paddingInline={4} paddingBlock={4}>
      <Text type="label" weight="semibold">
        Очередь файлов
      </Text>
      <StackItem size="fill" />
      <Text type="supporting" color="secondary" size="sm">
        {`${readyCount} готово`}
      </Text>
      {items.length > 0 ? (
        <Button
          size="sm"
          variant="ghost"
          label="Очистить"
          isDisabled={isStarting}
          onClick={clearQueue}
        />
      ) : null}
    </HStack>
  );

  const submitButton = (
    <Button
      variant="primary"
      size="lg"
      width="100%"
      icon={<Icon icon={Play} size="sm" />}
      label={
        submittable.length === 1
          ? "Обезличить документ"
          : `Обезличить ${submittable.length} ${pluralRu(submittable.length, ["документ", "документа", "документов"])}`
      }
      isDisabled={submittable.length === 0 || !hasSelectedTypes || isStarting}
      isLoading={isStarting}
      onClick={() => void handleStart()}
    />
  );

  return (
    <>
    <ScreenLayout
      title="Новый документ"
      contentPadding={0}
      isContentScrollable={false}
      panel={
        isNarrow ? undefined : (
          <LayoutPanel
            width={SETTINGS_WIDTH}
            hasDivider
            padding={0}
            isScrollable={false}
            label="Настройки задачи"
          >
            <Layout
              height="fill"
              header={<LayoutHeader hasDivider padding={0}>{queueHeader}</LayoutHeader>}
              content={
                <LayoutContent padding={6} isScrollable label="Очередь">
                  <VStack gap={4} height="100%">
                    <StackItem size="fill">
                      <UploadQueue />
                    </StackItem>
                    <VStack gap={3}>{submitButton}</VStack>
                  </VStack>
                </LayoutContent>
              }
            />
          </LayoutPanel>
        )
      }
    >
      <Layout
        height="fill"
        content={
          <LayoutContent
            isScrollable
            label="Настройки маскирования"
            padding={8}
          >
            <VStack gap={5}>
              <Card padding={0}>
                <UploadDropzone />
              </Card>
              <Card padding={0}>
                <MaskStylePicker
                  onAddCustomType={() => void handleOpenCompiler()}
                  isAddingCustomType={isUploadingForCompiler}
                />
              </Card>
              {isNarrow ? (
                <Card padding={0}>
                  <VStack gap={0}>
                    {queueHeader}
                    <VStack gap={4} padding={4} minHeight={200}>
                      <UploadQueue />
                      {submitButton}
                    </VStack>
                  </VStack>
                </Card>
              ) : null}
              <Card padding={0}>
                <RecentDocuments />
              </Card>
            </VStack>
          </LayoutContent>
        }
      />
    </ScreenLayout>
    <CustomTypesCompilerDialog
      isOpen={isCompilerOpen}
      onOpenChange={(open) => {
        setIsCompilerOpen(open);
        if (!open) setCompilerObjectName(null);
      }}
      objectName={compilerObjectName}
    />
    </>
  );
}
