import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Section } from "@astryxdesign/core/Section";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { VStack } from "@astryxdesign/core/Stack";
import { Heading } from "@astryxdesign/core/Text";

import { useAdminOverview } from "../../features/admin-overview/api/admin";
import { AdminActivityCharts } from "../../features/admin-overview/ui/admin-activity-charts";
import { AdminBreakdownCharts } from "../../features/admin-overview/ui/admin-breakdown-charts";
import { AdminFailuresTable } from "../../features/admin-overview/ui/admin-failures-table";
import { AdminSummaryCards } from "../../features/admin-overview/ui/admin-summary-cards";
import { useAdminFiltersStore } from "../../features/admin-overview/model/admin-filters-store";

/** Вкладка «Обзор»: ключевые факты, динамика и разрезы по системе целиком —
 * не по одному аккаунту, как личный журнал (`document-history`). */
export function AdminOverviewView() {
  const windowDays = useAdminFiltersStore((state) => state.windowDays);
  const overview = useAdminOverview(windowDays);

  if (overview.isLoading) {
    return (
      <Section padding={4}>
        <Skeleton height={400} width="100%" />
      </Section>
    );
  }

  if (overview.isError || !overview.data) {
    return (
      <Banner
        status="error"
        container="card"
        collapsible={false}
        title="Сводка недоступна"
        description="Не удалось загрузить агрегаты админки."
        endContent={
          <Button size="sm" variant="secondary" label="Повторить" onClick={() => void overview.refetch()} />
        }
      />
    );
  }

  return (
    <VStack gap={6}>
      <AdminSummaryCards overview={overview.data} />
      <AdminActivityCharts overview={overview.data} />
      <AdminBreakdownCharts overview={overview.data} />
      <VStack gap={3}>
        <Heading level={4}>Чаще всего падает</Heading>
        <AdminFailuresTable failures={overview.data.failures ?? []} />
      </VStack>
    </VStack>
  );
}
