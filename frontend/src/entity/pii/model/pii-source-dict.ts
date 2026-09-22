import type { PiiSource } from "./types";

/**
 * Подпись слоя детекции — `PiiSource` из `masker.model.Source`. Общий
 * источник для таблицы замен (`report-table.tsx`) и вкладки «Ресурсы»
 * (`report-resources.tsx`), чтобы значения вроде `rule`/`gliner` не уходили
 * в интерфейс сырыми английскими идентификаторами.
 */
export const PII_SOURCE_LABEL: Record<PiiSource | "gliner", string> = {
  rule: "Правила",
  ner: "Локальный NER (Natasha)",
  gliner: "GLiNER",
  block: "Блоки реквизитов",
  llm: "Модель",
  user: "Свои типы",
  cv: "CV-детектор",
  ml: "ML-модель",
};

/** Русская подпись слоя детекции. Неизвестный бэкенду источник подписывается как есть. */
export function piiSourceLabel(source: string): string {
  return PII_SOURCE_LABEL[source as PiiSource | "gliner"] ?? source;
}
