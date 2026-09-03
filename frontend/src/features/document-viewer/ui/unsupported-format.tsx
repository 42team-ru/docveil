import { Download } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";

type UnsupportedFormatProps = {
  format: string;
  fileUrl: string;
};

/** Заглушка для pdf/xlsx — привязка ПДн к этим форматам не входит в эту итерацию. */
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
