import type { CSSProperties } from "react";
import { ArrowRight, Check, Undo2 } from "lucide-react";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Icon } from "@astryxdesign/core/Icon";
import { Item } from "@astryxdesign/core/Item";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

import type { MaskFragment, MaskStatus } from "../model/types";
import { ConfidenceMark } from "./confidence-mark";
import { MaskStatusToken } from "./mask-status-token";

type MaskListItemProps = {
  fragment: MaskFragment;
  status: MaskStatus;
  isSelected: boolean;
  onSelect: (id: string) => void;
  onConfirm: (id: string) => void;
  onReject: (id: string) => void;
};

/**
 * Строка списка замен. Клик по строке выбирает фрагмент.
 * Кнопки решения появляются на месте бейджа статуса,
 * поэтому высота карточки не прыгает при выборе.
 */
export function MaskListItem({
  fragment,
  status,
  isSelected,
  onSelect,
  onConfirm,
  onReject,
}: MaskListItemProps) {
  const itemStyle: CSSProperties = {
    borderBottom: "1px solid var(--color-border)",
    borderLeft: isSelected ? "3px solid var(--color-accent)" : "3px solid transparent",
    backgroundColor: isSelected ? "var(--color-background-muted)" : "transparent",
    transition: "background-color 0.15s ease-out, border-color 0.15s ease-out",
  };

  return (
    <VStack gap={0} as="li" style={itemStyle}>
      <Item
        density="spacious"
        align="start"
        isSelected={false} // Мы стилизуем выделение через обёртку
        onClick={() => onSelect(fragment.id)}
        label={
          <HStack gap={2} vAlign="center">
            <Text type="supporting" weight="medium">
              {fragment.type}
            </Text>
            <ConfidenceMark value={fragment.confidence} />
            <StackItem size="fill" />
            <Text type="supporting" color="secondary" hasTabularNumbers>
              {`стр. ${fragment.page}`}
            </Text>
          </HStack>
        }
        description={
          <HStack gap={1.5} vAlign="center" wrap="wrap">
            <Text color="secondary" hasStrikethrough maxLines={1}>
              {fragment.original}
            </Text>
            <Icon icon={ArrowRight} size="xsm" color="secondary" />
            <Token size="sm" label={fragment.marker} />
          </HStack>
        }
        endContent={
          isSelected ? (
            <HStack gap={1} vAlign="center">
              <IconButton
                size="sm"
                variant={status === "ok" ? "ghost" : "primary"}
                icon={<Icon icon={Check} size="sm" />}
                label="Подтвердить"
                isDisabled={status === "ok"}
                onClick={(e) => {
                  e.stopPropagation();
                  onConfirm(fragment.id);
                }}
              />
              <IconButton
                size="sm"
                variant="ghost"
                icon={<Icon icon={Undo2} size="sm" />}
                label="Вернуть"
                isDisabled={status === "pending"}
                onClick={(e) => {
                  e.stopPropagation();
                  onReject(fragment.id);
                }}
              />
            </HStack>
          ) : (
            <MaskStatusToken status={status} />
          )
        }
      />
    </VStack>
  );
}
