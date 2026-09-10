import { useNavigate } from "react-router";
import { Play } from "lucide-react";
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
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Text } from "@astryxdesign/core/Text";

import { useRuleProfileStore } from "../../entity/rule-profile/model/rule-profile-store";
import { useUploadQueueStore } from "../../entity/document/model/upload-queue-store";
import { useStartRun } from "../../features/masking-run/api/masking-run";
import { DataTypePicker } from "../../features/document-upload/ui/data-type-picker";
import { MaskStylePicker } from "../../features/document-upload/ui/mask-style-picker";
import { UploadDropzone } from "../../features/document-upload/ui/upload-dropzone";
import { UploadQueue } from "../../features/document-upload/ui/upload-queue";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";

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

  const enabledTypes = useRuleProfileStore((state) => state.enabledTypes);
  const maskStyle = useRuleProfileStore((state) => state.maskStyle);

  const startRun = useStartRun();
  const pending = items.filter((item) => item.state !== "started");

  /**
   * Один прогон на документ: движок принимает файл, а не пачку. Файлы
   * заводятся по очереди, чтобы порядок прогонов в журнале совпадал с
   * порядком в очереди, а первый открылся на проверку.
   */
  async function handleStart() {
    let firstRunId: string | null = null;

    for (const item of pending) {
      markStarting(item.id);
      try {
        const run = await startRun.mutateAsync({
          source: item.source,
          types: enabledTypes,
          maskStyle,
        });
        markStarted(item.id, run.id);
        firstRunId ??= run.id;
      } catch (error) {
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
    navigate(`/documents/${firstRunId}`);
  }

  return (
    <ScreenLayout
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
                    {`${pending.length} готово`}
                  </Text>
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
                        pending.length === 1
                          ? "Обезличить документ"
                          : `Обезличить ${pending.length} документа`
                      }
                      isDisabled={pending.length === 0 || startRun.isPending}
                      isLoading={startRun.isPending}
                      onClick={() => void handleStart()}
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
                <DataTypePicker />
              </Card>
            </VStack>
          </LayoutContent>
        }
      />
    </ScreenLayout>
  );
}
