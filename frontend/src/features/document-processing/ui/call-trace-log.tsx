import { CodeBlock } from "@astryxdesign/core/CodeBlock";

import { callTrace } from "../../../entity/agent/model/fixtures";

/** Трасса вызовов: что именно уходило в модель и что она вернула. */
export function CallTraceLog() {
  return (
    <CodeBlock
      code={callTrace}
      language="plaintext"
      title="трасса вызовов · llm-слой: local"
      size="sm"
      width="100%"
      maxHeight={340}
    />
  );
}
