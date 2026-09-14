/**
 * Русская подпись узла графа по `node_hint` (`AdminFailureOut.node_hint`,
 * `RunResponse.node_hint`) — тот же словарь узлов, что и `STAGE_LABELS` в
 * `masking-report/ui/report-resources.tsx`, только этот участок кода не
 * импортирует оттуда: тот файл — приватная реализация вкладки «Ресурсы»
 * отчёта одного прогона, а не общий словарь. Осознанное маленькое
 * дублирование: имена узлов графа меняются редко, и то же лечится
 * одинаково в обоих местах при следующей правке словаря.
 */
const NODE_LABEL: Record<string, string> = {
  extract: "Извлечение",
  detect: "Поиск данных",
  profile: "Профили сторон",
  judge: "Проверка находок",
  policy: "Политика",
  plan: "План замен",
  summary: "Содержание",
  render: "Рендер",
  validate: "Проверка утечек",
  report: "Отчёт",
  apply_answers: "Применение ответов",
  ask_human: "Вопрос оператору",
  image_export: "Экспорт изображений",
  finalize: "Завершение",
  ask_review: "Вопрос на проверке",
  apply_review_edits: "Применение правок",
};

/** `null` — граф упал до входа в узел (например, при извлечении файла из MinIO). */
export function graphNodeLabel(node: string | null | undefined): string {
  if (!node) return "До начала графа";
  return NODE_LABEL[node] ?? node;
}
