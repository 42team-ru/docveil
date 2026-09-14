import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Text } from "@astryxdesign/core/Text";

import { useChartTheme } from "./chart-theme";

/** Один столбец категорийной диаграммы (источник / уровень / статус / формат). */
export type CategoryDatum = { key: string; label: string; count: number };

/**
 * Группирует счётчик по словарю подписей. С `order` держит заданный порядок
 * категорий (нужно, например, для уровней уверенности — от надёжного к
 * спорному) и дописывает в конец всё, чего в порядке не было, а не молчит
 * про него. Без `order` сортирует по убыванию — так на диаграмме сверху
 * самый частый случай.
 */
export function buildCategoryData(
  counts: Record<string, number>,
  labels: Record<string, string>,
  order?: string[],
): CategoryDatum[] {
  const keys = order
    ? [...order, ...Object.keys(counts).filter((key) => !order.includes(key))]
    : Object.keys(counts).sort((a, b) => (counts[b] ?? 0) - (counts[a] ?? 0));
  return keys
    .map((key) => ({ key, label: labels[key] ?? key, count: counts[key] ?? 0 }))
    .filter((item) => item.count > 0);
}

type CategoryBarChartProps = {
  data: CategoryDatum[];
  valueFormatter?: (value: number) => string;
  /** Явно задать высоту контейнера (px) — нужно чтобы несколько чартов стояли ровно. */
  fixedHeight?: number;
};

/** Горизонтальная диаграмма по категориям — источник, уверенность, статус, формат. */
export function CategoryBarChart({
  data,
  valueFormatter,
  fixedHeight,
}: CategoryBarChartProps) {
  const { colors, axisColor, gridColor, tooltipBackground, tooltipBorder, tooltipText } =
    useChartTheme();

  if (data.length === 0) {
    return <Text color="secondary">Данных нет.</Text>;
  }
  const format =
    valueFormatter ?? ((value: number) => value.toLocaleString("ru-RU"));
  const chartData = data.map((item) => ({
    name: item.label,
    count: item.count,
  }));
  const maxLabelLength = chartData.reduce(
    (max, d) => Math.max(max, d.name.length),
    0,
  );
  const yAxisWidth = Math.min(280, Math.max(120, maxLabelLength * 7));
  const height = fixedHeight ?? Math.max(96, chartData.length * 44);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={chartData}
        layout="vertical"
        margin={{ top: 4, right: 24, bottom: 4, left: 4 }}
      >
        <XAxis
          type="number"
          allowDecimals={false}
          tickFormatter={format}
          stroke={axisColor}
          tick={{ fill: axisColor, fontSize: 12 }}
          axisLine={{ stroke: gridColor }}
          tickLine={{ stroke: gridColor }}
        />
        <YAxis
          type="category"
          dataKey="name"
          width={yAxisWidth}
          interval={0}
          stroke={axisColor}
          tick={{ fill: axisColor, fontSize: 12 }}
          axisLine={{ stroke: gridColor }}
          tickLine={false}
        />
        <Tooltip
          formatter={(value) => format(Number(value))}
          contentStyle={{
            background: tooltipBackground,
            border: `1px solid ${tooltipBorder}`,
            borderRadius: 8,
          }}
          labelStyle={{ color: tooltipText }}
          itemStyle={{ color: tooltipText }}
          cursor={{ fill: gridColor, opacity: 0.4 }}
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={22}>
          {chartData.map((entry, index) => (
            <Cell key={entry.name} fill={colors[index % colors.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
