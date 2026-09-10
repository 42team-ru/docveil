import { useState } from "react";
import { useNavigate } from "react-router";
import { Download, RotateCcw } from "lucide-react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Icon } from "@astryxdesign/core/Icon";
import {
  Layout,
  LayoutContent,
  LayoutFooter,
} from "@astryxdesign/core/Layout";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { useToast } from "@astryxdesign/core/Toast";

import type { DocumentFormat } from "../../../entity/document/model/types";
import { FormatToken } from "../../../entity/document/ui/format-token";
import { RunStatusToken } from "../../../entity/document/ui/run-status-token";
import { useUploadQueueStore } from "../../../entity/document/model/upload-queue-store";
import {
  downloadArtifact,
  hasRunResult,
  useRunArtifacts,
  useRunState,
} from "../../masking-run/api/masking-run";
import { formatMoment } from "../../../shared/lib/format-moment";

/** Подписи ролей артефактов — тех же, что отдаёт движок (`nodes.py`). */
const ARTIFACT_LABEL: Record<string, string> = {
  preview: "Исходный текст (с подсветкой)",
  masked_highlight: "Обезличенный с подсветкой",
  masked_black: "Обезличенный",
};

type RunDetailsDialogProps = {
  /** `null` — диалог закрыт. */
  runId: string | null;
  onClose: () => void;
  onOpenReview: (runId: string) => void;
};

/**
 * Детали прогона: сведения и скачивание файлов. Замена раскрытой строке
 * журнала (`history-run-list.tsx`, удалена в 3e81e65) — те же действия,
 * но на живых данных прогона через API, а не на фикстуре.
 *
 * «Скачать оригинал» отдельной кнопкой нет — артефакт `preview` уже несёт
 * исходный текст с подсветкой найденного, честнее «сырого» файла для
 * оператора. «Повторить прогон» использует `document.object_name`
 * (`RunDocument`, бэкенд хранит его с самого начала в `RunORM`, наружу отдаёт
 * с недавних пор) — заводит тот же файл в очереди загрузки без повторной
 * заливки байтов.
 */
export function RunDetailsDialog({
  runId,
  onClose,
  onOpenReview,
}: RunDetailsDialogProps) {
  const isOpen = runId !== null;
  const navigate = useNavigate();
  const runState = useRunState(runId);
  const run = runState.data;
  const ready = hasRunResult(run?.status);
  const artifacts = useRunArtifacts(runId, ready);
  const showToast = useToast();
  const addExisting = useUploadQueueStore((state) => state.addExisting);
  const [downloadingRole, setDownloadingRole] = useState<string | null>(null);

  async function handleDownload(role: string, name: string) {
    if (runId === null) return;
    setDownloadingRole(role);
    try {
      await downloadArtifact(runId, role, name);
    } catch {
      showToast({ body: "Не удалось скачать файл", type: "error" });
    } finally {
      setDownloadingRole(null);
    }
  }

  /**
   * Заводит тот же файл в очереди загрузки заново — без повторной заливки
   * байтов, `object_name` уже лежит в MinIO с прошлого прогона. Открывает
   * загрузку, а не запускает прогон напрямую: оператор может передумать
   * насчёт типов ПДн/стиля маски перед повторным запуском.
   */
  function handleRepeat() {
    if (run === undefined) return;
    addExisting({
      objectName: run.document.object_name,
      name: run.document.name,
      format: run.document.format.toUpperCase() as DocumentFormat,
    });
    onClose();
    navigate("/");
  }

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      purpose="info"
      width={560}
    >
      <Layout
        header={
          <DialogHeader
            title={run?.document.name ?? "Документ"}
            subtitle="Сведения о прогоне"
            onOpenChange={() => onClose()}
          />
        }
        content={
          <LayoutContent>
            {runState.isLoading ? (
              <Skeleton height={160} width="100%" />
            ) : run === undefined ? (
              <Banner
                status="error"
                container="section"
                collapsible={false}
                title="Прогон не найден"
                description="Возможно, его удалили из журнала."
              />
            ) : (
              <VStack gap={5}>
                <MetadataList columns={2}>
                  <MetadataListItem label="Формат">
                    <FormatToken
                      format={run.document.format.toUpperCase() as DocumentFormat}
                    />
                  </MetadataListItem>
                  <MetadataListItem label="Статус">
                    <RunStatusToken status={run.status} />
                  </MetadataListItem>
                  <MetadataListItem label="Запущен">
                    {formatMoment(run.created_at)}
                  </MetadataListItem>
                  <MetadataListItem label="Завершён">
                    {formatMoment(run.finished_at)}
                  </MetadataListItem>
                </MetadataList>

                {run.error ? (
                  <Banner
                    status="error"
                    container="section"
                    collapsible={false}
                    title="Ошибка прогона"
                    description={run.error}
                  />
                ) : null}

                <VStack gap={2}>
                  <Text type="label" weight="medium">
                    Файлы
                  </Text>
                  {!ready ? (
                    <Text color="secondary">
                      Файлы появятся, когда прогон дойдёт до проверки.
                    </Text>
                  ) : artifacts.isLoading ? (
                    <Skeleton height={80} width="100%" />
                  ) : (artifacts.data ?? []).length === 0 ? (
                    <Text color="secondary">Файлов нет.</Text>
                  ) : (
                    <VStack gap={1.5}>
                      {(artifacts.data ?? []).map((artifact) => (
                        <Button
                          key={artifact.role}
                          size="sm"
                          variant="secondary"
                          label={ARTIFACT_LABEL[artifact.role] ?? artifact.name}
                          icon={<Icon icon={Download} size="sm" />}
                          isLoading={downloadingRole === artifact.role}
                          onClick={() =>
                            void handleDownload(artifact.role, artifact.name)
                          }
                        />
                      ))}
                    </VStack>
                  )}
                </VStack>
              </VStack>
            )}
          </LayoutContent>
        }
        footer={
          <LayoutFooter hasDivider>
            <HStack gap={2} hAlign="end" width="100%">
              <Button
                variant="ghost"
                label="Повторить прогон"
                icon={<Icon icon={RotateCcw} size="sm" />}
                isDisabled={run === undefined}
                onClick={handleRepeat}
              />
              <Button
                variant="primary"
                label="Открыть"
                isDisabled={run === undefined}
                onClick={() => {
                  if (runId !== null) onOpenReview(runId);
                }}
              />
            </HStack>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
