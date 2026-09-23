import { describe, expect, it } from "vitest";

import {
  canStartReviewSubmission,
  reviewConfirmationDescription,
  shouldShowReviewFinish,
} from "./review-lifecycle";

describe("review lifecycle", () => {
  it("оставляет завершение проверки доступным только на awaiting_review", () => {
    expect(shouldShowReviewFinish("awaiting_review")).toBe(true);
    expect(shouldShowReviewFinish("done")).toBe(false);
    expect(shouldShowReviewFinish("leaked")).toBe(false);
    expect(shouldShowReviewFinish("running")).toBe(false);
  });

  it("не запускает второй запрос во время отправки или после принятого 202", () => {
    expect(canStartReviewSubmission("awaiting_review", false, false)).toBe(true);
    expect(canStartReviewSubmission("awaiting_review", true, false)).toBe(false);
    expect(canStartReviewSubmission("awaiting_review", false, true)).toBe(false);
    expect(canStartReviewSubmission("done", false, false)).toBe(false);
    expect(canStartReviewSubmission("leaked", false, false)).toBe(false);
  });

  it("объясняет пустую проверку без ложного счётчика 0/0", () => {
    expect(reviewConfirmationDescription(0, 0)).toContain("не нашла сущностей");
    expect(reviewConfirmationDescription(0, 0)).not.toContain("0 из 0");
    expect(reviewConfirmationDescription(3, 5)).toContain("3 из 5 групп");
    expect(reviewConfirmationDescription(5, 5)).toContain("проверка будет завершена");
  });
});
