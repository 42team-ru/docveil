import { Token } from "@astryxdesign/core/Token";

import type { MaskStatus } from "../model/types";

const STATUS_COLOR: Record<MaskStatus, "green" | "yellow" | "red"> = {
  ok: "green",
  pending: "yellow",
  low: "red",
};

type MaskTokenProps = {
  marker: string;
  status: MaskStatus;
  isSelected: boolean;
  onSelect: () => void;
};

/**
 * Маркер прямо в тексте документа. Выделенный фрагмент окрашивается в синий —
 * так видно, какая замена сейчас открыта в правой панели; остальные держат цвет
 * своего статуса.
 */
export function MaskToken({
  marker,
  status,
  isSelected,
  onSelect,
}: MaskTokenProps) {
  return (
    <Token
      size="sm"
      color={isSelected ? "blue" : STATUS_COLOR[status]}
      label={marker}
      description={isSelected ? "выбранная замена" : undefined}
      onClick={onSelect}
    />
  );
}
