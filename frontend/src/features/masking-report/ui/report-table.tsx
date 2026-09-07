import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

import { flattenPiiOccurrences } from "../../../entity/pii/model/flatten";
import { piiTypeLabel } from "../../../entity/pii/model/pii-type-dict";
import type {
  DecisionSource,
  MaskingReport,
} from "../../../entity/pii/model/types";

type ReportTableProps = {
  report: MaskingReport;
};

/**
 * Строка отчёта — ровно то, что описано в ARCHITECTURE.md: тип, исходное
 * значение, маркер, место, кем найдено, уверенность. Плюс сторона договора и
 * то, кто принял решение: без последнего непонятно, отработал ли инвариант
 * критичных типов.
 */
type ReportRow = {
  id: string;
  type: string;
  original: string;
  marker: string;
  where: string;
  foundBy: string;
  confidence: string;
  side: string;
  decidedBy: DecisionSource | null;
};

/** Как подписан источник решения в колонке «Решение». */
const DECIDED_BY_LABEL: Record<DecisionSource, string> = {
  critical_guard: "гвардия",
  entity: "оператор",
  profile: "по стороне",
  type: "по типу",
  judge: "судья",
  default: "по умолчанию",
};

const DECIDED_BY_COLOR: Record<DecisionSource, "red" | "blue" | "gray"> = {
  critical_guard: "red",
  entity: "blue",
  profile: "blue",
  type: "blue",
  judge: "gray",
  default: "gray",
};

function buildRows(report: MaskingReport): ReportRow[] {
  const decisionByRef = new Map(
    (report.decisions?.byRef ?? []).map((decision) => [decision.ref, decision]),
  );
  const roleByProfileId = new Map(
    report.profiles.map((profile) => [
      profile.id,
      profile.roleTitle || profile.markerLabel,
    ]),
  );
  const profileByGroupId = new Map(
    (report.plan?.groups ?? []).map((group) => [group.id, group.profileId]),
  );

  return flattenPiiOccurrences(report.extraction).map((occurrence) => {
    const profileId = profileByGroupId.get(occurrence.groupId) ?? "";

    return {
      id: occurrence.id,
      type: piiTypeLabel(occurrence.type),
      original: occurrence.originalText,
      marker: occurrence.marker,
      where: occurrence.anchor.label,
      foundBy: occurrence.source,
      confidence: occurrence.confidence.toFixed(2),
      side: roleByProfileId.get(profileId) ?? "—",
      decidedBy: decisionByRef.get(occurrence.ref)?.decidedBy ?? null,
    };
  });
}

/** Перечень заменённых фрагментов — то, что уходит в CSV/XLSX/PDF-отчёт. */
export function ReportTable({ report }: ReportTableProps) {
  const rows = buildRows(report);

  return (
    <Section padding={0}>
      <VStack gap={0} paddingInline={4}>
        <HStack gap={2} vAlign="center" paddingBlock={3}>
          <Heading level={5}>Перечень заменённых фрагментов</Heading>
          <StackItem size="fill" />
          <Text type="supporting" hasTabularNumbers>
            {`${rows.length} записей`}
          </Text>
        </HStack>
        <Table<ReportRow>
          data={rows}
          idKey="id"
          density="balanced"
          hasHover
          textOverflow="truncate"
          columns={[
            { key: "type", header: "Тип", width: pixel(150) },
            { key: "original", header: "Оригинал", width: proportional(1) },
            {
              key: "marker",
              header: "Маркер",
              width: pixel(210),
              renderCell: (row) => (
                <Text type="code" size="sm">
                  {row.marker}
                </Text>
              ),
            },
            {
              key: "where",
              header: "Где",
              width: pixel(150),
              renderCell: (row) => (
                <Text color="secondary">{row.where}</Text>
              ),
            },
            { key: "side", header: "Сторона", width: pixel(130) },
            {
              key: "foundBy",
              header: "Найдено",
              width: pixel(100),
              renderCell: (row) => (
                <Text color="secondary">{row.foundBy}</Text>
              ),
            },
            {
              key: "confidence",
              header: "Увер.",
              width: pixel(80),
              renderCell: (row) => (
                <Text hasTabularNumbers>{row.confidence}</Text>
              ),
            },
            {
              key: "decidedBy",
              header: "Решение",
              width: pixel(130),
              renderCell: (row) =>
                row.decidedBy ? (
                  <Token
                    size="sm"
                    color={DECIDED_BY_COLOR[row.decidedBy]}
                    label={DECIDED_BY_LABEL[row.decidedBy]}
                  />
                ) : (
                  <Text color="secondary">—</Text>
                ),
            },
          ]}
        />
      </VStack>
    </Section>
  );
}
