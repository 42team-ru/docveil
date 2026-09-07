import { Card } from "@astryxdesign/core/Card";
import { Grid } from "@astryxdesign/core/Grid";
import { VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";

import { piiTypeLabel } from "../../../entity/pii/model/pii-type-dict";
import type { MaskingReport } from "../../../entity/pii/model/types";

type ReportStatsProps = {
  report: MaskingReport;
};

type Stat = { label: string; value: string; note: string };

/** Самый частый тип — чтобы плитка говорила, чего в документе больше всего. */
function topType(byType: Record<string, number>): string {
  const entries = Object.entries(byType);
  if (entries.length === 0) return "—";

  const [type, count] = entries.reduce((best, current) =>
    current[1] > best[1] ? current : best,
  );
  return `${piiTypeLabel(type as never)} — ${count}`;
}

function buildStats(report: MaskingReport): Stat[] {
  const groups = report.plan?.groups.length ?? 0;
  const validation = report.validation;
  const minConfidence = report.summary.minimumConfidence;

  return [
    {
      label: "Найдено сущностей",
      value: String(report.summary.entitiesTotal),
      note: `${groups} групп замен · ${report.extraction.chunkCount} фрагментов`,
    },
    {
      label: "Чаще всего",
      value: topType(report.summary.byType),
      note: Object.entries(report.summary.bySource)
        .map(([source, count]) => `${source}: ${count}`)
        .join(" · "),
    },
    {
      label: "Низшая уверенность",
      value: minConfidence === null ? "—" : minConfidence.toFixed(2),
      note:
        minConfidence !== null && minConfidence < 0.6
          ? "есть находки, требующие проверки"
          : "все находки выше порога проверки",
    },
    {
      label: "Проверка утечек",
      value: validation?.ok ? "чисто" : "не пройдена",
      note: validation
        ? `утечек: ${validation.leakedCount} · остатков: ${validation.residualCount}`
        : "проверка не выполнялась",
    },
  ];
}

/** Четыре плитки со сводкой прогона — цифры из `report.summary` и `report.validation`. */
export function ReportStats({ report }: ReportStatsProps) {
  return (
    <Grid columns={{ minWidth: 200, max: 4, repeat: "fit" }} gap={3}>
      {buildStats(report).map((stat) => (
        <Card key={stat.label} padding={4}>
          <VStack gap={1}>
            <Text type="supporting" weight="medium">
              {stat.label}
            </Text>
            <Heading level={2}>{stat.value}</Heading>
            <Text type="supporting">{stat.note}</Text>
          </VStack>
        </Card>
      ))}
    </Grid>
  );
}
