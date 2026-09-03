import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

import {
  partyRoles,
  partyRolesNote,
} from "../../../entity/agent/model/fixtures";

/** Кто в договоре поставщик, а кто покупатель — и насколько агент в этом уверен. */
export function PartyRolesPanel() {
  return (
    <Section padding={4}>
      <VStack gap={3}>
        <Heading level={5}>Роли сторон</Heading>
        {partyRoles.map((role) => (
          <HStack key={role.role} gap={2} vAlign="center" wrap="wrap">
            <Text type="supporting" weight="medium">
              {role.role}
            </Text>
            <Text
              weight="medium"
              color={role.isResolved ? "primary" : "secondary"}
            >
              {role.value}
            </Text>
            <StackItem size="fill" />
            <Token
              size="sm"
              color={role.isResolved ? "green" : "red"}
              label={role.confidence.toFixed(2)}
            />
          </HStack>
        ))}
        <Text type="supporting" textWrap="pretty">
          {partyRolesNote}
        </Text>
      </VStack>
    </Section>
  );
}
