import type { PiiType } from "./types";

type PiiTypeInfo = {
  label: string;
  /** Префикс маркера, каким его формирует бэкенд, напр. «ФИО» → [ФИО-1]. */
  markerPrefix: string;
  /** Пропуск такого типа — утечка: движок маскирует его без вопроса. */
  critical: boolean;
};

/**
 * Подписи типов. `label` и `markerPrefix` — дословно из `builtin_specs()`
 * (`backend/src/masker/entity_types.py`), `critical` — из `CRITICAL_TYPES`
 * (`backend/src/masker/model.py`). Это тот же источник, из которого движок
 * собирает маркер в документе, поэтому расхождение здесь оператор видит
 * сразу — в файле, а не в интерфейсе.
 */
const PII_TYPE_DICT: Record<PiiType, PiiTypeInfo> = {
  org_name: { label: "Организация", markerPrefix: "ОРГАНИЗАЦИЯ", critical: false },
  person: { label: "ФИО", markerPrefix: "ФИО", critical: false },
  inn: { label: "ИНН", markerPrefix: "ИНН", critical: true },
  kpp: { label: "КПП", markerPrefix: "КПП", critical: false },
  ogrn: { label: "ОГРН", markerPrefix: "ОГРН", critical: true },
  snils: { label: "СНИЛС", markerPrefix: "СНИЛС", critical: true },
  bank_account: { label: "Банковский счёт", markerPrefix: "СЧЁТ", critical: true },
  bik: { label: "БИК", markerPrefix: "БИК", critical: false },
  bank_name: { label: "Банк", markerPrefix: "БАНК", critical: false },
  address: { label: "Адрес", markerPrefix: "АДРЕС", critical: false },
  phone: { label: "Телефон", markerPrefix: "ТЕЛЕФОН", critical: false },
  email: { label: "Email", markerPrefix: "ПОЧТА", critical: false },
  passport: { label: "Паспорт", markerPrefix: "ПАСПОРТ", critical: true },
  contract_number: { label: "Номер договора", markerPrefix: "ДОГОВОР", critical: false },
  money: { label: "Сумма", markerPrefix: "СУММА", critical: false },
  date: { label: "Дата", markerPrefix: "ДАТА", critical: false },
  birth_date: { label: "Дата рождения", markerPrefix: "РОЖДЕНИЕ", critical: false },
  site: { label: "Сайт", markerPrefix: "САЙТ", critical: false },
  federal_law: { label: "Федеральный закон", markerPrefix: "ФЗ", critical: false },
  contract_amount: { label: "Сумма договора", markerPrefix: "СУММА-ДОГОВОРА", critical: false },
  delivery_period: { label: "Срок поставки", markerPrefix: "СРОК-ПОСТАВКИ", critical: false },
  payment_terms: { label: "Условия оплаты", markerPrefix: "УСЛОВИЯ-ОПЛАТЫ", critical: false },
};

/** Русская подпись типа. Неизвестный бэкенду тип подписывается как есть. */
export function piiTypeLabel(type: PiiType): string {
  return PII_TYPE_DICT[type]?.label ?? type;
}

/** Префикс маркера типа; для неизвестного типа — сам идентификатор. */
export function piiTypeMarkerPrefix(type: PiiType): string {
  return PII_TYPE_DICT[type]?.markerPrefix ?? type;
}

/**
 * Критичность типа. Неизвестный тип (пользовательский из custom types)
 * считается некритичным: его критичность объявляет спека, а не этот словарь.
 */
export function isCriticalPiiType(type: PiiType): boolean {
  return PII_TYPE_DICT[type]?.critical ?? false;
}

export function piiTypeOptions(): { value: PiiType; label: string }[] {
  return (Object.keys(PII_TYPE_DICT) as PiiType[]).map((value) => ({
    value,
    label: PII_TYPE_DICT[value].label,
  }));
}
