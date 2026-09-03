#!/usr/bin/env node
/**
 * Собирает синтетический public/test.xlsx для разработки XLSX-вьюера —
 * реального файла и примера JSON с якорями для xlsx от заказчика ещё нет
 * (см. src/entity/pii/model/xlsx-fixtures.ts, где чанки построены по этому
 * же файлу). Реестр исполнителей — правдоподобное приложение к
 * public/test.docx (гос. контракт на услуги ПО, ЯНАО): "шапка" реестра,
 * колонка ролей без ПДн и уже промаскированные ФИО/ИНН/телефон/адрес —
 * тот же принцип, что и в docx: маркер вписан в ячейку как есть, оригинала
 * в файле нет.
 *
 * Перезапуск: node scripts/make-sample-xlsx.mjs
 */
import ExcelJS from "exceljs";

const workbook = new ExcelJS.Workbook();
workbook.creator = "TriemaMasker (тестовые данные)";

const sheet = workbook.addWorksheet("Реестр");

sheet.columns = [
  { key: "no", width: 5 },
  { key: "role", width: 22 },
  { key: "name", width: 26 },
  { key: "inn", width: 16 },
  { key: "phone", width: 18 },
  { key: "address", width: 32 },
];

const HEADER_FILL = { type: "pattern", pattern: "solid", fgColor: { argb: "FF1F1F22" } };
const HEADER_FONT = { bold: true, color: { argb: "FFFFFFFF" } };
const BANDED_FILL = { type: "pattern", pattern: "solid", fgColor: { argb: "FFF1F4F7" } };
const THIN_BORDER = { style: "thin", color: { argb: "FFCCD3DB" } };
const ALL_BORDERS = { top: THIN_BORDER, left: THIN_BORDER, bottom: THIN_BORDER, right: THIN_BORDER };

sheet.mergeCells("A1:F1");
const title = sheet.getCell("A1");
title.value = "Реестр исполнителей по Контракту № 2026-114";
title.font = { bold: true, size: 13 };
title.alignment = { horizontal: "center", vertical: "middle" };
sheet.getRow(1).height = 24;

const headerRow = sheet.getRow(2);
headerRow.values = ["№", "Роль", "ФИО", "ИНН", "Телефон", "Адрес"];
headerRow.eachCell((cell) => {
  cell.fill = HEADER_FILL;
  cell.font = HEADER_FONT;
  cell.alignment = { horizontal: "center", vertical: "middle" };
  cell.border = ALL_BORDERS;
});

const rows = [
  { no: 1, role: "Руководитель проекта", name: "[ФИО-1]", inn: "[ИНН-1]", phone: "[ТЕЛЕФОН-1]", address: "[АДРЕС-1]" },
  { no: 2, role: "Технический специалист", name: "[ФИО-2]", inn: "[ИНН-2]", phone: "[ТЕЛЕФОН-2]", address: "[АДРЕС-1]" },
  { no: 3, role: "Технический специалист", name: "[ФИО-3]", inn: "[ИНН-3]", phone: "[ТЕЛЕФОН-3]", address: "[АДРЕС-2]" },
  { no: 4, role: "Аналитик", name: "[ФИО-4]", inn: "[ИНН-4]", phone: "[ТЕЛЕФОН-4]", address: "[АДРЕС-1]" },
  { no: 5, role: "Куратор со стороны Заказчика", name: "[ФИО-5]", inn: "—", phone: "[ТЕЛЕФОН-5]", address: "[АДРЕС-3]" },
];

rows.forEach((data, index) => {
  const row = sheet.addRow(data);
  row.eachCell((cell) => {
    cell.border = ALL_BORDERS;
    cell.alignment = { vertical: "middle" };
    if (index % 2 === 1) cell.fill = BANDED_FILL;
  });
});

sheet.views = [{ state: "frozen", ySplit: 2 }];

await workbook.xlsx.writeFile(new URL("../public/test.xlsx", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));

console.log("public/test.xlsx готов:", rows.length, "строк, маркеры:", [
  ...new Set(rows.flatMap((r) => [r.name, r.inn, r.phone, r.address]).filter((v) => v !== "—")),
]);
