import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Section } from "@astryxdesign/core/Section";
import { Text } from "@astryxdesign/core/Text";
import { Button } from "@astryxdesign/core/Button";
import { DialogHeader, useImperativeDialog } from "@astryxdesign/core/Dialog";
import {
  Table,
  pixel,
  proportional,
} from "@astryxdesign/core/Table";
import { VStack } from "@astryxdesign/core/Stack";

import { documentHistory } from "../../../entity/document/model/fixtures";
import type { HistoryRecord } from "../../../entity/document/model/types";
import { DocumentStatusToken } from "../../../entity/document/ui/document-status-token";
import { FormatToken } from "../../../entity/document/ui/format-token";
import {
  ALL_PROJECTS,
  useHistoryFilterStore,
} from "../model/history-filter-store";
import { HistoryRunList } from "./history-run-list";

const REVIEW_STATUSES: HistoryRecord["status"][] = ["review", "ocr"];

/** Таблица истории файлов. */
export function HistoryTable() {
  const query = useHistoryFilterStore((state) => state.query);
  const project = useHistoryFilterStore((state) => state.project);
  const status = useHistoryFilterStore((state) => state.status);
  const dialog = useImperativeDialog();

  const rows = documentHistory.filter((record) => {
    if (project !== ALL_PROJECTS && record.project !== project) return false;
    if (status === "ok" && record.status !== "ok") return false;
    if (status === "review" && !REVIEW_STATUSES.includes(record.status)) {
      return false;
    }
    if (query && !record.name.toLowerCase().includes(query.toLowerCase())) {
      return false;
    }
    return true;
  });

  if (rows.length === 0) {
    return (
      <Section padding={0}>
        <EmptyState
          title="Ничего не найдено"
          description="Ни один документ не подходит под выбранные фильтры."
        />
      </Section>
    );
  }

  return (
    <>
      <Section padding={0}>
        <VStack gap={0} paddingInline={4}>
          <Table<HistoryRecord>
            data={rows}
            idKey="id"
            density="balanced"
            hasHover
            textOverflow="truncate"
            columns={[
              {
                key: "name",
                header: "Документ",
                width: proportional(2),
                renderCell: (record) => (
                  <VStack gap={0.5}>
                    <Text weight="medium" maxLines={1}>
                      {record.name}
                    </Text>
                    <Text type="supporting" color="secondary" maxLines={1}>
                      {record.meta}
                    </Text>
                  </VStack>
                ),
              },
              {
                key: "replacements",
                header: "Замен",
                width: pixel(96),
                align: "end",
                renderCell: (record) => (
                  <Text hasTabularNumbers>{record.replacements}</Text>
                ),
              },
              {
                key: "versions",
                header: "Версии",
                width: pixel(88),
                align: "end",
                renderCell: (record) => (
                  <Text color="secondary" hasTabularNumbers>
                    {record.versions}
                  </Text>
                ),
              },
              {
                key: "format",
                header: "Формат",
                width: pixel(96),
                renderCell: (record) => <FormatToken format={record.format} />,
              },
              {
                key: "updated",
                header: "Обновлён",
                width: pixel(132),
                renderCell: (record) => (
                  <Text color="secondary">{record.updated}</Text>
                ),
              },
              {
                key: "status",
                header: "Статус",
                width: pixel(170),
                renderCell: (record) => (
                  <DocumentStatusToken status={record.status} />
                ),
              },
              {
                key: "actions",
                header: "",
                width: pixel(100),
                align: "end",
                renderCell: (record) => (
                  <Button
                    size="sm"
                    variant="ghost"
                    label="Детали"
                    onClick={() =>
                      dialog.show(
                        <VStack gap={0}>
                          <DialogHeader
                            title={record.name}
                            subtitle={record.meta}
                            onOpenChange={dialog.hide}
                          />
                          <HistoryRunList record={record} />
                        </VStack>,
                        { width: 800 }
                      )
                    }
                  />
                ),
              },
            ]}
          />
        </VStack>
      </Section>
      {dialog.element}
    </>
  );
}
