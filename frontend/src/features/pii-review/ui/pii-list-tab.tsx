import { useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@astryxdesign/core/SegmentedControl";

import { flattenPiiOccurrences, groupOccurrences } from "../../../entity/pii/model/flatten";
import {
  useLowConfidenceGroupCount,
  usePendingGroupCount,
} from "../../../entity/pii/model/selectors";
import { useReviewStore } from "../../../entity/pii/model/review-store";
import type { PiiExtraction } from "../../../entity/pii/model/types";
import { PiiGroupItem } from "./pii-group-item";

type Filter = "all" | "pending" | "low";

const LOW_CONFIDENCE = 0.6;

type PiiListTabProps = {
  extraction: PiiExtraction;
  notFoundIds: Set<string>;
};

/** Вкладка «Замены»: список групп ПДн с фильтром по состоянию проверки. */
export function PiiListTab({ extraction, notFoundIds }: PiiListTabProps) {
  const [filter, setFilter] = useState<Filter>("pending");

  const groupDecisions = useReviewStore((state) => state.groupDecisions);
  const typeOverrides = useReviewStore((state) => state.typeOverrides);
  const occurrenceTypeOverrides = useReviewStore((state) => state.occurrenceTypeOverrides);
  const selectedOccurrenceId = useReviewStore((state) => state.selectedOccurrenceId);
  const select = useReviewStore((state) => state.select);
  const confirmGroup = useReviewStore((state) => state.confirmGroup);
  const rejectGroup = useReviewStore((state) => state.rejectGroup);
  const setGroupType = useReviewStore((state) => state.setGroupType);
  const setOccurrenceType = useReviewStore((state) => state.setOccurrenceType);
  const confirmAllGroups = useReviewStore((state) => state.confirmAllGroups);

  const pendingCount = usePendingGroupCount();
  const lowCount = useLowConfidenceGroupCount();

  const groups = groupOccurrences(flattenPiiOccurrences(extraction));

  const visibleGroups = [...groups.entries()]
    .map(([groupId, occurrences]) => ({
      groupId,
      occurrences: occurrences.map((o) => ({
        ...o,
        type: occurrenceTypeOverrides[o.id] ?? typeOverrides[groupId] ?? o.type,
      })),
      decision: groupDecisions[groupId] ?? "pending",
      minConfidence: Math.min(...occurrences.map((o) => o.confidence)),
    }))
    .filter((group) => {
      if (filter === "pending") return group.decision !== "confirmed";
      if (filter === "low") return group.minConfidence < LOW_CONFIDENCE;
      return true;
    });

  return (
    <VStack gap={0} height="100%">
      <HStack gap={2} vAlign="center" padding={3} hAlign="between" wrap="wrap">
        <SegmentedControl
          size="sm"
          label="Фильтр замен"
          value={filter}
          onChange={(value) => setFilter(value as Filter)}
        >
          <SegmentedControlItem value="all" label="Все" />
          <SegmentedControlItem value="pending" label={`Ожидают ${pendingCount}`} />
          <SegmentedControlItem value="low" label={`Низкая ${lowCount}`} />
        </SegmentedControl>
        <Button
          size="sm"
          variant="ghost"
          label="Подтвердить все"
          isDisabled={pendingCount === 0}
          onClick={() => confirmAllGroups([...groups.keys()])}
        />
      </HStack>

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
              selectedOccurrenceId={selectedOccurrenceId}
              notFoundIds={notFoundIds}
              onSelect={select}
              onConfirm={confirmGroup}
              onReject={rejectGroup}
              onSetGroupType={setGroupType}
              onSetOccurrenceType={setOccurrenceType}
            />
          ))}
        </VStack>
      )}
    </VStack>
  );
}
