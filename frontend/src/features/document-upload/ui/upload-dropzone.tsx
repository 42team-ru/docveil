import { FileInput } from "@astryxdesign/core/FileInput";
import { Section } from "@astryxdesign/core/Section";
import { VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { useUploadQueueStore } from "../model/upload-queue-store";

/**
 * Приём файлов. Выбранное кладётся в очередь задачи: сам файл уходит на
 * бэкенд не отсюда, а по кнопке запуска — до неё оператор ещё может убрать
 * лишнее из списка.
 */
export function UploadDropzone() {
  const items = useUploadQueueStore((state) => state.items);
  const add = useUploadQueueStore((state) => state.add);

  return (
    <Section padding={4}>
      <VStack gap={3}>
        <FileInput
          mode="dropzone"
          isMultiple
          label="Перетащите документы или выберите файлы"
          description="PDF и DOCX. Сканы распознаются локально через OCR."
          accept=".pdf,.docx"
          value={items.map((item) => item.file)}
          onChange={(next) => add(Array.isArray(next) ? next : next ? [next] : [])}
          width="100%"
        />
        <Text type="supporting" textWrap="pretty">
          Файлы уходят на сервер обезличивания во внутреннем контуре и хранятся
          там же — наружу ничего не отправляется.
        </Text>
      </VStack>
    </Section>
  );
}
