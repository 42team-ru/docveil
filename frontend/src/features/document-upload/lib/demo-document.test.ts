import { describe, expect, it } from "vitest";

import { DEMO_DOCUMENT_NAME, loadDemoDocument } from "./demo-document";

describe("loadDemoDocument", () => {
  it("returns the public example as a consistently named DOCX file", async () => {
    const document = await loadDemoDocument(async () => new Response("example", { status: 200 }));

    expect(document.name).toBe(DEMO_DOCUMENT_NAME);
    expect(document.type).toBe(
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    );
    expect(document.lastModified).toBe(0);
  });

  it("explains when the example cannot be loaded", async () => {
    await expect(loadDemoDocument(async () => new Response(null, { status: 404 }))).rejects.toThrow(
      "Не удалось загрузить учебный договор",
    );
  });
});
