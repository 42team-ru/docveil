import { useEffect } from "react";

import { useReviewStore } from "../../../entity/pii/model/review-store";

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return true;
  return target.isContentEditable;
}

function isInsideOverlay(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.closest('[role="dialog"]') !== null;
}

/**
 * j/k/a/r из document-toolbar.tsx — раньше только подсказки в Kbd, ничего не
 * перехватывалось. Обязательна охрана фокуса: без неё `r` во время ввода
 * границ или в попапе добавления срабатывал бы как «вернуть» посреди печати.
 */
export function useReviewHotkeys(
  orderedOccurrenceIds: string[],
  groupIdByOccurrenceId: Map<string, string>,
): void {
  useEffect(() => {
    function handler(event: KeyboardEvent) {
      if (event.isComposing) return;
      if (isEditableTarget(event.target)) return;
      if (isInsideOverlay(event.target)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const state = useReviewStore.getState();

      if (event.key === "j" || event.key === "k") {
        const currentIndex = orderedOccurrenceIds.indexOf(
          state.selectedOccurrenceId ?? "",
        );
        const nextIndex =
          event.key === "j"
            ? Math.min(currentIndex + 1, orderedOccurrenceIds.length - 1)
            : Math.max(currentIndex - 1, 0);
        const nextId = orderedOccurrenceIds[nextIndex];
        if (nextId) state.select(nextId);
        return;
      }

      if (event.key === "a" || event.key === "r") {
        if (!state.selectedOccurrenceId) return;
        const groupId = groupIdByOccurrenceId.get(state.selectedOccurrenceId);
        if (!groupId) return;
        if (event.key === "a") state.confirmGroup(groupId);
        else state.rejectGroup(groupId);
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [orderedOccurrenceIds, groupIdByOccurrenceId]);
}
