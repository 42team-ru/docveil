import { Card } from "@astryxdesign/core/Card";
import { Grid } from "@astryxdesign/core/Grid";
import { VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";

import { reportStats } from "../../../entity/document/model/fixtures";

/** Четыре плитки со сводкой по прогону. */
export function ReportStats() {
  return (
    <Grid columns={{ minWidth: 200, max: 4, repeat: "fit" }} gap={3}>
      {reportStats.map((stat) => (
        <Card key={stat.label} padding={4}>
          <VStack gap={1}>
            <Text type="supporting" weight="medium">
              {stat.label}
            </Text>
            <Heading level={2}>
              {stat.value}
            </Heading>
            <Text type="supporting">{stat.note}</Text>
          </VStack>
        </Card>
      ))}
    </Grid>
  );
}
