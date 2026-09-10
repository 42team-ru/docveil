import { describe, expect, it } from "vitest";

import { resolvePaintState } from "./apply-highlights";

describe("resolvePaintState", () => {
  it("не закрашивает исходный текст в режиме «Оригинал»", () => {
    expect(resolvePaintState("pending", "original")).toBe("original");
    expect(resolvePaintState("confirmed", "original")).toBe("original");
  });
});
