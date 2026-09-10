import { Card } from "@astryxdesign/core/Card";
import { List, ListItem } from "@astryxdesign/core/List";
import { VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";

import type { MaskingReport } from "../../../entity/pii/model/types";

type ReportLimitationsProps = {
  report: MaskingReport;
};

/**
 * Известные ограничения движка — то, что он сознательно не проверяет.
 * Отдельная карточка, а не подпись в подвале отчёта: это не мелкий комментарий
 * к таблице, а самостоятельное предупреждение оператору.
 */
export function ReportLimitations({ report }: ReportLimitationsProps) {
  return (
    <Card padding={4}>
      <VStack gap={3}>
        <Heading level={5}>Чего движок не покрывает</Heading>
        <List listStyle="disc" density="compact">
          {report.limitations.map((limitation) => (
            <ListItem
              key={limitation}
              label={
                <Text color="secondary" textWrap="pretty">
                  {limitation}
                </Text>
              }
            />
          ))}
        </List>
      </VStack>
    </Card>
  );
}
