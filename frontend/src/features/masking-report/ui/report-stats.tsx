import { List, ListItem } from "@astryxdesign/core/List";
import { Section } from "@astryxdesign/core/Section";
import { VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";

import { piiTypeLabel } from "../../../entity/pii/model/pii-type-dict";
import type { MaskingReport, PiiType } from "../../../entity/pii/model/types";
import { pluralRu } from "../../../shared/lib/plural-ru";
import { maskedOccurrences } from "../lib/report-occurrences";

type ReportStatsProps = { report: MaskingReport };

/** Обзор только реально заменённых вхождений, без найденных, но оставленных данных. */
export function ReportStats({ report }: ReportStatsProps) {
  const occurrences = maskedOccurrences(report);
  const byType = new Map<PiiType, number>();
  for (const occurrence of occurrences) {
    byType.set(occurrence.type, (byType.get(occurrence.type) ?? 0) + 1);
  }
  const types = [...byType].sort((left, right) => right[1] - left[1]);
  const possibleCount = occurrences.filter((occurrence) => occurrence.level === "possible").length;

  return (
    <Section padding={4}>
      <VStack gap={3}>
        <VStack gap={1}>
          <Heading level={3}>Что скрыто в документе</Heading>
          <Text color="secondary" textWrap="pretty">
            {occurrences.length === 0
              ? "По данным отчёта замены не применялись."
              : `${occurrences.length} ${pluralRu(occurrences.length, ["фрагмент", "фрагмента", "фрагментов"])} · ${types.length} ${pluralRu(types.length, ["тип", "типа", "типов"])} данных`}
          </Text>
        </VStack>
        {types.length > 0 ? (
          <List hasDividers density="balanced" header="Типы заменённых данных">
            {types.map(([type, count]) => (
              <ListItem
                key={type}
                label={piiTypeLabel(type)}
                endContent={<Text hasTabularNumbers weight="semibold">{count}</Text>}
              />
            ))}
          </List>
        ) : null}
        {possibleCount > 0 ? (
          <Text type="supporting" color="secondary" textWrap="pretty">
            {`${possibleCount} ${pluralRu(possibleCount, ["замену", "замены", "замен"])} с низкой уверенностью стоит проверить в списке ниже. Фрагменты уже скрыты в результате.`}
          </Text>
        ) : null}
      </VStack>
    </Section>
  );
}
