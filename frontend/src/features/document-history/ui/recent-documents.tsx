import { useNavigate } from "react-router";
import { Files } from "lucide-react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { Section } from "@astryxdesign/core/Section";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Heading, Text } from "@astryxdesign/core/Text";

import type { DocumentFormat } from "../../../entity/document/model/types";
import { FormatToken } from "../../../entity/document/ui/format-token";
import { RunStatusToken } from "../../../entity/document/ui/run-status-token";
import { formatMoment } from "../../../shared/lib/format-moment";
import { useRunList } from "../../masking-run/api/masking-run";
import type { RunListItem } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { recentRuns } from "../lib/recent-runs";

/**
 * `Table` требует от строки индексной сигнатуры, а сгенерированный из
 * OpenAPI интерфейс её не имеет (тот же приём, что в `history-table.tsx`).
 */
type RecentRunRow = RunListItem & Record<string, unknown>;

/** Последние пять запусков на экране создания новой задачи. */
export function RecentDocuments() {
  const navigate = useNavigate();
  const runs = useRunList({ limit: 5 });

  if (runs.isLoading) {
    return (
      <Section padding={4}>
        <Skeleton height={220} width="100%" />
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
          title="Последние документы недоступны"
          description="Не удалось получить журнал обработок."
          endContent={
            <Button size="sm" variant="secondary" label="Повторить" onClick={() => void runs.refetch()} />
          }
        />
      </Section>
    );
  }

  const documents = recentRuns(runs.data?.items ?? []) as RecentRunRow[];

  if (documents.length === 0) {
    return (
      <Section padding={0}>
        <EmptyState
          icon={<Icon icon={Files} size="lg" color="secondary" />}
          title="Здесь появятся последние документы"
          description="Загрузите первый файл, чтобы начать обработку."
        />
      </Section>
    );
  }

  return (
    <Section padding={0}>
      <VStack gap={4} paddingBlock={4} paddingInline={4}>
        <Heading level={4}>Последние документы</Heading>

        <Table<RecentRunRow>
          data={documents}
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
              width: pixel(90),
              renderCell: (run) => (
                <FormatToken
                  format={run.document.format.toUpperCase() as DocumentFormat}
                />
              ),
            },
            {
              key: "created_at",
              header: "Запущен",
              width: pixel(130),
              renderCell: (run) => (
                <Text color="secondary">{formatMoment(run.created_at)}</Text>
              ),
            },
            {
              key: "status",
              header: "Статус",
              width: pixel(150),
              renderCell: (run) => <RunStatusToken status={run.status} />,
            },
            {
              key: "actions",
              header: "",
              width: pixel(100),
              align: "end",
              renderCell: (run) => (
                <Button
                  size="sm"
                  variant="ghost"
                  label="Открыть"
                  onClick={() => navigate(`/documents/${run.id}`)}
                />
              ),
            },
          ]}
        />

        <HStack hAlign="end">
          <Button
            size="sm"
            variant="secondary"
            label="Все документы"
            onClick={() => navigate("/documents")}
          />
        </HStack>
      </VStack>
    </Section>
  );
}
