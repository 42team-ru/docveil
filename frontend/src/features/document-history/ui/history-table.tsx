import { useNavigate } from "react-router";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Section } from "@astryxdesign/core/Section";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { VStack } from "@astryxdesign/core/Stack";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";

import type { DocumentFormat } from "../../../entity/document/model/types";
import { FormatToken } from "../../../entity/document/ui/format-token";
import { RunStatusToken } from "../../../entity/document/ui/run-status-token";
import { useRunList } from "../../masking-run/api/masking-run";
import type { RunListItem } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { useHistoryFilterStore } from "../model/history-filter-store";

/**
 * `Table` требует от строки индексной сигнатуры, а сгенерированный из
 * OpenAPI интерфейс её не имеет. Расширяем строку журнала здесь, а не правим
 * генерируемый код: `src/shared/api/generated` перезаписывается Orval.
 */
type RunRow = RunListItem & Record<string, unknown>;

/** Строка журнала как её видит `Table`; полей не добавляет, только сигнатуру. */
const asRows = (items: RunListItem[]): RunRow[] => items as RunRow[];

/** Момент времени в журнале: короткая локальная дата, без выдуманных «2 часа назад». */
function formatMoment(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Журнал прогонов текущего пользователя. */
export function HistoryTable() {
  const navigate = useNavigate();
  const query = useHistoryFilterStore((state) => state.query);
  const status = useHistoryFilterStore((state) => state.status);

  const runs = useRunList({
    query: query || undefined,
    status: status === "all" ? undefined : status,
  });

  if (runs.isLoading) {
    return (
      <Section padding={4}>
        <Skeleton height={240} width="100%" />
      </Section>
    );
  }

  if (runs.isError) {
    return (
      <Section padding={0}>
        <EmptyState
          title="Журнал недоступен"
          description="Не удалось получить список прогонов. Проверьте, что сервер обезличивания запущен."
        />
      </Section>
    );
  }

  const rows = asRows(runs.data?.items ?? []);

  if (rows.length === 0) {
    return (
      <Section padding={0}>
        <EmptyState
          title="Ничего не найдено"
          description="Ни один прогон не подходит под выбранные фильтры."
        />
      </Section>
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
              width: pixel(110),
              align: "end",
              renderCell: (run) => (
                <Button
                  size="sm"
                  variant="ghost"
                  label="Открыть"
                  onClick={() => navigate(`/review?run=${run.id}`)}
                />
              ),
            },
          ]}
        />
      </VStack>
    </Section>
  );
}
