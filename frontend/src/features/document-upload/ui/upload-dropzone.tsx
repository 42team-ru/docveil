import { useState } from "react";
import { FileInput } from "@astryxdesign/core/FileInput";
import { Section } from "@astryxdesign/core/Section";
import { VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

/**
 * Приём файлов. Обработчик пока локальный: бэкенда нет, файлы никуда не уходят —
 * что совпадает с обещанием «файлы не покидают машину».
 */
export function UploadDropzone() {
  const [files, setFiles] = useState<File[]>([]);

  return (
    <Section padding={4}>
      <VStack gap={3}>
        <FileInput
          mode="dropzone"
          isMultiple
          label="Перетащите документы или выберите файлы"
          description="PDF, DOCX, XLSX. Сканы распознаются локально через OCR."
          accept=".pdf,.docx,.xlsx"
          value={files}
          onChange={(next) => setFiles(Array.isArray(next) ? next : [])}
          width="100%"
        />
        <Text type="supporting" textWrap="pretty">
          Файлы не покидают машину — обработка идёт в этом процессе.
        </Text>
      </VStack>
    </Section>
  );
}
