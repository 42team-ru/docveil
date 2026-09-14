import { describe, expect, it } from "vitest";

import type { UserPublic } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { isAdmin } from "./roles";

function userWith(roles: UserPublic["roles"]): UserPublic {
  return {
    id: "00000000-0000-0000-0000-000000000000",
    email: "user@example.com",
    full_name: "Пользователь",
    roles,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("isAdmin", () => {
  it("false для пустого списка ролей", () => {
    expect(isAdmin(userWith([]))).toBe(false);
  });

  it("false для обычного пользователя", () => {
    expect(isAdmin(userWith(["user"]))).toBe(false);
  });

  it("true, когда среди ролей есть admin", () => {
    expect(isAdmin(userWith(["user", "admin"]))).toBe(true);
  });

  it("false для undefined/null — сессия ещё не загружена", () => {
    expect(isAdmin(undefined)).toBe(false);
    expect(isAdmin(null)).toBe(false);
  });
});
