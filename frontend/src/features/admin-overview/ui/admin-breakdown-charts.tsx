import { Grid } from "@astryxdesign/core/Grid";
import { Section } from "@astryxdesign/core/Section";
import { VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";

import type { AdminOverviewOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { CategoryBarChart } from "../../../shared/ui/charts/category-bar-chart";
import { DonutChart, type DonutDatum } from "../../../shared/ui/charts/donut-chart";
import {
  documentFormatCategoryData,
  maskStyleCategoryData,
  runStatusCategoryData,
} from "../lib/to-category-data";

type AdminBreakdownChartsProps = {
  overview: AdminOverviewOut;
};

/** Три разреза по прогонам за окно: статус, формат документа, стиль маски. */
export function AdminBreakdownCharts({ overview }: AdminBreakdownChartsProps) {
  const statusData: DonutDatum[] = runStatusCategoryData(overview.runs.by_status ?? {}).map(
    (item) => ({ key: item.key, label: item.label, value: item.count }),
  );
  const formatData = documentFormatCategoryData(overview.runs.by_format ?? {});
  const maskStyleData = maskStyleCategoryData(overview.options.by_mask_style ?? {});

  return (
    <Grid columns={{ minWidth: 280, max: 3, repeat: "fit" }} gap={4}>
      <Section padding={5}>
        <VStack gap={3} width="100%" minHeight={0}>
          <Heading level={4}>Статусы прогонов</Heading>
          {statusData.length > 0 ? (
            <DonutChart data={statusData} />
          ) : (
            <Text color="secondary">Данных нет.</Text>
          )}
        </VStack>
      </Section>
      <Section padding={5}>
        <VStack gap={3} width="100%" minHeight={0}>
          <Heading level={4}>Форматы документов</Heading>
          <CategoryBarChart data={formatData} />
        </VStack>
      </Section>
      <Section padding={5}>
        <VStack gap={3} width="100%" minHeight={0}>
          <Heading level={4}>Стиль маскирования</Heading>
          <CategoryBarChart data={maskStyleData} />
        </VStack>
      </Section>
    </Grid>
  );
}
