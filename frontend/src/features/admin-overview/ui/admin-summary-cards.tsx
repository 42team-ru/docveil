import { Grid } from "@astryxdesign/core/Grid";

import { MetricCard } from "../../../shared/ui/charts/metric-card";
import type { AdminOverviewOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { formatDurationSeconds, formatPercent } from "../lib/format-stats";

type AdminSummaryCardsProps = {
  overview: AdminOverviewOut;
};

/** Ряд ключевых фактов вкладки «Обзор» — карточки, а не строки: это
 * standalone-виджеты (правило AGENTS.md про `Card`), а не список записей. */
export function AdminSummaryCards({ overview }: AdminSummaryCardsProps) {
  const { users, runs, sessions } = overview;

  return (
    <Grid columns={{ minWidth: 200, max: 6, repeat: "fit" }} gap={3}>
      <MetricCard
        label="Пользователи"
        value={String(users.total)}
        note={`${users.active} активных`}
      />
      <MetricCard
        label={`Прогоны за ${overview.window_days} дн.`}
        value={String(runs.total)}
        note={`${runs.in_progress} в работе`}
      />
      <MetricCard
        label="Доля успешных"
        value={formatPercent(runs.success_rate)}
        note={`${runs.succeeded} из ${runs.succeeded + runs.failed + runs.leaked}`}
      />
      <MetricCard
        label="Средняя длительность"
        value={formatDurationSeconds(runs.avg_duration_seconds)}
        note={
          runs.median_duration_seconds != null
            ? `медиана ${formatDurationSeconds(runs.median_duration_seconds)}`
            : undefined
        }
      />
      <MetricCard
        label="Живых сессий"
        value={String(sessions.active)}
        note={Object.keys(sessions.by_device ?? {}).length > 0 ? "по устройствам ниже" : undefined}
      />
      <MetricCard
        label="Администраторов"
        value={String(users.admins)}
        note={`${users.never_logged_in} ни разу не входили`}
      />
    </Grid>
  );
}
