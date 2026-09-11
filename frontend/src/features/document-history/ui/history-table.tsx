import { useState } from "react";
import { useNavigate } from "react-router";
import { FileClock, SearchX } from "lucide-react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { Pagination } from "@astryxdesign/core/Pagination";
import { Section } from "@astryxdesign/core/Section";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";

import type { DocumentFormat } from "../../../entity/document/model/types";
import { FormatToken } from "../../../entity/document/ui/format-token";
import { RunStatusToken } from "../../../entity/document/ui/run-status-token";
import type { useRunList } from "../../masking-run/api/masking-run";
import type { RunListItem } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { formatMoment } from "../../../shared/lib/format-moment";
import { RunDetailsDialog } from "./run-details-dialog";

/**
 * `Table` требует от строки индексной сигнатуры, а сгенерированный из
 * OpenAPI интерфейс её не имеет. Расширяем строку журнала здесь, а не правим
 * генерируемый код: `src/shared/api/generated` перезаписывается Orval.
 */
type RunRow = RunListItem & Record<string, unknown>;

/** Строка журнала как её видит `Table`; полей не добавляет, только сигнатуру. */
const asRows = (items: RunListItem[]): RunRow[] => items as RunRow[];

type HistoryTableProps = {
  /** Результат `useRunList` — запрос владеет `DocumentsPage`, чтобы шапка
   * экрана и пагинация читали один и тот же `total`, а не заводили вторую
   * сетевую пару глазами разных компонентов. */
  runs: ReturnType<typeof useRunList>;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  /** Активен ли поиск/фильтр статуса — различает «журнал пуст» и «под фильтр
   * ничего не подошло»: это разные состояния с разным следующим шагом. */
  hasActiveFilters: boolean;
  onResetFilters: () => void;
};

/** Журнал прогонов текущего пользователя. */
export function HistoryTable({
  runs,
  page,
  pageSize,
  onPageChange,
  hasActiveFilters,
  onResetFilters,
}: HistoryTableProps) {
  const navigate = useNavigate();
  const [detailsRunId, setDetailsRunId] = useState<string | null>(null);

  const detailsDialog = (
    <RunDetailsDialog
      runId={detailsRunId}
      onClose={() => setDetailsRunId(null)}
      onOpenReview={(runId) => navigate(`/documents/${runId}`)}
    />
  );

  if (runs.isLoading) {
    return (
      <Section padding={4}>
        <Skeleton height={240} width="100%" />
        {detailsDialog}
      </Section>
    );
  }

  if (runs.isError) {
    return (
      <Section padding={0}>
        <Banner
          status="error"
          container="card"
          collapsible={false}
          title="Журнал недоступен"
          description="Не удалось получить список прогонов."
          endContent={
            <Button size="sm" variant="secondary" label="Повторить" onClick={() => void runs.refetch()} />
          }
        />
        {detailsDialog}
      </Section>
    );
  }

  const rows = asRows(runs.data?.items ?? []);
  const total = runs.data?.total ?? 0;

  if (rows.length === 0) {
    return (
      <VStack height="100%" hAlign="center" vAlign="center">
        <Section width="100%" padding={0}>
          {hasActiveFilters ? (
            <EmptyState
              icon={<Icon icon={SearchX} size="lg" color="secondary" />}
              title="Ничего не найдено"
              description="Ни один прогон не подходит под выбранные фильтры."
              actions={<Button size="sm" variant="secondary" label="Сбросить фильтры" onClick={onResetFilters} />}
            />
          ) : (
            <EmptyState
              icon={<Icon icon={FileClock} size="lg" color="secondary" />}
              title="Здесь пока нет прогонов"
              description="Загрузите первый документ, чтобы начать обработку."
              actions={<Button size="sm" variant="primary" label="Новый документ" onClick={() => navigate("/")} />}
            />
          )}
          {detailsDialog}
        </Section>
      </VStack>
    );
  }

  return (
    <Section padding={0}>
      <VStack gap={0} paddingInline={4}>
        <Table<RunRow>
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
              key: "format",
              header: "Формат",
              width: pixel(96),
              renderCell: (run) => (
                <FormatToken
                  format={run.document.format.toUpperCase() as DocumentFormat}
                />
              ),
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
            {
              key: "status",
              header: "Статус",
              width: pixel(180),
              renderCell: (run) => <RunStatusToken status={run.status} />,
            },
            {
              key: "actions",
              header: "",
              width: pixel(320),
              align: "end",
              renderCell: (run) => (
                <HStack gap={1.5} hAlign="end">
                  <Button
                    size="sm"
                    variant="primary"
                    label={
                      run.status === "awaiting_review" || run.status === "done"
                        ? "Проверить результат"
                        : "Открыть документ"
                    }
                    onClick={() => navigate(`/documents/${run.id}`)}
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    label="Детали"
                    onClick={() => setDetailsRunId(run.id)}
                  />
                </HStack>
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
      {detailsDialog}
    </Section>
  );
}
