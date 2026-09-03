import { HStack } from "@astryxdesign/core/Stack";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Token } from "@astryxdesign/core/Token";

import type { DocumentStatus } from "../model/types";

const STATUS_LABEL: Record<DocumentStatus, string> = {
  ok: "утверждён",
  review: "на проверке",
  ocr: "OCR · проверить",
  run: "обрабатывается",
};

const STATUS_COLOR: Record<DocumentStatus, "green" | "yellow" | "red" | "blue"> =
  {
    ok: "green",
    review: "yellow",
    ocr: "red",
    run: "blue",
  };

/** Состояние документа. У «обрабатывается» рядом пульсирует точка. */
export function DocumentStatusToken({ status }: { status: DocumentStatus }) {
  return (
    <HStack gap={1.5} vAlign="center">
      {status === "run" ? (
        <StatusDot variant="accent" label="идёт обработка" isPulsing />
      ) : null}
      <Token size="sm" color={STATUS_COLOR[status]} label={STATUS_LABEL[status]} />
    </HStack>
  );
}
