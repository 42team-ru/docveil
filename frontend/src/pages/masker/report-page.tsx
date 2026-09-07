import { Sheet, Download } from "lucide-react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { ReportStats } from "../../features/masking-report/ui/report-stats";
import { ReportTable } from "../../features/masking-report/ui/report-table";
import { useReviewData } from "../../features/pii-review/api/use-review-data";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";

/**
 * Итог прогона: сводка и полный перечень замен.
 *
 * Данные берёт из того же шва, что и экран проверки (`useReviewData`), — иначе
 * отчёт рассказывает про один документ, а панель проверки про другой. Раньше
 * имя документа и цифры были вписаны в разметку руками.
 */
export function ReportPage() {
  const { report } = useReviewData();

  if (!report) {
    return (
      <ScreenLayout title="Отчёт о заменах">
        <EmptyState
          title="Отчёта нет"
          description="Движок не вернул отчёт для этого документа."
        />
      </ScreenLayout>
    );
  }

  return (
    <ScreenLayout
      title="Отчёт о заменах"
      meta={
        <HStack gap={2} vAlign="center">
          <Text type="supporting" hasTabularNumbers>
            {report.input}
          </Text>
          <Text type="supporting" color="secondary">
            ·
          </Text>
          <Text type="supporting" color="secondary">
            {report.decisions?.mode === "interactive"
              ? "с ответами оператора"
              : "без вопросов оператору"}
          </Text>
        </HStack>
      }
      actions={
        <HStack gap={2}>
          <Button size="sm" variant="ghost" label="CSV" icon={<Icon icon={Sheet} size="sm" />} />
          <Button size="sm" variant="ghost" label="XLSX" icon={<Icon icon={Sheet} size="sm" />} />
          <Button size="sm" variant="primary" label="PDF-отчёт" icon={<Icon icon={Download} size="sm" />} />
        </HStack>
      }
    >
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

        <VStack gap={2} paddingInline={4} paddingBlock={2}>
          <Text type="supporting" weight="medium">
            Чего движок не покрывает
          </Text>
          {report.limitations.map((limitation) => (
            <Text key={limitation} type="supporting" color="secondary" textWrap="pretty">
              {limitation}
            </Text>
          ))}
        </VStack>
      </VStack>
    </ScreenLayout>
  );
}
