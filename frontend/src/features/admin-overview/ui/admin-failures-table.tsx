import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Section } from "@astryxdesign/core/Section";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";

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

  return (
    <Section padding={0}>
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
    </Section>
  );
}
