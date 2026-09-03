import { X } from "lucide-react";
import { Heading, Text } from "@astryxdesign/core/Text";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Item } from "@astryxdesign/core/Item";
import { List } from "@astryxdesign/core/List";
import { Section } from "@astryxdesign/core/Section";
import { Token } from "@astryxdesign/core/Token";

import {
  uploadQueue,
  uploadQueueSummary,
} from "../../../entity/document/model/fixtures";
import { FormatToken } from "../../../entity/document/ui/format-token";

/** Очередь файлов, отобранных для текущей задачи. */
export function UploadQueue() {
  return (
    <Section padding={0}>
      <VStack gap={0}>
        <HStack gap={2} vAlign="center" padding={3}>
          <Heading level={5}>
            {`В очереди · ${uploadQueueSummary.files} файла`}
          </Heading>
          <StackItem size="fill" />
          <Text type="supporting" hasTabularNumbers>
            {uploadQueueSummary.size}
          </Text>
        </HStack>
        <List hasDividers density="compact">
          {uploadQueue.map((file) => (
            <Item
              key={file.id}
              as="li"
              density="compact"
              startContent={<FormatToken format={file.format} />}
              label={file.name}
              labelLines={1}
              description={
                <Text type="supporting" color="secondary">
                  {file.meta}
                </Text>
              }
              endContent={
                <HStack gap={2} vAlign="center">
                  <Token
                    size="sm"
                    color={file.needsAttention ? "yellow" : "gray"}
                    label={file.tag}
                  />
                  <IconButton
                    size="sm"
                    variant="ghost"
                    label={`Убрать ${file.name} из очереди`}
                    icon={<Icon icon={X} size="sm" />}
                  />
                </HStack>
              }
            />
          ))}
        </List>
      </VStack>
    </Section>
  );
}
