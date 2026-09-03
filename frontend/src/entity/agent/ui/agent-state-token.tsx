import { Token } from "@astryxdesign/core/Token";

import type { AgentState } from "../model/types";

const STATE_LABEL: Record<AgentState, string> = {
  done: "готово",
  run: "выполняется",
  wait: "в очереди",
};

const STATE_COLOR: Record<AgentState, "green" | "blue" | "gray"> = {
  done: "green",
  run: "blue",
  wait: "gray",
};

/** Чип состояния шага конвейера или агента. */
export function AgentStateToken({ state }: { state: AgentState }) {
  return <Token size="sm" color={STATE_COLOR[state]} label={STATE_LABEL[state]} />;
}
