import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { FilePlus2 } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { HistoryFilters } from "../../features/document-history/ui/history-filters";
import { HistoryTable } from "../../features/document-history/ui/history-table";
import { useHistoryFilterStore } from "../../features/document-history/model/history-filter-store";
import { useRunList } from "../../features/masking-run/api/masking-run";
import { pluralRu } from "../../shared/lib/plural-ru";
import { useDebouncedValue } from "../../shared/lib/use-debounced-value";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";

const PAGE_SIZE = 20;

/**
 * Журнал обработанных документов — единственная точка входа в проверку и
 * отчёт. Локальное действие «Новый документ» стоит рядом с фильтрами, чтобы
 * оставаться заметным в контексте списка; глобальный переход остаётся в шапке.
 */
export function DocumentsPage() {
  const navigate = useNavigate();
  const query = useHistoryFilterStore((state) => state.query);
  const status = useHistoryFilterStore((state) => state.status);
  const resetFilters = useHistoryFilterStore((state) => state.reset);
  // Поле ввода остаётся мгновенным (стор пишется на каждое нажатие), а
  // запрос в `GET /api/runs` уходит по отложенному значению — иначе каждый
  // символ поиска — это отдельный round-trip.
  const debouncedQuery = useDebouncedValue(query, 300);

  const [page, setPage] = useState(1);
  useEffect(() => {
    setPage(1);
  }, [debouncedQuery, status]);

  const runs = useRunList({
    query: debouncedQuery || undefined,
    status: status === "all" ? undefined : status,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  const total = runs.data?.total;
  const hasActiveFilters = query !== "" || status !== "all";

  return (
    <ScreenLayout
      title="Журнал документов"
      meta={
        typeof total === "number" ? (
          <Text type="supporting" color="secondary" size="sm">
            {`${total} ${pluralRu(total, ["прогон", "прогона", "прогонов"])}`}
          </Text>
        ) : undefined
      }
    >
      <VStack gap={4} height="100%">
        <HistoryFilters
          actions={(
            <Button
              size="sm"
              variant="primary"
              label="Новый документ"
              icon={<Icon icon={FilePlus2} size="sm" />}
              onClick={() => void navigate("/", { viewTransition: true })}
            />
          )}
        />
        <StackItem size="fill">
          <HistoryTable
            runs={runs}
            page={page}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
            hasActiveFilters={hasActiveFilters}
            onResetFilters={resetFilters}
          />
        </StackItem>
      </VStack>
    </ScreenLayout>
  );
}
