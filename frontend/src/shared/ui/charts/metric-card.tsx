import { Card } from "@astryxdesign/core/Card";
import { VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";

type MetricCardProps = {
  label: string;
  value: string;
  note?: string;
};

/** Карточка одного числового факта — standalone-виджет (правило AGENTS.md:
 * `Card` для них, не для строк списка). */
export function MetricCard({ label, value, note }: MetricCardProps) {
  return (
    <Card padding={4}>
      <VStack gap={1}>
        <Text type="supporting">{label}</Text>
        <Heading level={3}>{value}</Heading>
        {note ? (
          <Text type="supporting" color="secondary">
            {note}
          </Text>
        ) : null}
      </VStack>
    </Card>
  );
}
