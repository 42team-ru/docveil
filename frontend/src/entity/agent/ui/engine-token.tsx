import { Token } from "@astryxdesign/core/Token";

import type { AgentConfigRow } from "../model/types";

const ENGINE_COLOR: Record<
  AgentConfigRow["engine"],
  "blue" | "yellow" | "gray" | "teal"
> = {
  модель: "blue",
  гибрид: "yellow",
  правила: "gray",
  tesseract: "teal",
};

/** Чем работает агент: правилами, моделью, OCR или их смесью. */
export function EngineToken({ engine }: { engine: AgentConfigRow["engine"] }) {
  return <Token size="sm" color={ENGINE_COLOR[engine]} label={engine} />;
}
