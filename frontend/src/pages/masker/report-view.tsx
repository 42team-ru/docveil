import { Banner } from "@astryxdesign/core/Banner";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { List, ListItem } from "@astryxdesign/core/List";
import { Section } from "@astryxdesign/core/Section";
import { VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";

import type { MaskingReport } from "../../entity/pii/model/types";
import { piiTypeLabel } from "../../entity/pii/model/pii-type-dict";
import { maskedOccurrences } from "../../features/masking-report/lib/report-occurrences";
import { ReportTable } from "../../features/masking-report/ui/report-table";
import type { RunStatus } from "../../features/masking-run/api/masking-run";
import { pluralRu } from "../../shared/lib/plural-ru";

type ReportViewProps = {
  report: MaskingReport | null;
  runId: string | null;
  status?: RunStatus | null;
  canDownload?: boolean;
};

/** Отчёт для оператора: вывод, фактические замены и проверки результата. */
export function ReportView({ report, status = null }: ReportViewProps) {
  if (!report) {
    return (
      <EmptyState
        title="Отчёта нет"
        description="Движок не вернул отчёт для этого документа."
      />
    );
  }

  return (
    <VStack gap={6}>
      <ReportConclusion report={report} status={status} />
      <ReportUsage report={report} />
      <ReportTable report={report} />
      <ReportChecks report={report} />
    </VStack>
  );
}

function ReportUsage({ report }: { report: MaskingReport }) {
  const telemetry = report.telemetry?.llm;
  if (!telemetry) return null;

  const tokens = telemetry.promptTokens + telemetry.completionTokens;
  const amount = telemetry.cost?.amount;
  const currency = telemetry.cost?.currency;
  const numericCost =
    typeof amount === "string" && amount.trim() !== ""
      ? Number(amount)
      : Number.NaN;
  const formattedCost = Number.isFinite(numericCost)
    ? numericCost.toLocaleString("ru-RU", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    : null;
  const cost = formattedCost !== null
    ? `${formattedCost} ${currency === "RUB" ? "₽" : String(currency ?? "")}`.trim()
    : "стоимость не рассчитана";
  const summary = [
    `${telemetry.calls} ${pluralRu(telemetry.calls, [
      "обращение к модели",
      "обращения к модели",
      "обращений к модели",
    ])}`,
    cost,
    tokens > 0 ? `${tokens.toLocaleString("ru-RU")} токенов` : null,
  ].filter((part): part is string => part !== null).join(" · ");

  return (
    <Section padding={3}>
      <VStack gap={1}>
        <Heading level={3}>Обработка документа</Heading>
        <Text color="secondary" textWrap="pretty">
          {summary}
        </Text>
      </VStack>
    </Section>
  );
}

const CHECK_LABELS: Record<string, string> = {
  leak_scan: "Исходные данные не остались в файле",
  metadata_cleared: "Личные данные удалены из метаданных",
};

function ReportChecks({ report }: { report: MaskingReport }) {
  const certificate = report.certificate ?? report.validation?.certificate;
  const missingTypes = report.detectionCoverage.requestedWithoutDetector;
  const visibleChecks = (certificate?.checks ?? []).filter(
    (check) => check.name !== "width_quantization",
  );
  const hasChecks = visibleChecks.length > 0;
  const hasWarnings = missingTypes.length > 0 || report.limitations.length > 0;

  if (!hasChecks && !hasWarnings) return null;

  return (
    <Section padding={0}>
      <VStack gap={3}>
        <VStack gap={1}>
          <Heading level={3}>Проверки и ограничения</Heading>
          {hasChecks ? (
            <Text color="secondary">
              {visibleChecks.every((check) => check.ok)
                ? "Основные проверки результата пройдены."
                : "Есть проверки, требующие внимания."}
            </Text>
          ) : null}
        </VStack>
        {hasChecks ? (
          <List hasDividers header="Результаты проверок">
            {visibleChecks.map((check) => (
              <ListItem
                key={check.name}
                label={`${check.ok ? "Пройдено" : "Не пройдено"} · ${CHECK_LABELS[check.name] ?? check.name}`}
                description={!check.ok ? check.detail : undefined}
              />
            ))}
          </List>
        ) : null}
        {/*{missingTypes.length > 0 ? (*/}
        {/*  <Banner*/}
        {/*    status="warning"*/}
        {/*    container="section"*/}
        {/*    collapsible={false}*/}
        {/*    title="Некоторые типы данных не проверялись"*/}
        {/*    description={`Для ${missingTypes.map(piiTypeLabel).join(", ")} пока нет детектора. Эти данные могли остаться в документе.`}*/}
        {/*  />*/}
        {/*) : null}*/}
        {report.limitations.length > 0 ? (
          <List header="Известные ограничения" listStyle="disc">
            {report.limitations.map((limitation) => (
              <ListItem key={limitation} label={<Text textWrap="pretty">{limitation}</Text>} />
            ))}
          </List>
        ) : null}
      </VStack>
    </Section>
  );
}

function ReportConclusion({ report, status }: {
  report: MaskingReport;
  status: RunStatus | null;
}) {
  const replacementCount = maskedOccurrences(report).length;
  const failed = status === "leaked" || report.validation?.ok === false;
  const completed = status === "done" && report.validation?.ok === true;
  const title = failed
    ? "Проверка результата не пройдена"
    : completed
      ? "Обезличивание завершено"
      : status === "awaiting_review"
        ? "Документ ждёт вашей проверки"
        : "Результат обработки";
  const validationNote = report.validation
    ? report.validation.ok
      ? "Исходные данные не найдены в результате."
      : `Обнаружено ${report.validation.leakedCount} утечек и ${report.validation.residualCount} остатков.`
    : "Данных о проверке утечек нет.";

  return (
    <Banner
      status={failed ? "error" : completed ? "success" : status === "awaiting_review" ? "warning" : "info"}
      container="section"
      collapsible={false}
      title={title}
      description={`${replacementCount} ${pluralRu(replacementCount, ["фрагмент заменён", "фрагмента заменены", "фрагментов заменено"])}. ${validationNote}`}
    />
  );
}
