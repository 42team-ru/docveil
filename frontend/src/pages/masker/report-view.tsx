import { useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { List, ListItem } from "@astryxdesign/core/List";
import { Section } from "@astryxdesign/core/Section";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Heading, Text } from "@astryxdesign/core/Text";

import type { MaskingReport } from "../../entity/pii/model/types";
import { ReportLimitations } from "../../features/masking-report/ui/report-limitations";
import { ReportResources } from "../../features/masking-report/ui/report-resources";
import { ReportStats } from "../../features/masking-report/ui/report-stats";
import { ReportTable } from "../../features/masking-report/ui/report-table";
import { useRuntimeMetrics } from "../../features/masking-run/api/masking-run";

type ReportViewProps = {
  /** `null` — граф ещё не досчитал `report.json` для этого прогона. */
  report: MaskingReport | null;
  runId: string | null;
};

/** Тело вкладки «Отчёт»: сводка и полный перечень замен. */
export function ReportView({ report, runId }: ReportViewProps) {
  const [tab, setTab] = useState("report");
  const runtime = useRuntimeMetrics(runId, report?.telemetry?.runtime.available === true);
  if (!report) {
    return (
      <EmptyState
        title="Отчёта нет"
        description="Движок не вернул отчёт для этого документа."
      />
    );
  }

  return (
    <VStack gap={5}>
      <TabList value={tab} onChange={setTab} role="tablist" hasDivider>
        <Tab value="report" label="Отчёт" panelId="report-content" />
        <Tab value="certificate" label="Сертификат" panelId="report-content" />
        <Tab value="resources" label="Ресурсы" panelId="report-content" />
      </TabList>

      {tab === "certificate" ? <Certificate report={report} /> : null}
      {tab === "resources" ? <ReportResources report={report} runtime={runtime.data} /> : null}
      {tab === "report" ? <>
      <ReportStats report={report} />

      {report.detectionCoverage.requestedWithoutDetector.length > 0 ? (
        <Banner
          status="info"
          container="section"
          collapsible={false}
          title="Не все запрошенные типы ищутся"
          description={`Детектора пока нет: ${report.detectionCoverage.requestedWithoutDetector.join(", ")}. Замен по этим типам в документе не будет.`}
        />
      ) : null}

      <ReportTable report={report} />

      <ReportLimitations report={report} />
      </> : null}
    </VStack>
  );
}

function Certificate({ report }: { report: MaskingReport }) {
  const certificate = report.certificate ?? report.validation?.certificate;
  if (!certificate) {
    return <Banner status="info" title="Сертификат пока не создан" description="Он формируется только после реального рендера артефактов; в режиме предпросмотра проверять нечего." collapsible={false} />;
  }
  return <VStack gap={4}>
    <Banner status={certificate.ok ? "success" : "error"} title={certificate.ok ? "Обезличивание подтверждено" : "Проверка обезличивания не пройдена"} description={certificate.ok ? "Все обязательные проверки завершились успешно." : "Откройте пункты проверки ниже."} collapsible={false} />
    <Section>
      <List hasDividers header={<Heading level={4}>Проверки</Heading>}>
        {certificate.checks.map((check) => <ListItem key={check.name} label={<VStack gap={1}><HStack gap={2}><Text weight="semibold">{check.ok ? "Пройдено" : "Не пройдено"}</Text><Text>{check.name}</Text></HStack><Text color="secondary" textWrap="pretty">{check.detail}</Text></VStack>} />)}
      </List>
    </Section>
  </VStack>;
}
