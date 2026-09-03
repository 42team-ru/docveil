import type { DataType, RulePreset } from "./types";

export const dataTypes: DataType[] = [
  { id: "org", name: "Наименование организации", marker: "[ОРГАНИЗАЦИЯ_N]" },
  { id: "inn", name: "ИНН / КПП", marker: "[ИНН_N]" },
  { id: "ogrn", name: "ОГРН", marker: "[ОГРН_N]" },
  { id: "fio", name: "ФИО", marker: "[ФИО_N]" },
  { id: "post", name: "Должности", marker: "[ДОЛЖНОСТЬ_N]" },
  { id: "pass", name: "Паспортные данные", marker: "[ПАСПОРТ_N]" },
  { id: "addr", name: "Адреса", marker: "[АДРЕС_N]" },
  { id: "phone", name: "Телефоны", marker: "[ТЕЛЕФОН_N]" },
  { id: "email", name: "E-mail и сайты", marker: "[EMAIL_N]" },
  { id: "bank", name: "Банковские реквизиты", marker: "[СЧЁТ_N]" },
  { id: "money", name: "Суммы и цены", marker: "[СУММА_N]" },
  { id: "contract", name: "Номера договоров", marker: "[НОМЕР_N]" },
];

export const rulePresets: RulePreset[] = [
  {
    id: "tender",
    name: "Тендерная документация",
    description: "Стороны, реквизиты, суммы. Предмет и сроки сохраняются.",
  },
  {
    id: "full",
    name: "Максимальное обезличивание",
    description: "Все 12 типов, включая должности и даты.",
  },
  {
    id: "fin",
    name: "Финансовый отчёт",
    description: "Суммы и счета скрыты, названия сторон остаются.",
  },
];

/** Типы, включённые профилем «Тендерная документация». */
export const defaultEnabledTypes = [
  "org",
  "inn",
  "fio",
  "addr",
  "phone",
  "email",
  "bank",
  "money",
  "contract",
];
