import { useMediaQuery } from "@astryxdesign/core/hooks";
import { Card } from "@astryxdesign/core/Card";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { List, ListItem } from "@astryxdesign/core/List";
import { Section } from "@astryxdesign/core/Section";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/Stack";

import type { AdminFailureOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { formatMoment } from "../../../shared/lib/format-moment";
import { graphNodeLabel } from "../lib/graph-node-labels";

/** `Table` требует индексную сигнатуру строки — приём из
 * `document-history/ui/history-table.tsx#RunRow`. */
type FailureRow = AdminFailureOut & Record<string, unknown>;

type AdminFailuresTableProps = {
  failures: AdminFailureOut[];
};

/** Топ узлов графа, роняющих прогоны — где именно система ломается чаще
 * всего за выбранное окно. */
export function AdminFailuresTable({ failures }: AdminFailuresTableProps) {
  const isCompact = useMediaQuery("(max-width: 1200px)", false);
  if (failures.length === 0) {
    return (
      <Section padding={4}>
        <EmptyState
          title="Падений не было"
          description="За выбранный период ни один прогон не завершился ошибкой."
        />
      </Section>
    );
  }

  if (isCompact) {
    return (
      <Card padding={0}>
        <List hasDividers>
          {failures.map((failure) => (
            <ListItem
              key={failure.node_hint ?? "unknown"}
              label={<Text weight="medium" textWrap="pretty">{graphNodeLabel(failure.node_hint)}</Text>}
              description={
                <VStack gap={1} className="min-w-0">
                  <Text>{`${failure.count} падений · ${formatMoment(failure.last_at)}`}</Text>
                  <Text color="secondary" textWrap="pretty">{failure.last_error ?? "Описание ошибки недоступно"}</Text>
                </VStack>
              }
            />
          ))}
        </List>
      </Card>
    );
  }

  return (
    <Section padding={0}>
      <VStack paddingInline={4}>
        <Table<FailureRow>
          data={failures as FailureRow[]}
          idKey={(row) => row.node_hint ?? "unknown"}
          density="balanced"
          textOverflow="truncate"
          columns={[
            {
              key: "node_hint",
              header: "Узел графа",
              width: pixel(220),
              renderCell: (row) => (
                <Text weight="medium">{graphNodeLabel(row.node_hint)}</Text>
              ),
            },
            {
              key: "count",
              header: "Падений",
              width: pixel(110),
              renderCell: (row) => <Text>{row.count}</Text>,
            },
            {
              key: "last_error",
              header: "Последняя ошибка",
              width: proportional(2),
              renderCell: (row) => (
                <Text color="secondary" maxLines={1}>
                  {row.last_error ?? "—"}
                </Text>
              ),
            },
            {
              key: "last_at",
              header: "Когда",
              width: pixel(140),
              renderCell: (row) => (
                <Text color="secondary">{formatMoment(row.last_at)}</Text>
              ),
            },
          ]}
        />
      </VStack>
    </Section>
  );
}
