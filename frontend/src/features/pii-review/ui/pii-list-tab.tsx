import { useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@astryxdesign/core/SegmentedControl";

import {
  flattenPiiOccurrences,
  groupOccurrences,
  manualFallbackId,
  type FlatPiiOccurrence,
} from "../../../entity/pii/model/flatten";
import {
  PII_CATEGORY_ORDER,
  piiTypeCategory,
  piiTypeLabel,
} from "../../../entity/pii/model/pii-type-dict";
import { useLowConfidenceGroupCount } from "../../../entity/pii/model/selectors";
import { effectiveGroupDecision, useReviewStore } from "../../../entity/pii/model/review-store";
import type { PiiExtraction, PiiType } from "../../../entity/pii/model/types";
import { PiiGroupItem } from "./pii-group-item";

type Filter = "all" | "excluded" | "low" | "notFound";

const LOW_CONFIDENCE = 0.6;

type PiiListTabProps = {
  extraction: PiiExtraction;
  notFoundIds: Set<string>;
  isEditingDisabled?: boolean;
  isReadOnly?: boolean;
};

/** Вкладка «Замены»: список групп ПДн с фильтром по состоянию проверки. */
export function PiiListTab({ extraction, notFoundIds, isEditingDisabled = false, isReadOnly = false }: PiiListTabProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const isEditingDisabledRef = useRef(isEditingDisabled);
  isEditingDisabledRef.current = isEditingDisabled;

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
  const addManual = useReviewStore((state) => state.addManual);

  const lowCount = useLowConfidenceGroupCount();
  const manualOccurrenceIds = new Set(manualOccurrences.map((o) => o.id));

  // Непривязанное вхождение уже существует на бэке (тип и текст известны) —
  // в отличие от настоящей ручной пометки, тип у него выбирать не нужно.
  //
  // `ManualEntityIn` бэкенда не принимает locator вообще — только
  // `type`/`text`/опциональный `region` (`shared/api/generated/.../
  // triemaMaskerAPI.schemas.ts`). Для bbox-форматов (pdf/скан) у вхождения
  // уже есть точные координаты — их и шлём, тогда сервер не ищет текст на
  // странице (`ManualPiiOccurrence`, комментарий в entity/pii/model/types.ts).
  // Для docx/xlsx `regions` пуст и точной привязки в принципе нет: сервер
  // ищет `text` вслепую, и найдёт ли он именно то вхождение — вне контроля
  // фронта.
  function handleAddFallbackManual(occurrence: FlatPiiOccurrence) {
    if (isEditingDisabledRef.current) return;
    const region = occurrence.regions[0];
    addManual({
      id: manualFallbackId(occurrence.id),
      type: occurrence.type,
      text: occurrence.originalText,
      ...(region ? { region } : { anchor: occurrence.anchor }),
    });
  }

  function handleConfirmGroup(groupId: string) {
    if (!isEditingDisabledRef.current) confirmGroup(groupId);
  }

  function handleRejectGroup(groupId: string) {
    if (!isEditingDisabledRef.current) rejectGroup(groupId);
  }

  function handleConfirmOccurrence(occurrenceId: string, groupId: string) {
    if (!isEditingDisabledRef.current) confirmOccurrence(occurrenceId, groupId);
  }

  function handleRejectOccurrence(occurrenceId: string, groupId: string) {
    if (!isEditingDisabledRef.current) rejectOccurrence(occurrenceId, groupId);
  }

  function handleSetGroupType(groupId: string, type: PiiType) {
    if (!isEditingDisabledRef.current) setGroupType(groupId, type);
  }

  function handleSetOccurrenceType(occurrenceId: string, type: PiiType) {
    if (!isEditingDisabledRef.current) setOccurrenceType(occurrenceId, type);
  }

  function handleRemoveManual(occurrenceId: string) {
    if (!isEditingDisabledRef.current) removeManual(occurrenceId);
  }

  const groups = groupOccurrences(flattenPiiOccurrences(extraction));

  const allGroups = [...groups.entries()]
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
      hasNotFound: occurrences.some((o) => notFoundIds.has(o.id)),
    }));

  const notFoundCount = allGroups.filter((group) => group.hasNotFound).length;

  // Пункт фильтра существует, только пока есть что показывать — если
  // непривязанные вхождения исчезли (перегенерация починила якоря), а
  // фильтр остался на них, в SegmentedControl не на что указывать значением.
  useEffect(() => {
    if (filter === "notFound" && notFoundCount === 0) setFilter("all");
  }, [filter, notFoundCount]);

  const visibleGroups = allGroups.filter((group) => {
    if (filter === "excluded") return group.decision === "rejected";
    if (filter === "low") return group.minConfidence < LOW_CONFIDENCE;
    if (filter === "notFound") return group.hasNotFound;
    return true;
  });
  const groupsByCategory = PII_CATEGORY_ORDER.map((category) => ({
    category,
    groups: visibleGroups.filter(
      (group) => piiTypeCategory(group.occurrences[0].type) === category,
    ),
  })).filter(({ groups }) => groups.length > 0);

  return (
    <VStack gap={0} height="100%">
      <HStack gap={3} vAlign="center" padding={4} wrap="wrap">
        <SegmentedControl
          size="sm"
          label="Фильтр замен"
          value={filter}
          onChange={(value) => setFilter(value as Filter)}
        >
          <SegmentedControlItem value="all" label="Все" />
          <SegmentedControlItem value="excluded" label="Исключённые" />
          <SegmentedControlItem value="low" label={`Низкая ${lowCount}`} />
          {notFoundCount > 0 ? (
            <SegmentedControlItem value="notFound" label={`Замазано без подсветки ${notFoundCount}`} />
          ) : null}
        </SegmentedControl>
      </HStack>

      {manualOccurrences.length > 0 ? (
        <Section padding={4} dividers={["top", "bottom"]}>
          <VStack gap={2}>
            <Text type="supporting" weight="medium">
              {`Отмечено вручную: ${manualOccurrences.length}`}
            </Text>
            {manualOccurrences.map((occurrence) => (
              <HStack key={occurrence.id} gap={2} vAlign="center" width="100%" wrap="wrap">
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
                  onClick={() => handleRemoveManual(occurrence.id)}
                />
              </HStack>
            ))}
            <Text type="supporting" color="secondary" textWrap="pretty">
              В документе такие фрагменты подсвечены жёлтым, как черновик —
              маска встанет в файл после перегенерации.
            </Text>
          </VStack>
        </Section>
      ) : null}

      {allGroups.length === 0 && manualOccurrences.length === 0 ? (
        <EmptyState
          isCompact
          title="Сущностей для маскирования не найдено"
          description="Документ можно просмотреть и завершить проверку без решений по заменам."
        />
      ) : visibleGroups.length === 0 ? (
        <EmptyState
          isCompact
          title="Все проверено"
          description="В этом фильтре не осталось групп, требующих решения."
        />
      ) : (
        <VStack gap={2} isScrollable>
          {groupsByCategory.map(({ category, groups }) => (
            <VStack key={category} gap={0} as="section">
              <HStack gap={3} vAlign="center" padding={4}>
                <Heading level={5}>{category}</Heading>
                <Token size="sm" color="gray" label={`Найдено: ${groups.length}`} />
              </HStack>
              <VStack gap={0} as="ul">
                {groups.map((group) => (
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
                    manualOccurrenceIds={manualOccurrenceIds}
                    onSelect={select}
                    onConfirm={handleConfirmGroup}
                    onReject={handleRejectGroup}
                    onConfirmOccurrence={handleConfirmOccurrence}
                    onRejectOccurrence={handleRejectOccurrence}
                    onSetGroupType={handleSetGroupType}
                    onSetOccurrenceType={handleSetOccurrenceType}
                    onAddFallbackManual={handleAddFallbackManual}
                    isEditingDisabled={isEditingDisabled}
                    isReadOnly={isReadOnly}
                  />
                ))}
              </VStack>
            </VStack>
          ))}
        </VStack>
      )}
    </VStack>
  );
}
