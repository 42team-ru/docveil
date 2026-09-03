import type { PiiType } from "./types";

type PiiTypeInfo = {
  label: string;
  /** Префикс маркера, каким его формирует бэкенд, напр. «ФИО» → [ФИО-1]. */
  markerPrefix: string;
};

const PII_TYPE_DICT: Record<PiiType, PiiTypeInfo> = {
  org_name: { label: "Организация", markerPrefix: "ОРГАНИЗАЦИЯ" },
  person_name: { label: "ФИО", markerPrefix: "ФИО" },
  address: { label: "Адрес", markerPrefix: "АДРЕС" },
  bank_account: { label: "Банк. счёт", markerPrefix: "СЧЁТ" },
  inn: { label: "ИНН", markerPrefix: "ИНН" },
  kpp: { label: "КПП", markerPrefix: "КПП" },
  email: { label: "Почта", markerPrefix: "ПОЧТА" },
  website: { label: "Сайт", markerPrefix: "САЙТ" },
  phone: { label: "Телефон", markerPrefix: "ТЕЛЕФОН" },
  money: { label: "Сумма", markerPrefix: "СУММА" },
  date: { label: "Дата", markerPrefix: "ДАТА" },
  contract_no: { label: "Номер договора", markerPrefix: "НОМЕР" },
};

/** Русская подпись типа ПДн. Неизвестный бэкенду тип подписывается как есть. */
export function piiTypeLabel(type: PiiType): string {
  return PII_TYPE_DICT[type]?.label ?? type;
}

export function piiTypeOptions(): { value: PiiType; label: string }[] {
  return (Object.keys(PII_TYPE_DICT) as PiiType[]).map((value) => ({
    value,
    label: PII_TYPE_DICT[value].label,
  }));
}
