import { Download } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";

type UnsupportedFormatProps = {
  format: string;
  fileUrl: string;
};

/**
 * Заглушка на случай формата, которого нет ни среди docx/xlsx, ни среди
 * bbox-форматов (`document-viewer.tsx::BBOX_FORMATS`) — сегодня все
 * значения `PiiDocFormat` разобраны, это только защита от расхождения
 * контракта с бэкендом.
 */
export function UnsupportedFormat({ format, fileUrl }: UnsupportedFormatProps) {
  return (
    <EmptyState
      title={`Просмотр для ${format.toUpperCase()} пока недоступен`}
      description="Подсветка замен для этого формата ещё не реализована. Скачайте файл, чтобы проверить его локально."
      actions={
        <Button
          variant="secondary"
          label="Скачать файл"
          icon={<Icon icon={Download} size="sm" />}
          href={fileUrl}
        />
      }
    />
  );
}
