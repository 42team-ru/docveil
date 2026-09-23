import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { LLMProfileOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";

const profileActions = vi.hoisted(() => ({
  activate: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("../api/admin", () => ({
  useActivateLlmProfile: () => ({ isPending: false, mutate: profileActions.activate }),
  useDeleteLlmProfile: () => ({ isPending: false, mutate: profileActions.remove }),
}));

const { AdminLlmProfilesTable } = await import("./admin-llm-profiles-table");
const host = document.createElement("main");
document.body.append(host);
let root: Root;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeEach(() => {
  root = createRoot(host);
  profileActions.activate.mockClear();
  profileActions.remove.mockClear();
});

afterEach(async () => {
  await act(async () => root.unmount());
});

function makeProfile(overrides: Partial<LLMProfileOut> = {}): LLMProfileOut {
  return {
    id: "profile-1",
    source: "custom",
    name: "Профиль модели",
    provider: "gigachat",
    model: "GigaChat",
    api_key_env: "GIGACHAT_API_KEY",
    has_api_key: true,
    provider_config: {},
    pricing: { prompt_per_1k: 0.25, completion_per_1k: 0.5, currency: "RUB" },
    is_active: false,
    created_at: "2026-09-23T10:00:00Z",
    ...overrides,
  };
}

it("показывает встроенный активный профиль карточкой без кнопки активации", async () => {
  const builtin = makeProfile({
    id: null,
    source: "builtin",
    name: "Встроенный профиль",
    is_active: true,
    has_api_key: false,
  });

  await act(async () => root.render(<AdminLlmProfilesTable profiles={[builtin]} onEdit={() => undefined} />));

  expect(host.querySelector("table")).toBeNull();
  expect(host.textContent).toContain("Встроенный профиль");
  expect(host.textContent).toContain("Активен");
  expect(host.textContent).toContain("Тариф");
  expect(host.textContent).toContain("Токен");
  expect([...host.querySelectorAll("button")].some((button) => button.textContent?.includes("Активировать"))).toBe(false);
  expect(host.querySelector('[aria-label="Удалить профиль «Встроенный профиль»"]')).toBeNull();
});

it("переносит длинные значения и сохраняет активацию, изменение и удаление", async () => {
  const custom = makeProfile({
    name: "Профиль для длинного имени, которое должно переноситься в карточке",
    model: "long-model-name-with-provider-specific-configuration-and-version",
    is_active: false,
    pricing: { prompt_per_1k: 123456.75, completion_per_1k: 987654.25, currency: "RUB" },
  });
  const onEdit = vi.fn();

  await act(async () => root.render(<AdminLlmProfilesTable profiles={[custom]} onEdit={onEdit} />));

  expect(host.textContent).toContain(custom.name);
  expect(host.textContent).toContain(custom.model);
  expect(host.querySelector("table")).toBeNull();

  const buttons = [...host.querySelectorAll("button")];
  const activateButton = buttons.find((button) => button.textContent?.includes("Активировать"));
  const editButton = buttons.find((button) => button.textContent?.includes("Изменить"));
  expect(activateButton).toBeDefined();
  expect(editButton).toBeDefined();
  expect(host.querySelector('[aria-label^="Удалить профиль"]')).not.toBeNull();

  await act(async () => activateButton?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  await act(async () => editButton?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  expect(profileActions.activate).toHaveBeenCalledWith({ source: "custom", name: custom.name });
  expect(onEdit).toHaveBeenCalledWith(custom);
});

it("не позволяет удалить собственный активный профиль", async () => {
  const activeCustom = makeProfile({ is_active: true });

  await act(async () => root.render(<AdminLlmProfilesTable profiles={[activeCustom]} onEdit={() => undefined} />));

  const deleteButton = host.querySelector<HTMLButtonElement>(
    `[aria-label="Удалить профиль «${activeCustom.name}»"]`,
  );
  expect(deleteButton).not.toBeNull();
  expect(deleteButton?.disabled || deleteButton?.getAttribute("aria-disabled") === "true").toBe(true);
  expect([...host.querySelectorAll("button")].some((button) => button.textContent?.includes("Активировать"))).toBe(false);
});
