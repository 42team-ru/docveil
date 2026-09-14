import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it } from "vitest";

import type { AdminOverviewOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { AdminSummaryCards } from "./admin-summary-cards";

const host = document.createElement("main");
document.body.append(host);
let root = createRoot(host);
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
afterEach(async () => {
  await act(async () => root.unmount());
  root = createRoot(host);
});

function overviewWith(overrides: Partial<AdminOverviewOut["runs"]>): AdminOverviewOut {
  return {
    generated_at: "2026-01-01T00:00:00Z",
    window_days: 30,
    users: {
      total: 4,
      active: 3,
      inactive: 1,
      admins: 1,
      never_logged_in: 1,
      active_last_7d: 2,
      active_last_30d: 3,
      with_avatar: 0,
      signups_by_day: [],
    },
    runs: {
      total: 0,
      by_status: {},
      by_format: {},
      by_day: [],
      succeeded: 0,
      failed: 0,
      leaked: 0,
      in_progress: 0,
      success_rate: null,
      avg_duration_seconds: null,
      median_duration_seconds: null,
      ...overrides,
    },
    options: {
      by_mask_style: {},
      profile_enabled: 0,
      rules_only: 0,
      unmask_critical: 0,
      review: 0,
      with_custom_types: 0,
    },
    failures: [],
    sessions: { active: 0, by_device: {}, revoked: 0, expired: 0 },
    top_users: [],
  };
}

it("рендерит ключевые факты по данным сводки", async () => {
  const overview = overviewWith({
    total: 10,
    succeeded: 8,
    failed: 1,
    leaked: 1,
    success_rate: 0.8,
    avg_duration_seconds: 65,
  });

  await act(async () => root.render(<AdminSummaryCards overview={overview} />));

  expect(host.textContent).toContain("80%");
  expect(host.textContent).toContain("1 мин 5 с");
  expect(host.textContent).toContain("10");
});

it("не считает долю успеха и не падает в NaN, когда прогонов ещё не было", async () => {
  const overview = overviewWith({});

  await act(async () => root.render(<AdminSummaryCards overview={overview} />));

  expect(host.textContent).not.toContain("NaN");
  expect(host.textContent).toContain("—");
});
