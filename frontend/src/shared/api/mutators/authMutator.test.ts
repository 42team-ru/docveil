import { describe, expect, it } from "vitest";

import { baseURL, clientApiWithAuth } from "./authMutator";

describe("authMutator API origin", () => {
  it("uses the same-origin Vite proxy in development", () => {
    expect(baseURL).toBe("/api");
    expect(clientApiWithAuth.defaults.baseURL).toBe("/api");
  });
});
