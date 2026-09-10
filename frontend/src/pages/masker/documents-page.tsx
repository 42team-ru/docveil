import { useEffect, useState } from "react";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/Stack";

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
 * отчёт. Заголовок «Новый документ» здесь не повторяется отдельной кнопкой:
 * тот же переход уже есть в шапке панели (`PanelShell.navStartContent`,
 * `masker-layout.tsx`), а вторая такая же кнопка на странице путала —
 * два разных по размеру и иконке контрола делали одно и то же.
 */
export function DocumentsPage() {
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
      title="Журнал обработок"
      meta={
        typeof total === "number" ? (
          <Text type="supporting" color="secondary" size="sm">
            {`${total} ${pluralRu(total, ["прогон", "прогона", "прогонов"])}`}
          </Text>
        ) : undefined
      }
    >
      <VStack gap={4}>
        <HistoryFilters />
        <HistoryTable
          runs={runs}
          page={page}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
          hasActiveFilters={hasActiveFilters}
          onResetFilters={resetFilters}
        />
      </VStack>
    </ScreenLayout>
  );
}
