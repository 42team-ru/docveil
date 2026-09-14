import { useTheme } from "@astryxdesign/core/theme";

/**
 * Палитра графиков — токены темы, а не hex (правило AGENTS.md: «Tokens for
 * every value»). Шесть цветов хватает на любую категорийную диаграмму в
 * продукте — источники PII, статусы прогонов, форматы документов и т.д.;
 * при большем числе категорий цикл переиспользует их по кругу.
 */
export const CHART_COLOR_TOKENS = [
  "--color-text-blue",
  "--color-text-teal",
  "--color-text-purple",
  "--color-text-orange",
  "--color-text-cyan",
  "--color-text-pink",
] as const;

export type ChartTheme = {
  colors: string[];
  axisColor: string;
  gridColor: string;
  mutedColor: string;
  tooltipBackground: string;
  tooltipBorder: string;
  tooltipText: string;
};

/** Единая точка получения цветов для recharts — раньше каждый чарт в
 * `masking-report/ui/report-resources.tsx` дёргал `useTheme().token(...)`
 * по шесть раз сам. */
export function useChartTheme(): ChartTheme {
  const { token } = useTheme();
  return {
    colors: CHART_COLOR_TOKENS.map((name) => token(name)),
    axisColor: token("--color-text-secondary"),
    gridColor: token("--color-border"),
    mutedColor: token("--color-background-muted"),
    tooltipBackground: token("--color-background-popover"),
    tooltipBorder: token("--color-border"),
    tooltipText: token("--color-text-primary"),
  };
}
