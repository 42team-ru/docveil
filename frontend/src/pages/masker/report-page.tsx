import { FileText, Sheet, Download } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { ReportStats } from "../../features/masking-report/ui/report-stats";
import { ReportTable } from "../../features/masking-report/ui/report-table";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";

/** Итог прогона: сводка и полный перечень замен. */
export function ReportPage() {
  return (
    <ScreenLayout
      title="Отчёт о заменах"
      meta={
        <HStack gap={2} vAlign="center">
          <Text type="supporting" hasTabularNumbers>
            Договор_поставки_2026-114
          </Text>
          <Text type="supporting" color="secondary">·</Text>
          <Text type="supporting" color="secondary">
            прогон 2
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
        <ReportStats />
        <ReportTable />
      </VStack>
    </ScreenLayout>
  );
}
