import type { RunStatus } from "../../masking-run/api/masking-run";

export function shouldShowReviewFinish(status: RunStatus | null | undefined): boolean {
  return status === "awaiting_review";
}

export function canStartReviewSubmission(
  status: RunStatus | null | undefined,
  isPending: boolean,
  isSubmitted: boolean,
): boolean {
  return shouldShowReviewFinish(status) && !isPending && !isSubmitted;
}

export function reviewConfirmationDescription(confirmedCount: number, totalCount: number): string {
  if (totalCount === 0) {
    return "Система не нашла сущностей для маскирования. Документ пересоберётся и проверка будет завершена.";
  }
  if (confirmedCount === totalCount) {
    return "Документ пересоберётся и проверка будет завершена.";
  }
  return `${confirmedCount} из ${totalCount} групп будут заменены на маркер, остальные — оставлены как есть по вашему решению. Документ пересоберётся с учётом этого.`;
}
