import { describe, expect, it } from "vitest";

import type { RunListItem } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { toReviewableRunSearchItems } from "./run-search";

const run = (id: string, status: RunListItem["status"]): RunListItem => ({
  id,
  status,
  document: { name: `${id}.docx`, format: "docx", object_name: `documents/${id}.docx` },
  created_at: "2026-09-10T09:00:00Z",
});

describe("toReviewableRunSearchItems", () => {
  it("предлагает только прогоны с доступным для проверки документом", () => {
    expect(
      toReviewableRunSearchItems([
        run("queued", "queued"),
        run("review", "awaiting_review"),
        run("done", "done"),
        run("failed", "failed"),
      ]),
    ).toEqual([
      expect.objectContaining({ id: "review", label: "review.docx" }),
      expect.objectContaining({ id: "done", label: "done.docx" }),
    ]);
  });
});
