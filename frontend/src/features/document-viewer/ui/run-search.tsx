import { useEffect, useState } from "react";
import { Card } from "@astryxdesign/core/Card";
import { List, ListItem } from "@astryxdesign/core/List";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { VStack } from "@astryxdesign/core/Stack";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Search } from "lucide-react";
import { useNavigate } from "react-router";

import { FormatToken } from "../../../entity/document/ui/format-token";
import { RunStatusToken } from "../../../entity/document/ui/run-status-token";
import { useListRunsApiRunsGet } from "../../../shared/api/generated/core/runs/runs";
import type { DocumentFormat } from "../../../entity/document/model/types";
import {
  toReviewableRunSearchItems,
  type RunSearchItem,
} from "../model/run-search";

/** Поиск завершённых прогонов, которые можно открыть в области проверки. */
export function RunSearch() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, 250);
  const runs = useListRunsApiRunsGet({
    query: debouncedQuery.trim() || undefined,
    limit: 20,
  });
  const items = toReviewableRunSearchItems(
    runs.data?.status === 200 ? runs.data.data.items : [],
  );
  const visibleItems = items.slice(0, 3);

  return (
    <Card width={480} padding={5} elevation="low">
      <VStack gap={4}>
        <VStack gap={1}>
          <Heading level={3}>Выберите документ</Heading>
        </VStack>
        <TextInput
          label="Поиск"
          value={query}
          onChange={setQuery}
          placeholder="Найдите файл по названию"
          startIcon={Search}
          hasClear
          isLoading={runs.isFetching}
          width="100%"
        />
        {runs.isLoading ? (
          <Skeleton height={144} width="100%" />
        ) : items.length > 0 ? (
          <List
            density="balanced"
            hasDividers
            header={<Heading level={4}>Документы</Heading>}
          >
            {visibleItems.map((item, index) => (
              <RunSearchResult
                key={item.id}
                item={item}
                isLast={index === visibleItems.length - 1}
                onSelect={() =>
                  navigate(`/review?run=${encodeURIComponent(item.id)}`)
                }
              />
            ))}
          </List>
        ) : (
          <Text color="secondary" type="supporting">
            Подходящих документов не найдено.
          </Text>
        )}
      </VStack>
    </Card>
  );
}

function RunSearchResult({
  item,
  isLast,
  onSelect,
}: {
  item: RunSearchItem;
  isLast: boolean;
  onSelect: () => void;
}) {
  const run = item.auxiliaryData;
  if (!run) return null;

  return (
    <ListItem
      label={item.label}
      description={run.document.format.toUpperCase()}
      startContent={
        <FormatToken
          format={run.document.format.toUpperCase() as DocumentFormat}
        />
      }
      endContent={<RunStatusToken status={run.status} />}
      onClick={onSelect}
      className={isLast ? "border-b-0" : undefined}
    />
  );
}

function useDebouncedValue(value: string, delayMs: number): string {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedValue(value), delayMs);
    return () => window.clearTimeout(timeout);
  }, [delayMs, value]);

  return debouncedValue;
}
