import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

import { reportRows } from "../../../entity/document/model/fixtures";
import type { ReportRow } from "../../../entity/document/model/types";

const STATUS_COLOR: Record<
  ReportRow["status"],
  "green" | "red" | "yellow" | "gray"
> = {
  "подтв.": "green",
  низкая: "red",
  проверить: "yellow",
  ожидает: "gray",
};

/** Перечень заменённых фрагментов — то, что уходит в CSV/XLSX/PDF-отчёт. */
export function ReportTable() {
  return (
    <Section padding={0}>
      <VStack gap={0} paddingInline={4}>
        <HStack gap={2} vAlign="center" paddingBlock={3}>
          <Heading level={5}>Перечень заменённых фрагментов</Heading>
          <StackItem size="fill" />
          <Text type="supporting" hasTabularNumbers>
            {`${reportRows.length} записей`}
          </Text>
        </HStack>
        <Table<ReportRow>
          data={reportRows}
          idKey="id"
          density="balanced"
          hasHover
          textOverflow="truncate"
          columns={[
            {
              key: "page",
              header: "Стр.",
              width: pixel(72),
              renderCell: (row) => (
                <Text type="supporting" hasTabularNumbers>
                  {row.page}
                </Text>
              ),
            },
            { key: "type", header: "Тип", width: pixel(150) },
            { key: "original", header: "Оригинал", width: proportional(1) },
            {
              key: "marker",
              header: "Маркер",
              width: pixel(160),
              renderCell: (row) => (
                <Text type="code" size="sm">
                  {row.marker}
                </Text>
              ),
            },
            {
              key: "side",
              header: "Сторона",
              width: pixel(120),
              renderCell: (row) => (
                <Text color="secondary">{row.side}</Text>
              ),
            },
            {
              key: "status",
              header: "Статус",
              width: pixel(120),
              renderCell: (row) => (
                <Token
                  size="sm"
                  color={STATUS_COLOR[row.status]}
                  label={row.status}
                />
              ),
            },
          ]}
        />
      </VStack>
    </Section>
  );
}
