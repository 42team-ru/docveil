import { Token } from "@astryxdesign/core/Token";

import type { MaskStatus } from "../model/types";

const STATUS_LABEL: Record<MaskStatus, string> = {
  ok: "подтверждено",
  pending: "ожидает",
  low: "низкая уверенность",
};

const STATUS_COLOR: Record<MaskStatus, "green" | "gray" | "red"> = {
  ok: "green",
  pending: "gray",
  low: "red",
};

/** Чип состояния проверки замены. */
export function MaskStatusToken({ status }: { status: MaskStatus }) {
  return (
    <Token size="sm" color={STATUS_COLOR[status]} label={STATUS_LABEL[status]} />
  );
}
