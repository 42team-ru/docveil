import type { MaskFragment, MaskStatus } from "./types";

/**
 * Замены, найденные во втором прогоне «Договор_поставки_2026-114.pdf».
 * Пока бэкенда нет, это единственный источник данных для экрана проверки.
 */
export const maskFragments: MaskFragment[] = [
  {
    id: "m5",
    type: "ПОКУПАТЕЛЬ",
    original: "АО «Северэнергосбыт»",
    marker: "[ПОКУПАТЕЛЬ]",
    confidence: 0.41,
    page: 3,
    side: "покупатель",
  },
  {
    id: "m1",
    type: "ОРГАНИЗАЦИЯ",
    original: "ООО «ГрандСтройМонтаж»",
    marker: "[ПОСТАВЩИК]",
    confidence: 0.98,
    page: 1,
    side: "поставщик",
  },
  {
    id: "m2",
    type: "ИНН",
    original: "7714256389",
    marker: "[ИНН_1]",
    confidence: 0.99,
    page: 3,
    side: "поставщик",
  },
  {
    id: "m3",
    type: "АДРЕС",
    original: "г. Москва, ул. Верхняя, д. 34, стр. 2",
    marker: "[АДРЕС_1]",
    confidence: 0.87,
    page: 3,
    side: "поставщик",
  },
  {
    id: "m4",
    type: "ФИО",
    original: "Ковалёв Артём Сергеевич",
    marker: "[ФИО_1]",
    confidence: 0.97,
    page: 3,
    side: "поставщик",
  },
  {
    id: "m6",
    type: "ТЕЛЕФОН",
    original: "+7 495 128-44-90",
    marker: "[ТЕЛЕФОН_1]",
    confidence: 0.94,
    page: 3,
    side: "поставщик",
  },
  {
    id: "m7",
    type: "СУММА",
    original: "14 780 500,00 руб.",
    marker: "[СУММА_1]",
    confidence: 0.92,
    page: 3,
  },
  {
    id: "m8",
    type: "БАНК. СЧЁТ",
    original: "40702810400000012345",
    marker: "[СЧЁТ_1]",
    confidence: 0.99,
    page: 3,
    side: "поставщик",
  },
  {
    id: "m9",
    type: "ДАТА",
    original: "12 марта 2026 г.",
    marker: "[ДАТА_1]",
    confidence: 0.9,
    page: 3,
  },
  {
    id: "m10",
    type: "НОМЕР ДОГОВОРА",
    original: "ПО-114/26-ГСМ",
    marker: "[НОМЕР_1]",
    confidence: 0.88,
    page: 1,
  },
];

/** Состояние проверки на момент открытия экрана. */
export const initialMaskStatuses: Record<string, MaskStatus> = {
  m1: "ok",
  m2: "ok",
  m3: "pending",
  m4: "ok",
  m5: "low",
  m6: "pending",
  m7: "ok",
  m8: "ok",
  m9: "ok",
  m10: "pending",
};

/** Документ, открытый на проверку. */
export const reviewedDocument = {
  name: "Договор_поставки_2026-114",
  format: "PDF" as const,
  pages: 14,
  run: 2,
  currentPage: 3,
};
