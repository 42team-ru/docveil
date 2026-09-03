import { parsePiiExtraction } from "./schema";

/**
 * Фикстура для `public/test.xlsx` — синтетического «Реестра исполнителей»
 * (см. scripts/make-sample-xlsx.mjs). Реального файла и примера JSON с
 * якорями для xlsx от заказчика ещё нет: и файл, и разметка собраны вместе,
 * специально чтобы не повторить ошибку, которая уже была с docx (там план
 * сперва угадал форму привязки, не имея реального файла, и пришлось
 * переделывать). Здесь оба артефакта согласованы по построению — риск
 * рассинхронизации только в том, совпадёт ли форма `anchor.locator` с тем,
 * что в итоге отдаст бэкенд (см. комментарий в xlsx-anchor-index.ts).
 *
 * Координаты — 1-based, row/col как их считает exceljs.
 */
const SHEET = "Реестр";

const rawPayload = {
  chunk_count: 19,
  chunks: [
    // Строка 3 — Руководитель проекта
    cellChunk(3, 3, "[ФИО-1]", "XG1", "person_name", "Соколова Мария Владимировна", 0.96),
    cellChunk(3, 4, "[ИНН-1]", "XG2", "inn", "772813444501", 0.98, "rule"),
    cellChunk(3, 5, "[ТЕЛЕФОН-1]", "XG3", "phone", "+7 495 212-33-01", 0.93, "rule"),
    cellChunk(3, 6, "[АДРЕС-1]", "XG4", "address", "г. Москва, ул. Тверская, д. 5", 0.88, "rule"),

    // Строка 4 — Технический специалист
    cellChunk(4, 3, "[ФИО-2]", "XG5", "person_name", "Дмитриев Олег Игоревич", 0.95),
    cellChunk(4, 4, "[ИНН-2]", "XG6", "inn", "500100222303", 0.98, "rule"),
    cellChunk(4, 5, "[ТЕЛЕФОН-2]", "XG7", "phone", "+7 495 212-33-02", 0.93, "rule"),
    cellChunk(4, 6, "[АДРЕС-1]", "XG4", "address", "г. Москва, ул. Тверская, д. 5", 0.88, "rule"),

    // Строка 5 — Технический специалист
    cellChunk(5, 3, "[ФИО-3]", "XG8", "person_name", "Кузнецова Анна Сергеевна", 0.95),
    cellChunk(5, 4, "[ИНН-3]", "XG9", "inn", "631200987654", 0.98, "rule"),
    cellChunk(5, 5, "[ТЕЛЕФОН-3]", "XG10", "phone", "+7 495 212-33-03", 0.93, "rule"),
    cellChunk(5, 6, "[АДРЕС-2]", "XG11", "address", "г. Москва, Ленинский пр-т, д. 40", 0.88, "rule"),

    // Строка 6 — Аналитик
    cellChunk(6, 3, "[ФИО-4]", "XG12", "person_name", "Захаров Никита Павлович", 0.95),
    cellChunk(6, 4, "[ИНН-4]", "XG13", "inn", "770300112244", 0.98, "rule"),
    cellChunk(6, 5, "[ТЕЛЕФОН-4]", "XG14", "phone", "+7 495 212-33-04", 0.93, "rule"),
    cellChunk(6, 6, "[АДРЕС-1]", "XG4", "address", "г. Москва, ул. Тверская, д. 5", 0.88, "rule"),

    // Строка 7 — Куратор со стороны Заказчика (ИНН не найден — "—" не ПДн)
    cellChunk(7, 3, "[ФИО-5]", "XG15", "person_name", "Волкова Елена Дмитриевна", 0.41),
    cellChunk(7, 5, "[ТЕЛЕФОН-5]", "XG16", "phone", "+7 495 212-33-05", 0.93, "rule"),
    cellChunk(7, 6, "[АДРЕС-3]", "XG17", "address", "г. Москва, Кутузовский пр-т, д. 12", 0.88, "rule"),
  ],
};

function pii(
  ref: string,
  groupId: string,
  marker: string,
  type: string,
  original: string,
  confidence: number,
  source: "ner" | "rule",
) {
  return {
    ref,
    group_id: groupId,
    marker,
    type,
    text: original,
    normalized: original.toLowerCase(),
    confidence,
    source,
    segment_order: 0,
    chunk_start: 0,
    chunk_end: marker.length,
    anchor: { format: "xlsx", label: "", locator: [] as (string | number)[] },
  };
}

/** Одна ячейка = один чанк с одним вхождением — в отличие от docx, где чанк
 * это целый абзац с несколькими ПДн внутри сплошного текста, в таблице
 * каждое ПДн уже само по себе занимает отдельную ячейку. */
function cellChunk(
  row: number,
  col: number,
  marker: string,
  groupId: string,
  type: string,
  original: string,
  confidence: number,
  source: "ner" | "rule" = "ner",
) {
  const anchor = {
    format: "xlsx",
    label: `${SHEET}!R${row}C${col}`,
    locator: ["sheet", SHEET, row, col],
  };
  const segmentOrder = row * 1000 + col;
  const ref = `XE${row}${col}`;

  return {
    id: `cell-${row}-${col}`,
    text: marker,
    anchor,
    segment_order: segmentOrder,
    pii: [
      {
        ...pii(ref, groupId, marker, type, original, confidence, source),
        segment_order: segmentOrder,
        anchor,
      },
    ],
  };
}

export const piiExtractionXlsxFixture = parsePiiExtraction(rawPayload);

export const reviewedXlsxDocumentFixture = {
  name: "Реестр_исполнителей_2026-114",
  format: "xlsx" as const,
  fileUrl: "/test.xlsx",
};
