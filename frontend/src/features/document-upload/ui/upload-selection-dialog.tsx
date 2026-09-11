import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { List, ListItem } from "@astryxdesign/core/List";
import { HStack } from "@astryxdesign/core/Stack";
import { useUploadQueueStore } from "../../../entity/document/model/upload-queue-store";
import { FormatToken } from "../../../entity/document/ui/format-token";

type Props = {
  isOpen: boolean;
  uploadIds: string[];
  onSelect: (runId: string) => void;
  onLeave: () => void;
};

/** Выбор рабочего документа из только что отправленной пачки. */
export function UploadSelectionDialog({ isOpen, uploadIds, onSelect, onLeave }: Props) {
  const items = useUploadQueueStore((state) => state.items);
  const uploads = items.filter((item) => uploadIds.includes(item.id));
  return (
    <Dialog isOpen={isOpen} purpose="required" width={560} onOpenChange={() => {}}>
      <Layout
        header={<DialogHeader title="Какой документ открыть?" subtitle="Выберите файл, чтобы настроить обезличивание и проверить результат." />}
        content={<LayoutContent isScrollable>
          <List hasDividers>
            {uploads.map((item) => <ListItem key={item.id} label={item.name}
              description={item.state === "failed" ? item.error ?? "Не удалось загрузить" : item.state === "started" ? "Можно открыть" : "Загружается…"}
              startContent={<FormatToken format={item.format} />}
              endContent={<Button label="Открыть" size="sm" isDisabled={item.runId === null}
                onClick={() => { if (item.runId) onSelect(item.runId); }} />} />)}
          </List>
        </LayoutContent>}
        footer={<LayoutFooter hasDivider><HStack hAlign="end"><Button label="К загрузке файлов" variant="ghost" onClick={onLeave} /></HStack></LayoutFooter>}
      />
    </Dialog>
  );
}
