import { Banner } from "@astryxdesign/core/Banner";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { VStack } from "@astryxdesign/core/Stack";

import type { MaskingReport } from "../../entity/pii/model/types";
import { ReportLimitations } from "../../features/masking-report/ui/report-limitations";
import { ReportStats } from "../../features/masking-report/ui/report-stats";
import { ReportTable } from "../../features/masking-report/ui/report-table";

type ReportViewProps = {
  /** `null` — граф ещё не досчитал `report.json` для этого прогона. */
  report: MaskingReport | null;
};

/** Тело вкладки «Отчёт»: сводка и полный перечень замен. */
export function ReportView({ report }: ReportViewProps) {
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
    </VStack>
  );
}
