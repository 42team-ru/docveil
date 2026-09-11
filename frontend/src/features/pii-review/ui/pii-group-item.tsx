import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Plus, X } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Icon } from "@astryxdesign/core/Icon";
import { Item } from "@astryxdesign/core/Item";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { Tooltip } from "@astryxdesign/core/Tooltip";

import { manualFallbackId, type FlatPiiOccurrence } from "../../../entity/pii/model/flatten";
import { piiTypeLabel } from "../../../entity/pii/model/pii-type-dict";
import type { PiiDecisionKind, PiiType } from "../../../entity/pii/model/types";
import {
  effectiveOccurrenceDecision,
} from "../../../entity/pii/model/review-store";
import { PiiOccurrenceItem } from "../../../entity/pii/ui/pii-occurrence-item";
import { GroupTypeMenu, OccurrenceTypeMenu } from "./pii-type-menu";

type PiiGroupItemProps = {
  groupId: string;
  /** Все вхождения одной сущности — общий маркер и тип, разные абзацы. */
  occurrences: FlatPiiOccurrence[];
  decision: PiiDecisionKind;
  groupDecisions: Record<string, PiiDecisionKind>;
  occurrenceDecisions: Record<string, PiiDecisionKind>;
  appliedGroupDecisions: Record<string, Exclude<PiiDecisionKind, "pending">>;
  appliedOccurrenceDecisions: Record<string, Exclude<PiiDecisionKind, "pending">>;
  selectedOccurrenceId: string | null;
  notFoundIds: Set<string>;
  /** Id ручных записей — узнать, заведён ли уже фолбэк для вхождения. */
  manualOccurrenceIds: Set<string>;
  onSelect: (occurrenceId: string) => void;
  onConfirm: (groupId: string) => void;
  onReject: (groupId: string) => void;
  onConfirmOccurrence: (occurrenceId: string, groupId: string) => void;
  onRejectOccurrence: (occurrenceId: string, groupId: string) => void;
  onSetGroupType: (groupId: string, type: PiiType) => void;
  onSetOccurrenceType: (occurrenceId: string, type: PiiType) => void;
  /** Завести ручную запись по непривязанному вхождению — тип уже известен. */
  onAddFallbackManual: (occurrence: FlatPiiOccurrence) => void;
  isEditingDisabled?: boolean;
};

const CRITICAL_TYPES = new Set(["inn", "passport", "bank_account", "ogrn", "snils"]);

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
  groupDecisions,
  occurrenceDecisions,
  appliedGroupDecisions,
  appliedOccurrenceDecisions,
  selectedOccurrenceId,
  notFoundIds,
  manualOccurrenceIds,
  onSelect,
  onConfirm,
  onReject,
  onConfirmOccurrence,
  onRejectOccurrence,
  onSetGroupType,
  onSetOccurrenceType,
  onAddFallbackManual,
  isEditingDisabled = false,
}: PiiGroupItemProps) {
  const containsSelected = occurrences.some((o) => o.id === selectedOccurrenceId);
  const [isOpen, setIsOpen] = useState(containsSelected);
  const first = occurrences[0];
  const isExcluded = decision === "rejected";
  const notFoundCount = occurrences.filter((o) => notFoundIds.has(o.id)).length;

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
            <Text
              weight="medium"
              color={isExcluded ? "secondary" : undefined}
              hasStrikethrough={isExcluded}
            >
              {first.marker || first.originalText}
            </Text>
            <Text type="supporting" color="secondary">
              {piiTypeLabel(first.type)}
            </Text>
            {occurrences.length > 1 ? (
              <Text type="supporting" color="secondary">
                × {occurrences.length}
              </Text>
            ) : null}
            {isExcluded ? (
              <Tooltip
                content="Маскирование снято: сущность останется видимой в готовом документе."
                placement="above"
              >
                <Token size="sm" color="gray" label="Не замазано" />
              </Tooltip>
            ) : null}
            {notFoundCount > 0 ? (
              <Tooltip
                content={
                  notFoundCount === occurrences.length
                    ? "Уже замаскировано в документе — сам маркер найти и подсветить не удалось, но на файл это не влияет."
                    : `Замазано без подсветки: ${notFoundCount} из ${occurrences.length} вхождений.`
                }
                placement="above"
              >
                <Token size="sm" color="green" label="Замазано" />
              </Tooltip>
            ) : null}
          </HStack>
        }
        endContent={
          <HStack gap={1} vAlign="center">
            <GroupTypeMenu
              currentType={first.type}
              onSelect={(type) => onSetGroupType(groupId, type)}
            />
            {decision === "rejected" ? (
              <Button
                size="sm"
                variant="ghost"
                label="Вернуть"
                isDisabled={isEditingDisabled}
                onClick={(e) => {
                  e.stopPropagation();
                  onConfirm(groupId);
                }}
              />
            ) : (
              <IconButton
                size="sm"
                variant="ghost"
                icon={<Icon icon={X} size="sm" />}
                label="Убрать маскирование"
                tooltip={
                  CRITICAL_TYPES.has(first.type)
                    ? "Критичные реквизиты нельзя раскрыть без явного разрешения прогона"
                    : "Убрать маскирование"
                }
                isDisabled={isEditingDisabled || CRITICAL_TYPES.has(first.type)}
                onClick={(e) => {
                  e.stopPropagation();
                  onReject(groupId);
                }}
              />
            )}
          </HStack>
        }
      />

      {isOpen ? (
        <VStack gap={1} as="ul" paddingInlineStart={6}>
          {occurrences.map((occurrence) => {
            const isNotFound = notFoundIds.has(occurrence.id);
            return (
              <HStack key={occurrence.id} gap={0} vAlign="center" paddingInlineEnd={2}>
                <StackItem size="fill">
                  <PiiOccurrenceItem
                    occurrence={occurrence}
                    isSelected={occurrence.id === selectedOccurrenceId}
                    isUnanchored={isNotFound}
                    onSelect={onSelect}
                  />
                </StackItem>
                <OccurrenceTypeMenu
                  currentType={occurrence.type}
                  onSelectOnlyThis={(type) => onSetOccurrenceType(occurrence.id, type)}
                />
                {effectiveOccurrenceDecision(
                  {
                    groupDecisions,
                    appliedGroupDecisions,
                    occurrenceDecisions,
                    appliedOccurrenceDecisions,
                  },
                  occurrence.id,
                  groupId,
                ) === "rejected" ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    label="Вернуть"
                    isDisabled={isEditingDisabled}
                    onClick={() => onConfirmOccurrence(occurrence.id, groupId)}
                  />
                ) : isNotFound && !manualOccurrenceIds.has(manualFallbackId(occurrence.id)) ? (
                  <IconButton
                    size="sm"
                    variant="ghost"
                    icon={<Icon icon={Plus} size="sm" />}
                    label={`Добавить «${occurrence.originalText}»`}
                    tooltip="Добавить отдельной записью: тип и текст уже известны, подставим их сами"
                    isDisabled={isEditingDisabled}
                    onClick={() => onAddFallbackManual(occurrence)}
                  />
                ) : isNotFound ? null : (
                  <IconButton
                    size="sm"
                    variant="ghost"
                    icon={<Icon icon={X} size="sm" />}
                    label={`Убрать маскирование «${occurrence.originalText}»`}
                    tooltip={
                      CRITICAL_TYPES.has(occurrence.type)
                        ? "Критичные реквизиты нельзя раскрыть без явного разрешения прогона"
                        : "Убрать маскирование только в этом месте"
                    }
                    isDisabled={isEditingDisabled || CRITICAL_TYPES.has(occurrence.type)}
                    onClick={() => onRejectOccurrence(occurrence.id, groupId)}
                  />
                )}
              </HStack>
            );
          })}
        </VStack>
      ) : null}
    </VStack>
  );
}
