import type { HistoryRecord, QueuedFile } from "./types";

/** Проекты, по которым разложены документы в истории. */
export const projects = [
  "Тендер 44-ФЗ/2026-0311",
  "Тендер 223-ФЗ/2026-0104",
  "Рамочные договоры",
  "Архив поставщиков",
  "Без проекта",
];

export const uploadQueue: QueuedFile[] = [
  {
    id: "q1",
    name: "Договор_поставки_2026-114.pdf",
    meta: "2.1 МБ · 14 стр. · слой текста 11/14",
    format: "PDF",
    tag: "скан 3 стр.",
    needsAttention: true,
  },
  {
    id: "q2",
    name: "Коммерческое_предложение_СЭС.docx",
    meta: "0.4 МБ · 6 стр. · 2 таблицы",
    format: "DOCX",
    tag: "готов",
    needsAttention: false,
  },
  {
    id: "q3",
    name: "Смета_оборудование_Q1.xlsx",
    meta: "1.7 МБ · 4 листа · 1 240 строк",
    format: "XLSX",
    tag: "готов",
    needsAttention: false,
  },
];

export const uploadQueueSummary = {
  files: 3,
  size: "4.2 МБ",
  estimate: "~40 сек · 1 файл со сканом → OCR",
};

const defaultRuns = (updated: string) => [
  {
    tag: "прогон 1",
    description:
      "Профиль «Тендерная документация». Изменений после проверки нет.",
    author: "система",
    when: updated,
  },
];

export const documentHistory: HistoryRecord[] = [
  {
    id: "h1",
    name: "Договор_поставки_2026-114.pdf",
    meta: "тендер № 44-ФЗ/2026-0311 · 14 стр.",
    project: "Тендер 44-ФЗ/2026-0311",
    replacements: 28,
    versions: 2,
    format: "PDF",
    updated: "сегодня 11:24",
    status: "ok",
    runs: defaultRuns("сегодня 11:24"),
  },
  {
    id: "h2",
    name: "Коммерческое_предложение_СЭС.docx",
    meta: "тендер № 44-ФЗ/2026-0311 · 6 стр.",
    project: "Тендер 44-ФЗ/2026-0311",
    replacements: 19,
    versions: 3,
    format: "DOCX",
    updated: "сегодня 10:58",
    status: "review",
    runs: [
      {
        tag: "прогон 3",
        description:
          "Добавлены типы: должности. Ответ на уточнение: покупатель — АО «Северэнергосбыт».",
        author: "а. орлова",
        when: "сегодня 10:58",
      },
      {
        tag: "прогон 2",
        description: "19 замен, 2 возвращены вручную (номер лота).",
        author: "а. орлова",
        when: "сегодня 09:31",
      },
      {
        tag: "прогон 1",
        description: "Профиль «Тендерная документация», 17 замен.",
        author: "система",
        when: "29 авг 17:10",
      },
    ],
  },
  {
    id: "h3",
    name: "Смета_оборудование_Q1.xlsx",
    meta: "тендер № 44-ФЗ/2026-0311 · 4 листа",
    project: "Тендер 44-ФЗ/2026-0311",
    replacements: 142,
    versions: 1,
    format: "XLSX",
    updated: "вчера 18:02",
    status: "run",
    runs: defaultRuns("вчера 18:02"),
  },
  {
    id: "h4",
    name: "Скан_доверенности.pdf",
    meta: "OCR · 2 стр. · уверенность 0.91",
    project: "Без проекта",
    replacements: 7,
    versions: 1,
    format: "PDF",
    updated: "вчера 16:40",
    status: "ocr",
    runs: defaultRuns("вчера 16:40"),
  },
  {
    id: "h5",
    name: "Финотчёт_2025_ГСМ.xlsx",
    meta: "архив поставщика · 12 листов",
    project: "Архив поставщиков",
    replacements: 311,
    versions: 2,
    format: "XLSX",
    updated: "27 авг",
    status: "ok",
    runs: defaultRuns("27 авг"),
  },
  {
    id: "h6",
    name: "Договор_субподряда_88.docx",
    meta: "тендер № 223-ФЗ/2026-0104 · 9 стр.",
    project: "Тендер 223-ФЗ/2026-0104",
    replacements: 24,
    versions: 1,
    format: "DOCX",
    updated: "26 авг",
    status: "ok",
    runs: defaultRuns("26 авг"),
  },
  {
    id: "h7",
    name: "Протокол_разногласий.docx",
    meta: "тендер № 223-ФЗ/2026-0104 · 3 стр.",
    project: "Тендер 223-ФЗ/2026-0104",
    replacements: 11,
    versions: 1,
    format: "DOCX",
    updated: "24 авг",
    status: "review",
    runs: defaultRuns("24 авг"),
  },
  {
    id: "h8",
    name: "Банковская_гарантия.pdf",
    meta: "скан · 2 стр.",
    project: "Без проекта",
    replacements: 9,
    versions: 1,
    format: "PDF",
    updated: "21 авг",
    status: "ok",
    runs: defaultRuns("21 авг"),
  },
  {
    id: "h9",
    name: "КП_Энергокомплект.pdf",
    meta: "архив · 8 стр.",
    project: "Архив поставщиков",
    replacements: 16,
    versions: 1,
    format: "PDF",
    updated: "19 авг",
    status: "ok",
    runs: defaultRuns("19 авг"),
  },
];

export const historySummary = "локальное хранилище · 214 документов · 1.2 ГБ";
