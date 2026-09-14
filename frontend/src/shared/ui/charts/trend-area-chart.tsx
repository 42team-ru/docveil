import { useId } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Text } from "@astryxdesign/core/Text";

import { useChartTheme } from "./chart-theme";

/** Одна точка временного ряда — форма `DayCountOut` с бэкенда (`date`, `count`),
 * но без зависимости `shared` от сгенерированного API-клиента: тип описан
 * по форме, а не импортирован. */
export type TrendDatum = { date: string; count: number };

type TrendAreaChartProps = {
  data: TrendDatum[];
  height?: number;
  valueFormatter?: (value: number) => string;
  dateFormatter?: (date: string) => string;
};

const defaultDateFormatter = (date: string) =>
  new Date(date).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });

/** Область под линией временного ряда — регистрации/прогоны по дням. */
export function TrendAreaChart({
  data,
  height = 220,
  valueFormatter,
  dateFormatter,
}: TrendAreaChartProps) {
  const { colors, axisColor, gridColor, tooltipBackground, tooltipBorder, tooltipText } =
    useChartTheme();
  // Свой id на инстанс: если на экране два таких графика (например, «Обзор»
  // админки — регистрации и прогоны рядом), общий id `<linearGradient>`
  // перезаписал бы заливку одного графика другим.
  const gradientId = useId();

  if (data.length === 0) {
    return <Text color="secondary">Данных нет.</Text>;
  }

  const format = valueFormatter ?? ((value: number) => value.toLocaleString("ru-RU"));
  const formatDate = dateFormatter ?? defaultDateFormatter;
  const color = colors[0];

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.35} />
            <stop offset="95%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="date"
          tickFormatter={formatDate}
          stroke={axisColor}
          tick={{ fill: axisColor, fontSize: 12 }}
          axisLine={{ stroke: gridColor }}
          tickLine={{ stroke: gridColor }}
          minTickGap={24}
        />
        <YAxis
          allowDecimals={false}
          stroke={axisColor}
          tick={{ fill: axisColor, fontSize: 12 }}
          axisLine={{ stroke: gridColor }}
          tickLine={{ stroke: gridColor }}
          width={40}
        />
        <Tooltip
          labelFormatter={(label) => formatDate(String(label))}
          formatter={(value) => format(Number(value))}
          contentStyle={{
            background: tooltipBackground,
            border: `1px solid ${tooltipBorder}`,
            borderRadius: 8,
          }}
          labelStyle={{ color: tooltipText }}
          itemStyle={{ color: tooltipText }}
        />
        <Area type="monotone" dataKey="count" stroke={color} fill={`url(#${gradientId})`} strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
