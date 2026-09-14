import { describe, expect, it } from "vitest";

import { formatDurationSeconds, formatPercent, successRateTone } from "./format-stats";

describe("formatDurationSeconds", () => {
  it("прочерк для null/undefined — считать было не из чего", () => {
    expect(formatDurationSeconds(null)).toBe("—");
    expect(formatDurationSeconds(undefined)).toBe("—");
  });

  it("секунды до минуты", () => {
    expect(formatDurationSeconds(42)).toBe("42 с");
  });

  it("минуты с остатком секунд", () => {
    expect(formatDurationSeconds(125)).toBe("2 мин 5 с");
  });

  it("ровные минуты без остатка", () => {
    expect(formatDurationSeconds(120)).toBe("2 мин");
  });

  it("часы с остатком минут", () => {
    expect(formatDurationSeconds(3900)).toBe("1 ч 5 мин");
  });

  it("ровные часы", () => {
    expect(formatDurationSeconds(7200)).toBe("2 ч");
  });
});

describe("formatPercent", () => {
  it("прочерк для null", () => {
    expect(formatPercent(null)).toBe("—");
  });

  it("округляет долю до процентов", () => {
    expect(formatPercent(0.923)).toBe("92%");
  });

  it("ноль — не то же самое, что null", () => {
    expect(formatPercent(0)).toBe("0%");
  });
});

describe("successRateTone", () => {
  it("neutral, когда считать было не из чего", () => {
    expect(successRateTone(null)).toBe("neutral");
  });

  it("success от 90%", () => {
    expect(successRateTone(0.95)).toBe("success");
  });

  it("warning от 70% до 90%", () => {
    expect(successRateTone(0.75)).toBe("warning");
  });

  it("error ниже 70%", () => {
    expect(successRateTone(0.5)).toBe("error");
  });
});
