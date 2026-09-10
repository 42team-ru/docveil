/**
 * Момент времени в журнале и деталях документа: короткая локальная дата,
 * без выдуманных «2 часа назад». Год короткий, но обязателен — журнал живёт
 * дольше одного года, и без него записи из разных январей неотличимы.
 */
export function formatMoment(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
