import { describe, expect, it } from "vitest";

import type { RunListItem } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { recentRuns } from "./recent-runs";

const runs = Array.from({ length: 6 }, (_, index) => ({
  id: `run-${index + 1}`,
  status: "done",
  document: {
    name: `document-${index + 1}.pdf`,
    format: "pdf",
    object_name: `document-${index + 1}.pdf`,
  },
  created_at: "2026-09-10T10:00:00Z",
})) satisfies RunListItem[];

describe("recentRuns", () => {
  it("keeps the API order and limits the list to five documents", () => {
    expect(recentRuns(runs).map((run) => run.id)).toEqual([
      "run-1",
      "run-2",
      "run-3",
      "run-4",
      "run-5",
    ]);
  });
});
