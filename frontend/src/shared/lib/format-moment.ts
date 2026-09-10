/**
 * Момент времени в журнале и деталях документа: короткая локальная дата,
 * без выдуманных «2 часа назад».
 */
export function formatMoment(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
