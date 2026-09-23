import { useMediaQuery } from "@astryxdesign/core/hooks";
import { List, ListItem } from "@astryxdesign/core/List";
import { Section } from "@astryxdesign/core/Section";
import { VStack } from "@astryxdesign/core/Stack";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Heading, Text } from "@astryxdesign/core/Text";

import { piiTypeLabel } from "../../../entity/pii/model/pii-type-dict";
import type { DecisionSource, MaskingReport } from "../../../entity/pii/model/types";
import { maskedOccurrences } from "../lib/report-occurrences";

type ReportRow = {
  id: string;
  type: string;
  original: string;
  marker: string;
  where: string;
};

/** Подписи нужны техническому компоненту ресурсов, который не входит в отчёт оператора. */
export const DECIDED_BY_LABEL: Record<DecisionSource, string> = {
  critical_guard: "обязательная защита",
  entity: "оператор",
  profile: "по стороне",
  type: "по типу",
  judge: "судья",
  default: "по умолчанию",
};

function buildRows(report: MaskingReport): ReportRow[] {
  return maskedOccurrences(report).map((occurrence) => ({
    id: occurrence.id,
    type: piiTypeLabel(occurrence.type),
    original: occurrence.originalText,
    marker: occurrence.marker,
    where: occurrence.anchor.label,
  }));
}

/** Оператору важны три вопроса: что нашли, что скрыли и где это было. */
export function ReportTable({ report }: { report: MaskingReport }) {
  const rows = buildRows(report);
  const isCompact = useMediaQuery("(max-width: 1200px)", false);

  return (
    <Section padding={0}>
      <VStack gap={0}>
        <VStack gap={1} paddingBlock={3}>
          <Heading level={3}>Замены в документе</Heading>
          <Text color="secondary" textWrap="pretty">
            {rows.length === 0 ? "Замен в документе нет." : `${rows.length} записей: исходный фрагмент и его замена.`}
          </Text>
        </VStack>
        {isCompact && rows.length > 0 ? (
          <List hasDividers header="Заменённые фрагменты">
            {rows.map((row) => (
              <ListItem
                key={row.id}
                label={row.type}
                description={
                  <VStack gap={1}>
                    <Text type="supporting" color="secondary" textWrap="pretty">{row.where}</Text>
                    <Text textWrap="pretty" className="break-all">{row.original}</Text>
                    <Text type="supporting" color="secondary" className="max-w-full overflow-x-auto whitespace-nowrap">→ {row.marker}</Text>
                  </VStack>
                }
              />
            ))}
          </List>
        ) : rows.length > 0 ? (
          <Table<ReportRow>
            data={rows}
            idKey="id"
            density="balanced"
            textOverflow="wrap"
            columns={[
              {
                key: "type", header: "Данные / место", width: pixel(200),
                renderCell: (row) => (
                  <VStack gap={1}>
                    <Text weight="medium" textWrap="pretty">{row.type}</Text>
                    <Text type="supporting" color="secondary" textWrap="pretty">{row.where}</Text>
                  </VStack>
                ),
              },
              {
                key: "original", header: "Было", width: proportional(1),
                renderCell: (row) => <Text className="break-all">{row.original}</Text>,
              },
              {
                key: "marker", header: "Стало", width: pixel(300),
                renderCell: (row) => <Text type="code" className="max-w-full overflow-x-auto whitespace-nowrap">{row.marker}</Text>,
              },
            ]}
          />
        ) : null}
      </VStack>
    </Section>
  );
}
