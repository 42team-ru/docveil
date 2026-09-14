import { useEffect, useState } from "react";

import { useAdminRuns, useAdminUsers } from "../../features/admin-overview/api/admin";
import { AdminRunsTable } from "../../features/admin-overview/ui/admin-runs-table";
import { useAdminFiltersStore } from "../../features/admin-overview/model/admin-filters-store";
import { useDebouncedValue } from "../../shared/lib/use-debounced-value";

const PAGE_SIZE = 20;

/** Вкладка «Прогоны»: журнал всех пользователей — в отличие от личного
 * журнала (`document-history`), который видит только свои прогоны. */
export function AdminRunsView() {
  const query = useAdminFiltersStore((state) => state.runQuery);
  const status = useAdminFiltersStore((state) => state.runStatus);
  const ownerId = useAdminFiltersStore((state) => state.runOwnerId);
  // Поле поиска остаётся мгновенным, запрос уходит по отложенному значению —
  // тот же приём, что в `document-history/pages/documents-page.tsx`.
  const debouncedQuery = useDebouncedValue(query, 300);

  const [page, setPage] = useState(1);
  useEffect(() => {
    setPage(1);
  }, [debouncedQuery, status, ownerId]);

  const users = useAdminUsers();
  const runs = useAdminRuns({
    query: debouncedQuery || undefined,
    status: status === "all" ? undefined : status,
    user_id: ownerId ?? undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  return (
    <AdminRunsTable
      runs={runs}
      users={users.data}
      page={page}
      pageSize={PAGE_SIZE}
      onPageChange={setPage}
    />
  );
}
