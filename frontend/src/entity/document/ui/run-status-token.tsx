import { HStack } from "@astryxdesign/core/Stack";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Token } from "@astryxdesign/core/Token";

import type { RunStatus } from "../../../features/masking-run/api/masking-run";

export const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "в очереди",
  running: "обрабатывается",
  awaiting_answers: "ждёт ответов",
  awaiting_review: "на проверке",
  done: "готов",
  leaked: "утечка",
  failed: "ошибка",
};

const STATUS_COLOR: Record<RunStatus, "green" | "yellow" | "red" | "gray" | "blue"> = {
  queued: "gray",
  running: "blue",
  awaiting_answers: "yellow",
  awaiting_review: "yellow",
  done: "green",
  // Утечка — это не «ошибка сервера», а найденный валидатором дефект
  // результата: она обязана быть видна в журнале так же ясно, как отказ.
  leaked: "red",
  failed: "red",
};

/** Состояние прогона. У идущего рядом пульсирует точка. */
export function RunStatusToken({ status }: { status: RunStatus }) {
  const inProgress = status === "queued" || status === "running";

  return (
    <HStack gap={1.5} vAlign="center">
      {inProgress ? (
        <StatusDot variant="accent" label="идёт обработка" isPulsing />
      ) : null}
      <Token size="sm" color={STATUS_COLOR[status]} label={STATUS_LABEL[status]} />
    </HStack>
  );
}
