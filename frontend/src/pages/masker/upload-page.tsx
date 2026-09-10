import { useState } from "react";
import { useNavigate } from "react-router";
import { Play } from "lucide-react";
import { useToast } from "@astryxdesign/core/Toast";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import {
  Layout,
  LayoutContent,
  LayoutFooter,
  LayoutHeader,
  LayoutPanel,
} from "@astryxdesign/core/Layout";
import { Icon } from "@astryxdesign/core/Icon";
import { List, ListItem } from "@astryxdesign/core/List";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { useUploadQueueStore } from "../../entity/document/model/upload-queue-store";
import { piiTypeOptions } from "../../entity/pii/model/pii-type-dict";
import { useRuleProfileStore } from "../../entity/rule-profile/model/rule-profile-store";
import { RecentDocuments } from "../../features/document-history/ui/recent-documents";
import { useStartRun } from "../../features/masking-run/api/masking-run";
import {
  MASK_STYLE_OPTIONS,
  MaskStylePicker,
} from "../../features/document-upload/ui/mask-style-picker";
import { UploadDropzone } from "../../features/document-upload/ui/upload-dropzone";
import { UploadQueue } from "../../features/document-upload/ui/upload-queue";
import { pluralRu } from "../../shared/lib/plural-ru";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";

/** Ширина правой колонки настроек — структурный размер региона. */
const SETTINGS_WIDTH = 380;

const REGISTRY_TYPE_COUNT = piiTypeOptions().length;

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
  const maskStyleName =
    MASK_STYLE_OPTIONS.find((option) => option.id === maskStyle)?.name ?? maskStyle;

  const startRun = useStartRun();
  // Кандидаты на (повторную) отправку: всё, что ещё не заведено прогоном —
  // включая уже упавшие файлы, их можно отправить повторно тем же кликом.
  const submittable = items.filter((item) => item.state !== "started");
  // «Готово» в шапке очереди — только по-настоящему свободные от ошибки
  // файлы, а не всё, что уйдёт по кнопке (которая retry-ит и упавшие).
  const readyCount = items.filter((item) => item.state === "pending").length;

  const [isConfirmOpen, setIsConfirmOpen] = useState(false);

  /**
   * Один прогон на документ: движок принимает файл, а не пачку. Файлы
   * заводятся по очереди, чтобы порядок прогонов в журнале совпадал с
   * порядком в очереди, а первый открылся на проверку.
   */
  async function handleStart() {
    let firstRunId: string | null = null;
    let failedCount = 0;

    for (const item of submittable) {
      markStarting(item.id);
      try {
        const run = await startRun.mutateAsync({
          source: item.source,
          maskStyle,
        });
        markStarted(item.id, run.id);
        firstRunId ??= run.id;
      } catch (error) {
        failedCount += 1;
        markFailed(
          item.id,
          error instanceof Error ? error.message : "не удалось запустить",
        );
      }
    }

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
    navigate(`/documents/${firstRunId}`);
  }

  return (
    <ScreenLayout
      title="Новый документ"
      contentPadding={0}
      isContentScrollable={false}
      panel={
        <LayoutPanel
          width={SETTINGS_WIDTH}
          hasDivider
          padding={0}
          isScrollable={false}
          label="Настройки задачи"
        >
          <Layout
            height="fill"
            header={
              <LayoutHeader hasDivider padding={0}>
                <HStack
                  gap={2}
                  vAlign="center"
                  paddingInline={3}
                  paddingBlock={3}
                >
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
                      isDisabled={startRun.isPending}
                      onClick={clearQueue}
                    />
                  ) : null}
                </HStack>
              </LayoutHeader>
            }
            content={
              <LayoutContent padding={4} isScrollable label="Очередь">
                <VStack gap={4} height="100%">
                  <StackItem size="fill">
                    <UploadQueue />
                  </StackItem>
                  <VStack gap={3}>
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
                      isDisabled={submittable.length === 0 || startRun.isPending}
                      isLoading={startRun.isPending}
                      onClick={() => setIsConfirmOpen(true)}
                    />
                  </VStack>
                </VStack>
              </LayoutContent>
            }
          />
        </LayoutPanel>
      }
    >
      <Layout
        height="fill"
        content={
          <LayoutContent
            isScrollable
            label="Настройки маскирования"
            padding={6}
          >
            <VStack gap={5}>
              <Card padding={0}>
                <UploadDropzone />
              </Card>
              <Card padding={0}>
                <MaskStylePicker />
              </Card>
              <Card padding={0}>
                <RecentDocuments />
              </Card>
            </VStack>
          </LayoutContent>
        }
      />

      <Dialog isOpen={isConfirmOpen} onOpenChange={setIsConfirmOpen} purpose="form" width={480}>
        <Layout
          header={
            <DialogHeader
              title="Запустить обезличивание?"
              subtitle="Действие нельзя отменить после запуска — проверьте список перед подтверждением."
              onOpenChange={setIsConfirmOpen}
            />
          }
          content={
            <LayoutContent>
              <VStack gap={4}>
                <VStack gap={2}>
                  <Text type="label" weight="medium">
                    {`${submittable.length} ${pluralRu(submittable.length, ["файл", "файла", "файлов"])} на обезличивание`}
                  </Text>
                  <List hasDividers density="compact">
                    {submittable.map((item) => (
                      <ListItem key={item.id} label={item.name} />
                    ))}
                  </List>
                </VStack>
                <VStack gap={1}>
                  <Text color="secondary" size="sm">
                    {`Стиль маски: «${maskStyleName}». Маскируются все ${REGISTRY_TYPE_COUNT} ${pluralRu(REGISTRY_TYPE_COUNT, ["тип", "типа", "типов"])} персональных данных из реестра движка.`}
                  </Text>
                  <Text color="secondary" size="sm">
                    Перед тем как документ станет финальным, каждый найденный
                    фрагмент можно проверить и отменить на экране проверки —
                    запуск сразу не завершает обработку.
                  </Text>
                </VStack>
              </VStack>
            </LayoutContent>
          }
          footer={
            <LayoutFooter hasDivider>
              <HStack gap={2} hAlign="end" width="100%">
                <Button variant="ghost" label="Отмена" onClick={() => setIsConfirmOpen(false)} />
                <Button
                  variant="primary"
                  label="Запустить"
                  icon={<Icon icon={Play} size="sm" />}
                  isLoading={startRun.isPending}
                  onClick={() => {
                    setIsConfirmOpen(false);
                    void handleStart();
                  }}
                />
              </HStack>
            </LayoutFooter>
          }
        />
      </Dialog>
    </ScreenLayout>
  );
}
