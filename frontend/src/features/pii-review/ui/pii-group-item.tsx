import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight, Undo2 } from "lucide-react";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Icon } from "@astryxdesign/core/Icon";
import { Item } from "@astryxdesign/core/Item";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import type { FlatPiiOccurrence } from "../../../entity/pii/model/flatten";
import { piiTypeLabel } from "../../../entity/pii/model/pii-type-dict";
import type { PiiDecisionKind, PiiType } from "../../../entity/pii/model/types";
import { PiiOccurrenceItem } from "../../../entity/pii/ui/pii-occurrence-item";
import { GroupTypeMenu, OccurrenceTypeMenu } from "./pii-type-menu";

type PiiGroupItemProps = {
  groupId: string;
  /** Все вхождения одной сущности — общий маркер и тип, разные абзацы. */
  occurrences: FlatPiiOccurrence[];
  decision: PiiDecisionKind;
  selectedOccurrenceId: string | null;
  notFoundIds: Set<string>;
  onSelect: (occurrenceId: string) => void;
  onConfirm: (groupId: string) => void;
  onReject: (groupId: string) => void;
  onSetGroupType: (groupId: string, type: PiiType) => void;
  onSetOccurrenceType: (occurrenceId: string, type: PiiType) => void;
};

/**
 * Группа — сущность, встречающаяся в документе один или несколько раз.
 * Решение по группе (`decision`) всегда одно на все вхождения — без правки
 * границ отвязать конкретное вхождение по kind больше нечем, поэтому строка
 * группы никогда не бывает «частично» (это упростилось после того, как
 * «Править границы» убрали из итерации).
 *
 * Раскрытие/сворачивание — свой `isOpen`, а не Collapsible: кнопки
 * подтверждения и меню типа должны жить в той же строке, что и заголовок, а
 * Collapsible оборачивает trigger в свой `<button>` — вложенный `<button>`
 * внутри него невалиден и ломает клики. Та же развязка «строка кликабельна,
 * действия внутри стопают propagation», что уже есть в
 * прежней строке списка масок.
 */
export function PiiGroupItem({
  groupId,
  occurrences,
  decision,
  selectedOccurrenceId,
  notFoundIds,
  onSelect,
  onConfirm,
  onReject,
  onSetGroupType,
  onSetOccurrenceType,
}: PiiGroupItemProps) {
  const containsSelected = occurrences.some((o) => o.id === selectedOccurrenceId);
  const [isOpen, setIsOpen] = useState(containsSelected);
  const first = occurrences[0];

  // Клик по метке в документе выбирает вхождение в сторе — группа, где оно
  // лежит, должна раскрыться сама, даже если оператор её не трогал. Группу,
  // из которой выбор ушёл, не сворачиваем — так удобнее сравнивать соседние
  // решения глазами.
  useEffect(() => {
    if (containsSelected) setIsOpen(true);
  }, [containsSelected]);

  return (
    <VStack gap={0} as="li">
      <Item
        density="spacious"
        align="center"
        isSelected={false}
        onClick={() => setIsOpen((v) => !v)}
        startContent={
          <Icon icon={isOpen ? ChevronDown : ChevronRight} size="sm" color="secondary" />
        }
        label={
          <HStack gap={2} vAlign="center" wrap="wrap">
            <Text weight="medium">{first.marker}</Text>
            <Text type="supporting" color="secondary">
              {piiTypeLabel(first.type)}
            </Text>
            {occurrences.length > 1 ? (
              <Text type="supporting" color="secondary">
                × {occurrences.length}
              </Text>
            ) : null}
          </HStack>
        }
        endContent={
          <HStack gap={1} vAlign="center">
            <GroupTypeMenu
              currentType={first.type}
              onSelect={(type) => onSetGroupType(groupId, type)}
            />
            <IconButton
              size="sm"
              variant={decision === "confirmed" ? "ghost" : "primary"}
              icon={<Icon icon={Check} size="sm" />}
              label="Подтвердить группу"
              isDisabled={decision === "confirmed"}
              onClick={(e) => {
                e.stopPropagation();
                onConfirm(groupId);
              }}
            />
            <IconButton
              size="sm"
              variant="ghost"
              icon={<Icon icon={Undo2} size="sm" />}
              label="Вернуть группу"
              isDisabled={decision === "pending"}
              onClick={(e) => {
                e.stopPropagation();
                onReject(groupId);
              }}
            />
          </HStack>
        }
      />

      {isOpen ? (
        <VStack gap={0} as="ul" paddingInlineStart={6}>
          {occurrences.map((occurrence) => (
            <HStack key={occurrence.id} gap={0} vAlign="center">
              <StackItem size="fill">
                <PiiOccurrenceItem
                  occurrence={occurrence}
                  isSelected={occurrence.id === selectedOccurrenceId}
                  isUnanchored={notFoundIds.has(occurrence.id)}
                  onSelect={onSelect}
                />
              </StackItem>
              <OccurrenceTypeMenu
                currentType={occurrence.type}
                onSelectOnlyThis={(type) => onSetOccurrenceType(occurrence.id, type)}
              />
            </HStack>
          ))}
        </VStack>
      ) : null}
    </VStack>
  );
}
