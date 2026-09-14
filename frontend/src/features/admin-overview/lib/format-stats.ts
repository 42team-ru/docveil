/**
 * Форматирование чисел админки. Отдельно от
 * `masking-report/ui/report-resources.tsx#formatDuration`: там миллисекунды
 * одного узла графа (обычно доли секунды), здесь — секунды целого прогона
 * (обычно десятки секунд — минуты), и шкала другая.
 */
export function formatDurationSeconds(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)} с`;

  const totalMinutes = Math.floor(seconds / 60);
  if (totalMinutes < 60) {
    const remainingSeconds = Math.round(seconds - totalMinutes * 60);
    return remainingSeconds > 0 ? `${totalMinutes} мин ${remainingSeconds} с` : `${totalMinutes} мин`;
  }

  const hours = Math.floor(totalMinutes / 60);
  const remainingMinutes = totalMinutes - hours * 60;
  return remainingMinutes > 0 ? `${hours} ч ${remainingMinutes} мин` : `${hours} ч`;
}

/** Доля 0..1 → «92%»; `null` — считать было не из чего (см. `success_rate`
 * в `AdminRunsStatsOut` — `None`, когда завершённых прогонов ещё не было). */
export function formatPercent(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

export type SuccessRateTone = "success" | "warning" | "error" | "neutral";

/** Цвет `StatusDot`/`Token` для доли успешных прогонов. */
export function successRateTone(rate: number | null | undefined): SuccessRateTone {
  if (rate == null) return "neutral";
  if (rate >= 0.9) return "success";
  if (rate >= 0.7) return "warning";
  return "error";
}
