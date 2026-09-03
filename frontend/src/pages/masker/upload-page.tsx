import { useNavigate } from "react-router";
import { Play } from "lucide-react";
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

import { uploadQueueSummary } from "../../entity/document/model/fixtures";
import { DataTypePicker } from "../../features/document-upload/ui/data-type-picker";
import { UploadDropzone } from "../../features/document-upload/ui/upload-dropzone";
import { UploadQueue } from "../../features/document-upload/ui/upload-queue";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";

/** Ширина правой колонки настроек — структурный размер региона. */
const SETTINGS_WIDTH = 380;

/** Шаг 1: что обезличиваем и по каким правилам. */
export function UploadPage() {
  const navigate = useNavigate();

  return (
    <ScreenLayout
      title="Новая задача"
      startContent={
        <HStack gap={1.5} vAlign="center">
          <StatusDot variant="neutral" label="Подготовка задачи" />
        </HStack>
      }
      meta={
        <HStack gap={2} vAlign="center">
          <Text type="supporting" hasTabularNumbers>шаг 1 из 3</Text>
          <Text type="supporting" color="secondary">·</Text>
          <Text type="supporting" color="secondary">вход и правила маскирования</Text>
        </HStack>
      }
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
              <LayoutHeader hasDivider>
                <HStack gap={2} vAlign="center" padding={3}>
                  <Text type="label" weight="medium">
                    Очередь файлов
                  </Text>
                  <StackItem size="fill" />
                  <Text type="supporting" color="secondary" size="sm">
                    {uploadQueueSummary.files} готово
                  </Text>
                </HStack>
              </LayoutHeader>
            }
            content={
              <LayoutContent padding={4} isScrollable label="Очередь">
                <VStack gap={4} height="100%">
                  <UploadQueue />
                  <StackItem size="fill" />
                  <VStack gap={3}>
                    <Button
                      variant="primary"
                      size="lg"
                      width="100%"
                      icon={<Icon icon={Play} size="sm" />}
                      label={`Обезличить ${uploadQueueSummary.files} файла`}
                      onClick={() => navigate("/review")}
                    />
                    <Text type="supporting" color="secondary" justify="center">
                      {`оценка: ${uploadQueueSummary.estimate}`}
                    </Text>
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
          <LayoutContent isScrollable label="Настройки маскирования" padding={6}>
            <VStack gap={5}>
              <Card padding={0}>
                <UploadDropzone />
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
