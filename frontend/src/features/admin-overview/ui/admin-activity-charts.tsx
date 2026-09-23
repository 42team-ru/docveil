import { Grid } from "@astryxdesign/core/Grid";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Section } from "@astryxdesign/core/Section";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Heading } from "@astryxdesign/core/Text";

import type { AdminOverviewOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { TrendAreaChart } from "../../../shared/ui/charts/trend-area-chart";
import { type AdminWindowDays, useAdminFiltersStore } from "../model/admin-filters-store";

const WINDOW_OPTIONS: AdminWindowDays[] = [7, 30, 90];

type AdminActivityChartsProps = {
  overview: AdminOverviewOut;
};

/** Регистрации и прогоны по дням — с переключателем окна 7/30/90. */
export function AdminActivityCharts({ overview }: AdminActivityChartsProps) {
  const windowDays = useAdminFiltersStore((state) => state.windowDays);
  const setWindowDays = useAdminFiltersStore((state) => state.setWindowDays);

  return (
    <VStack gap={3}>
      <HStack hAlign="end">
        <SegmentedControl
          label="Окно агрегатов"
          size="sm"
          value={String(windowDays)}
          onChange={(value) => setWindowDays(Number(value) as AdminWindowDays)}
        >
          {WINDOW_OPTIONS.map((days) => (
            <SegmentedControlItem key={days} value={String(days)} label={`${days} дн.`} />
          ))}
        </SegmentedControl>
      </HStack>
      <Grid columns={{ minWidth: 280, max: 2, repeat: "fit" }} gap={4}>
        <Section padding={5}>
          <VStack gap={3} width="100%" minHeight={0}>
            <Heading level={4}>Регистрации</Heading>
            <TrendAreaChart data={overview.users.signups_by_day ?? []} />
          </VStack>
        </Section>
        <Section padding={5}>
          <VStack gap={3} width="100%" minHeight={0}>
            <Heading level={4}>Прогоны</Heading>
            <TrendAreaChart data={overview.runs.by_day ?? []} />
          </VStack>
        </Section>
      </Grid>
    </VStack>
  );
}
