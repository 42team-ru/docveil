import type { RulePreset } from "./types";

/**
 * Пресеты правил маскирования.
 *
 * Списка типов здесь больше нет: он строится из общего словаря
 * `entity/pii/model/pii-type-dict.ts` в `features/document-upload` — фича
 * вправе видеть обе сущности, а горизонтальный импорт `entity/rule-profile`
 * → `entity/pii` запрещён (ARCHITECTURE.md, «Границы слоёв»). До этого фронт
 * держал здесь третий, ни с чем не совпадающий набор идентификаторов
 * (`org`, `fio`, `addr`, `pass`) плюс «Должности», которых в движке нет.
 */
export const rulePresets: RulePreset[] = [
  {
    id: "tender",
    name: "Тендерная документация",
    description: "Стороны, реквизиты, счета и номер договора.",
  },
  {
    id: "full",
    name: "Максимальное обезличивание",
    description: "Все типы реестра, включая даты и коммерческие условия.",
  },
  {
    id: "fin",
    name: "Финансовый отчёт",
    description: "Счета, суммы и сроки скрыты, названия сторон остаются.",
  },
];

/**
 * Типы, включённые профилем «Тендерная документация». Идентификаторы — те же,
 * что у `EntityType` бэкенда (`backend/src/masker/model.py`).
 */
export const defaultEnabledTypes: string[] = [
  "org_name",
  "person",
  "inn",
  "kpp",
  "ogrn",
  "bank_account",
  "bik",
  "address",
  "phone",
  "email",
  "passport",
  "contract_number",
];
