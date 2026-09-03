import { create } from "zustand";

import { initialMaskStatuses, maskFragments } from "./fixtures";
import type { MaskStatus } from "./types";

type MaskState = {
  statuses: Record<string, MaskStatus>;
  selectedId: string | null;
  select: (id: string) => void;
  confirm: (id: string) => void;
  reject: (id: string) => void;
  confirmAll: () => void;
};

/**
 * Состояние ручной проверки замен. Живёт в сущности, а не в фиче, потому что
 * счётчик ожидающих нужен и правой панели `/review`, и бейджу в рейле.
 */
export const useMaskStore = create<MaskState>((set) => ({
  statuses: initialMaskStatuses,
  selectedId: "m5",
  select: (id) => set({ selectedId: id }),
  confirm: (id) =>
    set((state) => ({
      selectedId: id,
      statuses: { ...state.statuses, [id]: "ok" },
    })),
  reject: (id) =>
    set((state) => ({
      selectedId: id,
      statuses: { ...state.statuses, [id]: "pending" },
    })),
  confirmAll: () =>
    set((state) => ({
      statuses: Object.fromEntries(
        Object.keys(state.statuses).map((id) => [id, "ok" as MaskStatus]),
      ),
    })),
}));

export const useMaskStatus = (id: string): MaskStatus =>
  useMaskStore((state) => state.statuses[id] ?? "pending");

export const useConfirmedCount = (): number =>
  useMaskStore(
    (state) => Object.values(state.statuses).filter((s) => s === "ok").length,
  );

export const usePendingCount = (): number =>
  useMaskStore(
    (state) => Object.values(state.statuses).filter((s) => s !== "ok").length,
  );

export const useTotalCount = (): number => maskFragments.length;

/** Замены с низкой уверенностью модели — им нужен глаз оператора. */
export const useLowConfidenceCount = (): number =>
  useMaskStore(
    (state) => Object.values(state.statuses).filter((s) => s === "low").length,
  );
