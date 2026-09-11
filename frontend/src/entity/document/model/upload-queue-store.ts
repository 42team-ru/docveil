import { create } from "zustand";

import type { DocumentFormat, UploadSource } from "./types";

export type { UploadSource };

/** Файл, выбранный оператором, вместе с состоянием его прогона. */
export type QueuedUpload = {
  id: string;
  name: string;
  /** `null` — размер неизвестен (повторный прогон уже загруженного файла). */
  size: number | null;
  format: DocumentFormat;
  source: UploadSource;
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
  addExisting: (input: { objectName: string; name: string; format: DocumentFormat }) => void;
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
  jpg: "JPG",
  jpeg: "JPEG",
  png: "PNG",
  tif: "TIF",
  tiff: "TIFF",
};

/** Формат по расширению; неизвестное расширение показываем как DOCX-заглушку. */
function formatOf(name: string): DocumentFormat {
  const suffix = name.slice(name.lastIndexOf(".") + 1).toLowerCase();
  return FORMAT_BY_SUFFIX[suffix] ?? "DOCX";
}

/** Человекочитаемый размер файла для строки очереди; `null` — размер неизвестен. */
export function formatSize(bytes: number | null): string {
  if (bytes === null) return "—";
  const megabytes = bytes / 1024 / 1024;
  if (megabytes >= 1) return `${megabytes.toFixed(1)} МБ`;
  return `${Math.max(1, Math.round(bytes / 1024))} КБ`;
}

/**
 * Очередь файлов текущей задачи. Живёт в сущности, а не в фиче загрузки:
 * список нужен и экрану загрузки, и деталям журнала («Повторить прогон» в
 * `run-details-dialog.tsx` из `features/document-history`) — двум разным
 * фичам, которые не должны знать друг о друге напрямую.
 */
export const useUploadQueueStore = create<UploadQueueState>((set) => ({
  items: [],
  add: (files) =>
    set((state) => ({
      items: [
        ...state.items,
        ...files.map(
          (file): QueuedUpload => ({
            id: `${file.name}-${file.size}-${file.lastModified}`,
            name: file.name,
            size: file.size,
            format: formatOf(file.name),
            source: { kind: "file", file },
            state: "pending",
            runId: null,
            error: null,
          }),
        ),
      ].filter(
        // Один и тот же файл, выбранный дважды, — это один элемент очереди:
        // иначе оператор случайно заведёт два одинаковых прогона.
        (item, index, all) => all.findIndex((other) => other.id === item.id) === index,
      ),
    })),
  addExisting: ({ objectName, name, format }) =>
    set((state) => {
      const id = `existing-${objectName}`;
      if (state.items.some((item) => item.id === id)) return state;
      return {
        items: [
          ...state.items,
          {
            id,
            name,
            size: null,
            format,
            source: { kind: "existing", objectName },
            state: "pending",
            runId: null,
            error: null,
          },
        ],
      };
    }),
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
