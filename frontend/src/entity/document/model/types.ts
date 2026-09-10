export type DocumentFormat = "PDF" | "DOCX" | "XLSX";

/**
 * Откуда взять байты документа при запуске: новый файл из дропзоны
 * (загружается в хранилище перед запуском) или уже загруженный объект
 * прошлого прогона («Повторить прогон» в `run-details-dialog.tsx`) — для
 * него запуск идёт сразу по `objectName`, без повторной загрузки.
 */
export type UploadSource =
  | { kind: "file"; file: File }
  | { kind: "existing"; objectName: string };

/** Состояние документа в локальном хранилище. */
export type DocumentStatus = "ok" | "review" | "ocr" | "run";

/** Файл, поставленный в очередь на обезличивание. */
export type QueuedFile = {
  id: string;
  name: string;
  /** Размер, число страниц, наличие текстового слоя. */
  meta: string;
  format: DocumentFormat;
  /** Короткая пометка: «готов», «скан 3 стр.». */
  tag: string;
  /** Нужен ли файлу OCR — тогда пометка подсвечивается. */
  needsAttention: boolean;
};

/** Один прогон обработки документа. */
export type RunRecord = {
  tag: string;
  description: string;
  author: string;
  when: string;
};

/** Запись в истории файлов. */
export type HistoryRecord = {
  id: string;
  name: string;
  meta: string;
  project: string;
  replacements: number;
  versions: number;
  format: DocumentFormat;
  updated: string;
  status: DocumentStatus;
  runs: RunRecord[];
};
