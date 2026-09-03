import { Download, RotateCcw } from "lucide-react";
import { useNavigate } from "react-router";
import { Button } from "@astryxdesign/core/Button";
import { ButtonGroup } from "@astryxdesign/core/ButtonGroup";
import { Icon } from "@astryxdesign/core/Icon";
import { VStack } from "@astryxdesign/core/Stack";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { Toolbar } from "@astryxdesign/core/Toolbar";

import type { HistoryRecord, RunRecord } from "../../../entity/document/model/types";

/** Раскрытая строка истории: действия над документом и его прогоны. */
export function HistoryRunList({ record }: { record: HistoryRecord }) {
  const navigate = useNavigate();

  return (
    <VStack gap={5} padding={4} paddingBlockStart={2}>
      <Toolbar
        label="Действия с документом"
        size="sm"
        startContent={
          <Button
            variant="primary"
            label="Открыть проверку"
            onClick={() => navigate("/review")}
          />
        }
        endContent={
          <>
            <ButtonGroup label="Скачать файл">
              <Button
                variant="secondary"
                label="Обезличенный"
                icon={<Icon icon={Download} />}
              />
              <Button
                variant="secondary"
                label="Оригинал"
                icon={<Icon icon={Download} />}
              />
            </ButtonGroup>
            <Button
              variant="ghost"
              label="Повторить с новыми правилами"
              icon={<Icon icon={RotateCcw} />}
            />
          </>
        }
      />

      <Table<RunRecord>
        data={record.runs}
        idKey="tag"
        density="balanced"
        columns={[
          {
            key: "tag",
            header: "Версия",
            width: pixel(100),
            renderCell: (run) => (
              <Text weight="medium">{run.tag}</Text>
            ),
          },
          {
            key: "description",
            header: "Описание изменений",
            width: proportional(1),
            renderCell: (run) => (
              <Text>{run.description}</Text>
            )
          },
          {
            key: "author",
            header: "Автор",
            width: pixel(160),
            renderCell: (run) => (
              <Text color="secondary">{run.author}</Text>
            ),
          },
          {
            key: "when",
            header: "Время",
            width: pixel(140),
            align: "end",
            renderCell: (run) => (
              <Text color="secondary">{run.when}</Text>
            ),
          },
        ]}
      />
    </VStack>
  );
}
