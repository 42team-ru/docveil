import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";

import { piiTypeOptions } from "../../../entity/pii/model/pii-type-dict";
import type { PiiType } from "../../../entity/pii/model/types";

function buildItems(currentType: PiiType, onSelect: (type: PiiType) => void) {
  return piiTypeOptions().map((option) => ({
    label: option.label,
    onClick: () => onSelect(option.value),
    variant: option.value === currentType ? ("default" as const) : undefined,
  }));
}

type GroupTypeMenuProps = {
  currentType: PiiType;
  onSelect: (type: PiiType) => void;
  isDisabled?: boolean;
};

/** Смена типа на всю группу — триггер в шапке `pii-group-item.tsx`. */
export function GroupTypeMenu({ currentType, onSelect, isDisabled = false }: GroupTypeMenuProps) {
  return (
    <DropdownMenu
      button={{ label: "Сменить тип", size: "sm", variant: "ghost", isDisabled }}
      items={buildItems(currentType, onSelect)}
    />
  );
}

type OccurrenceTypeMenuProps = {
  currentType: PiiType;
  onSelectOnlyThis: (type: PiiType) => void;
  isDisabled?: boolean;
};

/**
 * Смена типа для одного вхождения — «применить только к этому вхождению» из
 * решения по группам. Отдельный оверфлоу-триггер на строке вхождения, не
 * общий пункт с групповой сменой: так область действия видна по тому, где
 * оператор кликнул, а не по скрытому переключателю внутри одного меню.
 */
export function OccurrenceTypeMenu({
  currentType,
  onSelectOnlyThis,
  isDisabled = false,
}: OccurrenceTypeMenuProps) {
  return (
    <MoreMenu
      label="Тип только для этого вхождения"
      size="sm"
      isDisabled={isDisabled}
      items={[
        { type: "section", title: "Только это вхождение", items: buildItems(currentType, onSelectOnlyThis) },
      ]}
    />
  );
}
