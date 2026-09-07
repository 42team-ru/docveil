import { useEffect, useRef, type CSSProperties } from "react";
import { Item } from "@astryxdesign/core/Item";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

import type { FlatPiiOccurrence } from "../model/flatten";
import { piiTypeLabel } from "../model/pii-type-dict";

/** Порог уверенности, ниже которого метка подсвечивается отдельно — как в
 * прежней метке уверенности. */
const LOW_CONFIDENCE = 0.6;

function ConfidenceMark({ value }: { value: number }) {
  const formatted = value.toFixed(2);
  if (value < LOW_CONFIDENCE) {
    return <Token size="sm" color="red" label={formatted} />;
  }
  return (
    <Text type="supporting" hasTabularNumbers>
      {formatted}
    </Text>
  );
}

type PiiOccurrenceItemProps = {
  occurrence: FlatPiiOccurrence;
  isSelected: boolean;
  isUnanchored: boolean;
  onSelect: (id: string) => void;
};

/**
 * Строка одного вхождения внутри развёрнутой группы. Активная строка (выбор
 * пришёл либо кликом здесь, либо кликом по метке в документе) получает
 * вертикальную черту слева — тот же приём, что уже был в
 * прежней строке списка масок (`borderLeft` на обёртке, а не через
 * `Item.isSelected`, чтобы получить именно вертикальную черту, а не встроенную
 * заливку). Цвет — `--color-border-blue`, а не буквально белый: белая черта
 * не видна на светлой панели в светлой теме.
 */
export function PiiOccurrenceItem({
  occurrence,
  isSelected,
  isUnanchored,
  onSelect,
}: PiiOccurrenceItemProps) {
  const rowRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (isSelected) {
      rowRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [isSelected]);

  const rowStyle: CSSProperties = {
    borderInlineStart: isSelected
      ? "3px solid var(--color-border-blue)"
      : "3px solid transparent",
    backgroundColor: isSelected ? "var(--color-background-muted)" : "transparent",
    transition: "background-color 0.15s ease-out, border-color 0.15s ease-out",
  };

  return (
    <VStack gap={0} as="li" ref={rowRef} style={rowStyle}>
      <Item
        density="compact"
        align="start"
        isSelected={false}
        onClick={() => onSelect(occurrence.id)}
        label={
          <HStack gap={2} vAlign="center">
            <Text type="supporting">{occurrence.anchor.label}</Text>
            <ConfidenceMark value={occurrence.confidence} />
            <StackItem size="fill" />
            {isUnanchored ? <Token size="sm" color="red" label="не найдено" /> : null}
          </HStack>
        }
        description={
          <Text color="secondary" maxLines={1}>
            {piiTypeLabel(occurrence.type)} · {occurrence.originalText}
          </Text>
        }
      />
    </VStack>
  );
}
