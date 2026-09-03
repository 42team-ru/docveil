import { Item } from "@astryxdesign/core/Item";
import { HStack, StackItem } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import type { AgentTrace } from "../model/types";
import { AgentStateToken } from "./agent-state-token";

/** Карточка агента во вкладке «Агенты»: имя, состояние, вход/выход, время. */
export function AgentTraceItem({ trace }: { trace: AgentTrace }) {
  return (
    <Item
      as="li"
      align="start"
      density="compact"
      label={
        <HStack gap={2} vAlign="center">
          <Text weight="semibold">{trace.name}</Text>
          <AgentStateToken state={trace.state} />
          <StackItem size="fill" />
          <Text type="supporting" color="secondary" hasTabularNumbers>
            {trace.time}
          </Text>
        </HStack>
      }
      description={
        <Text type="code" size="sm" color="secondary">
          {trace.io}
        </Text>
      }
    />
  );
}
