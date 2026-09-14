import { Files, X } from "lucide-react";
import { AnimatePresence } from "motion/react";
import { Heading, Text } from "@astryxdesign/core/Text";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { List } from "@astryxdesign/core/List";
import { Section } from "@astryxdesign/core/Section";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Token } from "@astryxdesign/core/Token";

import { FormatToken } from "../../../entity/document/ui/format-token";
import {
  formatSize,
  useUploadQueueStore,
  type QueuedUpload,
} from "../../../entity/document/model/upload-queue-store";
import { MotionItem, listItemMotion } from "../../../shared/ui/motion/motion-astryx";

const STATE_LABEL: Record<QueuedUpload["state"], string> = {
  pending: "готов",
  starting: "отправка",
  started: "в работе",
  failed: "ошибка",
};

/** Очередь файлов, отобранных для текущей задачи. */
export function UploadQueue() {
  const items = useUploadQueueStore((state) => state.items);
  const remove = useUploadQueueStore((state) => state.remove);

  const totalSize = items.reduce((sum, item) => sum + (item.size ?? 0), 0);

  if (items.length === 0) {
    return (
      <VStack height="100%" hAlign="center" vAlign="center">
        <EmptyState
          isCompact
          icon={<Icon icon={Files} size="lg" />}
          title="Очередь пуста"
          description="Перетащите документы слева — они появятся здесь."
        />
      </VStack>
    );
  }

  return (
    <Section padding={0}>
      <VStack gap={0}>
        <HStack gap={2} vAlign="center" padding={3}>
          <Heading level={5}>{`В очереди · ${items.length}`}</Heading>
          <StackItem size="fill" />
          <Text type="supporting" hasTabularNumbers>
            {formatSize(totalSize)}
          </Text>
        </HStack>
        <List hasDividers density="compact">
          <AnimatePresence initial={false}>
            {items.map((item) => (
              <MotionItem
                key={item.id}
                {...listItemMotion}
                as="li"
                density="compact"
                startContent={<FormatToken format={item.format} />}
                label={item.name}
                labelLines={1}
                description={
                  <VStack gap={0}>
                    <Text type="supporting" color="secondary">
                      {formatSize(item.size)}
                    </Text>
                    {item.error !== null ? (
                      <Text type="supporting" className="text-red-vivid">
                        {item.error}
                      </Text>
                    ) : null}
                  </VStack>
                }
                endContent={
                  <HStack gap={2} vAlign="center">
                    {item.state === "starting" ? (
                      <Spinner size="sm" shade="subtle" aria-label="Отправка" />
                    ) : null}
                    <Token
                      size="sm"
                      color={item.state === "failed" ? "red" : "gray"}
                      label={STATE_LABEL[item.state]}
                    />
                    <IconButton
                      size="sm"
                      variant="ghost"
                      label={`Убрать ${item.name} из очереди`}
                      icon={<Icon icon={X} size="sm" />}
                      onClick={() => remove(item.id)}
                    />
                  </HStack>
                }
              />
            ))}
          </AnimatePresence>
        </List>
      </VStack>
    </Section>
  );
}
