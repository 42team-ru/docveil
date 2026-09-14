import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { List, ListItem } from "@astryxdesign/core/List";
import { HStack, StackItem } from "@astryxdesign/core/Stack";

import { useChartTheme } from "./chart-theme";

export type DonutDatum = {
  key: string;
  label: string;
  value: number;
  /** Вторая строка легенды — детали слайса (например, «12 выз. · ввод …»). */
  description?: string;
};

type DonutChartProps = {
  data: DonutDatum[];
  valueFormatter?: (value: number) => string;
  /** Сторона квадрата под диаграмму, px. */
  size?: number;
};

/** Кольцевая диаграмма долей + компактная легенда рядом — вынесено из
 * `masking-report/ui/report-resources.tsx` (там была только диаграмма
 * стоимости LLM по узлам); годится для любых долей — статусов, форматов,
 * стилей маскирования. */
export function DonutChart({ data, valueFormatter, size = 180 }: DonutChartProps) {
  const { colors, mutedColor, tooltipBackground, tooltipBorder, tooltipText } =
    useChartTheme();
  const format = valueFormatter ?? ((value: number) => value.toLocaleString("ru-RU"));

  return (
    <HStack gap={4} wrap="wrap" vAlign="center">
      <ResponsiveContainer width={size} height={size}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
            innerRadius={size * 0.267}
            outerRadius={size * 0.444}
            paddingAngle={data.length > 1 ? 2 : 0}
            stroke={mutedColor}
          >
            {data.map((item, index) => (
              <Cell key={item.key} fill={colors[index % colors.length]} />
            ))}
          </Pie>
          <Tooltip
            formatter={(value) => format(Number(value))}
            contentStyle={{
              background: tooltipBackground,
              border: `1px solid ${tooltipBorder}`,
              borderRadius: 8,
            }}
            labelStyle={{ color: tooltipText }}
            itemStyle={{ color: tooltipText }}
          />
        </PieChart>
      </ResponsiveContainer>
      <StackItem size="fill">
        <List density="compact">
          {data.map((item, index) => (
            <ListItem
              key={item.key}
              label={`${item.label} · ${format(item.value)}`}
              description={item.description}
              startContent={
                <svg aria-hidden="true" width="12" height="12">
                  <circle cx="6" cy="6" r="5" fill={colors[index % colors.length]} />
                </svg>
              }
            />
          ))}
        </List>
      </StackItem>
    </HStack>
  );
}
