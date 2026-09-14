import { Search } from "lucide-react";
import type { UseQueryResult } from "@tanstack/react-query";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Pagination } from "@astryxdesign/core/Pagination";
import { Section } from "@astryxdesign/core/Section";
import { Selector } from "@astryxdesign/core/Selector";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Toolbar } from "@astryxdesign/core/Toolbar";

import { RunStatusToken, STATUS_LABEL } from "../../../entity/document/ui/run-status-token";
import type {
  AdminRunListResponse,
  AdminUserRowOut,
} from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { formatMoment } from "../../../shared/lib/format-moment";
import type { RunStatus } from "../../masking-run/api/masking-run";
import {
  type AdminRunStatusFilter,
  useAdminFiltersStore,
} from "../model/admin-filters-store";

type AdminRunRow = AdminRunListResponse["items"][number] & Record<string, unknown>;

const STATUS_ORDER: RunStatus[] = [
  "queued",
  "running",
  "awaiting_answers",
  "awaiting_review",
  "done",
  "leaked",
  "failed",
];

const STATUS_OPTIONS = [
  { value: "all", label: "Все статусы" },
  ...STATUS_ORDER.map((status) => ({ value: status, label: STATUS_LABEL[status] })),
];

type AdminRunsTableProps = {
  runs: UseQueryResult<AdminRunListResponse, Error>;
  users: AdminUserRowOut[] | undefined;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
};

/** Журнал прогонов **всех** пользователей — в отличие от личного журнала
 * (`document-history`), здесь видна колонка «Владелец» и фильтр по нему. */
export function AdminRunsTable({ runs, users, page, pageSize, onPageChange }: AdminRunsTableProps) {
  const query = useAdminFiltersStore((state) => state.runQuery);
  const setQuery = useAdminFiltersStore((state) => state.setRunQuery);
  const status = useAdminFiltersStore((state) => state.runStatus);
  const setStatus = useAdminFiltersStore((state) => state.setRunStatus);
  const ownerId = useAdminFiltersStore((state) => state.runOwnerId);
  const setOwnerId = useAdminFiltersStore((state) => state.setRunOwnerId);

  const ownerOptions = [
    { value: "all", label: "Все пользователи" },
    ...(users ?? []).map((user) => ({ value: user.id, label: `${user.full_name} (${user.email})` })),
  ];

  const toolbar = (
    <Toolbar
      label="Фильтры журнала прогонов"
      size="lg"
      gap={3}
      startContent={
        <HStack gap={3} vAlign="center" wrap="wrap">
          <TextInput
            size="lg"
            label="Поиск по документу"
            isLabelHidden
            placeholder="Поиск по имени документа…"
            startIcon={Search}
            width={320}
            hasClear
            value={query}
            onChange={setQuery}
          />
          <Selector
            size="lg"
            label="Состояние прогона"
            isLabelHidden
            width={200}
            options={STATUS_OPTIONS}
            value={status}
            onChange={(value) => setStatus(value as AdminRunStatusFilter)}
          />
          <Selector
            size="lg"
            label="Владелец"
            isLabelHidden
            width={260}
            options={ownerOptions}
            value={ownerId ?? "all"}
            onChange={(value) => setOwnerId(value === "all" ? null : value)}
          />
        </HStack>
      }
    />
  );

  if (runs.isLoading) {
    return (
      <VStack gap={3}>
        {toolbar}
        <Section padding={4}>
          <Skeleton height={240} width="100%" />
        </Section>
      </VStack>
    );
  }

  if (runs.isError) {
    return (
      <VStack gap={3}>
        {toolbar}
        <Banner
          status="error"
          container="card"
          collapsible={false}
          title="Журнал недоступен"
          description="Не удалось получить прогоны всех пользователей."
          endContent={
            <Button size="sm" variant="secondary" label="Повторить" onClick={() => void runs.refetch()} />
          }
        />
      </VStack>
    );
  }

  const rows = (runs.data?.items ?? []) as AdminRunRow[];
  const total = runs.data?.total ?? 0;

  return (
    <VStack gap={3}>
      {toolbar}
      {rows.length === 0 ? (
        <Section padding={4}>
          <EmptyState
            title="Ничего не найдено"
            description="Ни один прогон не подходит под выбранные фильтры."
          />
        </Section>
      ) : (
        <Section padding={0}>
          <VStack gap={0}>
            <Table<AdminRunRow>
              data={rows}
              idKey="id"
              density="balanced"
              hasHover
              textOverflow="truncate"
              rowIndexStart={(page - 1) * pageSize + 1}
              rowCount={total}
              columns={[
                {
                  key: "name",
                  header: "Документ",
                  width: proportional(2),
                  renderCell: (run) => (
                    <Text weight="medium" maxLines={1}>
                      {run.document.name}
                    </Text>
                  ),
                },
                {
                  key: "owner",
                  header: "Владелец",
                  width: proportional(2),
                  renderCell: (run) => (
                    <Text color="secondary" maxLines={1}>
                      {run.user_full_name ?? run.user_email ?? run.user_id}
                    </Text>
                  ),
                },
                {
                  key: "status",
                  header: "Статус",
                  width: pixel(180),
                  renderCell: (run) => <RunStatusToken status={run.status} />,
                },
                {
                  key: "created_at",
                  header: "Запущен",
                  width: pixel(140),
                  renderCell: (run) => (
                    <Text color="secondary">{formatMoment(run.created_at)}</Text>
                  ),
                },
                {
                  key: "finished_at",
                  header: "Завершён",
                  width: pixel(140),
                  renderCell: (run) => (
                    <Text color="secondary">{formatMoment(run.finished_at)}</Text>
                  ),
                },
              ]}
            />
            {total > pageSize ? (
              <HStack hAlign="center" paddingBlock={3}>
                <Pagination page={page} onChange={onPageChange} totalItems={total} pageSize={pageSize} size="sm" />
              </HStack>
            ) : null}
          </VStack>
        </Section>
      )}
    </VStack>
  );
}
