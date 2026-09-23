import { describe, expect, it } from "vitest";

import { hasReadyArtifactForDownload, selectedTypesForRun } from "./masking-run";

describe("hasReadyArtifactForDownload", () => {
  it("allows downloading an existing artifact from a leaked run", () => {
    expect(hasReadyArtifactForDownload("leaked", "blob:masked-highlight"))
      .toBe(true);
  });

  it("requires both a rendered result and a file URL", () => {
    expect(hasReadyArtifactForDownload("running", "blob:masked-highlight"))
      .toBe(false);
    expect(hasReadyArtifactForDownload("leaked", ""))
      .toBe(false);
  });
});

describe("selectedTypesForRun", () => {
  it("keeps an empty built-in selection empty unless a custom type is selected", () => {
    expect(selectedTypesForRun([], [])).toEqual([]);
    expect(selectedTypesForRun([], [{
      outcome: "compile",
      spec: {
        schema_version: 1,
        id: "demo_project_code",
        title: "Демо-код проекта",
        marker: "[ДЕМО-КОД-{n}]",
        critical: false,
        detect: { kind: "regex", pattern: "DEMO-PROJ-[0-9]{4}" },
      },
    }])).toEqual(["demo_project_code"]);
  });

  it("keeps the all-types sentinel and includes use_builtin custom selections", () => {
    expect(selectedTypesForRun(null, [{ outcome: "use_builtin", type_id: "inn" }]))
      .toBeNull();
    expect(selectedTypesForRun([], [{ outcome: "use_builtin", type_id: "inn" }]))
      .toEqual(["inn"]);
  });
});
