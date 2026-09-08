import { create } from "zustand";

import type { DocumentFormat } from "../../../entity/document/model/types";

/** Файл, выбранный оператором, вместе с состоянием его прогона. */
export type QueuedUpload = {
  id: string;
  file: File;
  format: DocumentFormat;
  /**
   * `pending` — файл только выбран; `starting` — идёт загрузка в хранилище и
   * заведение прогона; `started` — прогон заведён (`runId` заполнен);
   * `failed` — не удалось, причина в `error`.
   */
  state: "pending" | "starting" | "started" | "failed";
  runId: string | null;
  error: string | null;
};

type UploadQueueState = {
  items: QueuedUpload[];
  add: (files: File[]) => void;
  remove: (id: string) => void;
  clear: () => void;
  markStarting: (id: string) => void;
  markStarted: (id: string, runId: string) => void;
  markFailed: (id: string, error: string) => void;
};

const FORMAT_BY_SUFFIX: Record<string, DocumentFormat> = {
  pdf: "PDF",
  docx: "DOCX",
  xlsx: "XLSX",
};

/** Формат по расширению; неизвестное расширение показываем как DOCX-заглушку. */
function formatOf(name: string): DocumentFormat {
  const suffix = name.slice(name.lastIndexOf(".") + 1).toLowerCase();
  return FORMAT_BY_SUFFIX[suffix] ?? "DOCX";
}

/** Человекочитаемый размер файла для строки очереди. */
export function formatSize(bytes: number): string {
  const megabytes = bytes / 1024 / 1024;
  if (megabytes >= 1) return `${megabytes.toFixed(1)} МБ`;
  return `${Math.max(1, Math.round(bytes / 1024))} КБ`;
}

/**
 * Очередь файлов текущей задачи. Живёт в сторе, а не в состоянии дропзоны:
 * список нужен и панели очереди, и кнопке запуска — это три разных
 * компонента на одном экране.
 */
export const useUploadQueueStore = create<UploadQueueState>((set) => ({
  items: [],
  add: (files) =>
    set((state) => ({
      items: [
        ...state.items,
        ...files.map((file) => ({
          id: `${file.name}-${file.size}-${file.lastModified}`,
          file,
          format: formatOf(file.name),
          state: "pending" as const,
          runId: null,
          error: null,
        })),
      ].filter(
        // Один и тот же файл, выбранный дважды, — это один элемент очереди:
        // иначе оператор случайно заведёт два одинаковых прогона.
        (item, index, all) => all.findIndex((other) => other.id === item.id) === index,
      ),
    })),
  remove: (id) => set((state) => ({ items: state.items.filter((item) => item.id !== id) })),
  clear: () => set({ items: [] }),
  markStarting: (id) =>
    set((state) => ({
      items: state.items.map((item) =>
        item.id === id ? { ...item, state: "starting", error: null } : item,
      ),
    })),
  markStarted: (id, runId) =>
    set((state) => ({
      items: state.items.map((item) =>
        item.id === id ? { ...item, state: "started", runId } : item,
      ),
    })),
  markFailed: (id, error) =>
    set((state) => ({
      items: state.items.map((item) =>
        item.id === id ? { ...item, state: "failed", error } : item,
      ),
    })),
}));
