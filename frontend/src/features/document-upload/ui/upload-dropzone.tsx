import { useState } from "react";
import { FileCheck2 } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { FileInput } from "@astryxdesign/core/FileInput";
import { Icon } from "@astryxdesign/core/Icon";
import { Section } from "@astryxdesign/core/Section";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { useToast } from "@astryxdesign/core/Toast";

import { useUploadQueueStore } from "../../../entity/document/model/upload-queue-store";
import { DEMO_DOCUMENT_NAME, loadDemoDocument } from "../lib/demo-document";

/**
 * Приём файлов. Выбранное кладётся в очередь задачи: сам файл уходит на
 * бэкенд не отсюда, а по кнопке запуска — до неё оператор ещё может убрать
 * лишнее из списка.
 */
export function UploadDropzone() {
  const items = useUploadQueueStore((state) => state.items);
  const add = useUploadQueueStore((state) => state.add);
  const showToast = useToast();
  const [isDemoLoading, setIsDemoLoading] = useState(false);

  async function handleAddDemo() {
    if (items.some((item) => item.name === DEMO_DOCUMENT_NAME)) {
      showToast({ body: "Учебный договор уже добавлен в очередь", type: "info" });
      return;
    }

    setIsDemoLoading(true);
    try {
      add([await loadDemoDocument()]);
      showToast({
        body: "Учебный договор добавлен. Теперь запустите обработку справа.",
        type: "info",
      });
    } catch (error) {
      showToast({
        body: error instanceof Error ? error.message : "Не удалось загрузить учебный договор",
        type: "error",
      });
    } finally {
      setIsDemoLoading(false);
    }
  }

  return (
    <Section padding={4}>
      <VStack gap={3}>
        <FileInput
          mode="dropzone"
          isMultiple
          label="Загрузите документ"
          description="Перетащите PDF, DOCX или XLSX сюда либо выберите файл на компьютере."
          accept=".pdf,.docx,.xlsx"
          value={items
            .map((item) => (item.source.kind === "file" ? item.source.file : null))
            .filter((file): file is File => file !== null)}
          onChange={(next) => add(Array.isArray(next) ? next : next ? [next] : [])}
          width="100%"
        />
        <Section variant="muted" padding={3}>
          <VStack gap={2}>
            <Text type="label" weight="medium">
              Хотите сначала посмотреть результат?
            </Text>
            <Text type="supporting" color="secondary" textWrap="pretty">
              Откройте учебный договор: в нём нет рабочих данных, а шаги обработки такие же,
              как для вашего файла.
            </Text>
            <HStack>
              <Button
                size="sm"
                variant="primary"
                label="Открыть безопасный пример"
                icon={<Icon icon={FileCheck2} size="sm" />}
                isLoading={isDemoLoading}
                onClick={() => void handleAddDemo()}
              />
            </HStack>
          </VStack>
        </Section>
      </VStack>
    </Section>
  );
}
