import { useState } from "react";
import { Trash2 } from "lucide-react";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@astryxdesign/core/SegmentedControl";

import { flattenPiiOccurrences, groupOccurrences } from "../../../entity/pii/model/flatten";
import { piiTypeLabel } from "../../../entity/pii/model/pii-type-dict";
import { useLowConfidenceGroupCount } from "../../../entity/pii/model/selectors";
import { effectiveGroupDecision, useReviewStore } from "../../../entity/pii/model/review-store";
import type { PiiExtraction } from "../../../entity/pii/model/types";
import { PiiGroupItem } from "./pii-group-item";

type Filter = "all" | "excluded" | "low";

const LOW_CONFIDENCE = 0.6;

type PiiListTabProps = {
  extraction: PiiExtraction;
  notFoundIds: Set<string>;
  isEditingDisabled?: boolean;
};

/** Вкладка «Замены»: список групп ПДн с фильтром по состоянию проверки. */
export function PiiListTab({ extraction, notFoundIds, isEditingDisabled = false }: PiiListTabProps) {
  const [filter, setFilter] = useState<Filter>("all");

  const groupDecisions = useReviewStore((state) => state.groupDecisions);
  const appliedGroupDecisions = useReviewStore((state) => state.appliedGroupDecisions);
  const occurrenceDecisions = useReviewStore((state) => state.occurrenceDecisions);
  const appliedOccurrenceDecisions = useReviewStore((state) => state.appliedOccurrenceDecisions);
  const typeOverrides = useReviewStore((state) => state.typeOverrides);
  const occurrenceTypeOverrides = useReviewStore((state) => state.occurrenceTypeOverrides);
  const selectedOccurrenceId = useReviewStore((state) => state.selectedOccurrenceId);
  const select = useReviewStore((state) => state.select);
  const confirmGroup = useReviewStore((state) => state.confirmGroup);
  const rejectGroup = useReviewStore((state) => state.rejectGroup);
  const confirmOccurrence = useReviewStore((state) => state.confirmOccurrence);
  const rejectOccurrence = useReviewStore((state) => state.rejectOccurrence);
  const setGroupType = useReviewStore((state) => state.setGroupType);
  const setOccurrenceType = useReviewStore((state) => state.setOccurrenceType);
  const manualOccurrences = useReviewStore((state) => state.manualOccurrences);
  const removeManual = useReviewStore((state) => state.removeManual);

  const lowCount = useLowConfidenceGroupCount();

  const groups = groupOccurrences(flattenPiiOccurrences(extraction));

  const visibleGroups = [...groups.entries()]
    .map(([groupId, occurrences]) => ({
      groupId,
      occurrences: occurrences.map((o) => ({
        ...o,
        type: occurrenceTypeOverrides[o.id] ?? typeOverrides[groupId] ?? o.type,
      })),
      decision: effectiveGroupDecision({
        groupDecisions,
        appliedGroupDecisions,
      }, groupId),
      minConfidence: Math.min(...occurrences.map((o) => o.confidence)),
    }))
    .filter((group) => {
      if (filter === "excluded") return group.decision === "rejected";
      if (filter === "low") return group.minConfidence < LOW_CONFIDENCE;
      return true;
    });

  return (
    <VStack gap={0} height="100%">
      <HStack gap={2} vAlign="center" padding={3} wrap="wrap">
        <SegmentedControl
          size="sm"
          label="Фильтр замен"
          value={filter}
          onChange={(value) => setFilter(value as Filter)}
        >
          <SegmentedControlItem value="all" label="Все" />
          <SegmentedControlItem value="excluded" label="Исключённые" />
          <SegmentedControlItem value="low" label={`Низкая ${lowCount}`} />
        </SegmentedControl>
      </HStack>

      {manualOccurrences.length > 0 ? (
        <Section padding={3} dividers={["top", "bottom"]}>
          <VStack gap={2}>
            <Text type="supporting" weight="medium">
              {`Отмечено вручную: ${manualOccurrences.length}`}
            </Text>
            {manualOccurrences.map((occurrence) => (
              <HStack key={occurrence.id} gap={2} vAlign="center" width="100%">
                <Token size="sm" color="orange" label={piiTypeLabel(occurrence.type)} />
                <Text textWrap="pretty">{occurrence.text}</Text>
                <StackItem size="fill" />
                <Text type="supporting" color="secondary" size="sm">
                  {occurrence.anchor?.label ??
                    (occurrence.region
                      ? `стр. ${occurrence.region.page + 1}, рамка на превью`
                      : "")}
                </Text>
                <IconButton
                  size="sm"
                  variant="ghost"
                  label={`Убрать «${occurrence.text}»`}
                  icon={<Icon icon={Trash2} size="sm" />}
                  isDisabled={isEditingDisabled}
                  onClick={() => removeManual(occurrence.id)}
                />
              </HStack>
            ))}
            <Text type="supporting" color="secondary" textWrap="pretty">
              В документе такие фрагменты пока не подсвечиваются: подсветка
              ищет уже вписанный маркер, а у ручной отметки его ещё нет.
            </Text>
          </VStack>
        </Section>
      ) : null}

      {visibleGroups.length === 0 ? (
        <EmptyState
          isCompact
          title="Все проверено"
          description="В этом фильтре не осталось групп, требующих решения."
        />
      ) : (
        <VStack gap={0} as="ul" isScrollable>
          {visibleGroups.map((group) => (
            <PiiGroupItem
              key={group.groupId}
              groupId={group.groupId}
              occurrences={group.occurrences}
              decision={group.decision}
              groupDecisions={groupDecisions}
              occurrenceDecisions={occurrenceDecisions}
              appliedGroupDecisions={appliedGroupDecisions}
              appliedOccurrenceDecisions={appliedOccurrenceDecisions}
              selectedOccurrenceId={selectedOccurrenceId}
              notFoundIds={notFoundIds}
              onSelect={select}
              onConfirm={confirmGroup}
              onReject={rejectGroup}
              onConfirmOccurrence={confirmOccurrence}
              onRejectOccurrence={rejectOccurrence}
              onSetGroupType={setGroupType}
              onSetOccurrenceType={setOccurrenceType}
              isEditingDisabled={isEditingDisabled}
            />
          ))}
        </VStack>
      )}
    </VStack>
  );
}
