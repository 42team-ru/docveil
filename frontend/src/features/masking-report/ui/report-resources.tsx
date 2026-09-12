import { useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Grid } from "@astryxdesign/core/Grid";
import { List, ListItem } from "@astryxdesign/core/List";
import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { useTheme } from "@astryxdesign/core/theme";

import type {
  ConfidenceLevel,
  DecisionSource,
  MaskingReport,
  PiiSource,
  Telemetry,
} from "../../../entity/pii/model/types";
import type { RuntimeMetrics } from "../../masking-run/api/masking-run";
import { DECIDED_BY_LABEL } from "./report-table";

type ReportResourcesProps = {
  report: MaskingReport;
  runtime: RuntimeMetrics | null | undefined;
};

/** Стадии графа в порядке прохождения — используется, когда события не пришли. */
const STAGE_LABELS: Record<string, string> = {
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
const FALLBACK_ORDER = [
  "extract", "detect", "profile", "judge", "ask_human", "apply_answers",
  "policy", "plan", "summary", "image_export", "render", "validate",
  "report", "ask_review", "apply_review_edits", "finalize",
];

/** Стадии короче этого порога сворачиваются в одну строку — это шум, а не сигнал. */
const MINOR_STAGE_THRESHOLD_MS = 5;

/** Подпись слоя детекции — `PiiSource` из `masker.model.Source`. */
const SOURCE_LABELS: Record<PiiSource, string> = {
  rule: "Правила",
  ner: "Локальный NER (Natasha)",
  block: "Блоки реквизитов",
  llm: "Модель",
  user: "Свои типы",
};

/** Подпись уровня уверенности — порядок фиксирован (от надёжного к спорному). */
const LEVEL_LABELS: Record<ConfidenceLevel, string> = {
  confirmed: "Подтверждено",
  probable: "Вероятно",
  possible: "Похоже",
};
const LEVEL_ORDER: ConfidenceLevel[] = ["confirmed", "probable", "possible"];

/**
 * Смысловые слои конвейера — группировка узлов графа по назначению, а не по
 * имени. `detect` не разложен на правила/NER/GLiNER/LLM-арбитраж: движок
 * измеряет узел одним замером (`deps.llm_for_stage("detect")` вызывается
 * внутри него же), разбивку по слоям детекции должен дать бэкенд отдельной
 * задачей — здесь эта группа честно подписана как единое целое.
 */
const STAGE_LAYERS: { key: string; label: string; nodes: string[] }[] = [
  { key: "extract", label: "Извлечение", nodes: ["extract"] },
  {
    key: "detect",
    label: "Поиск данных (правила + NER + GLiNER + LLM-арбитраж вместе)",
    nodes: ["detect"],
  },
  {
    key: "decisions",
    label: "Профили, вопросы и план",
    nodes: [
      "profile", "judge", "policy", "ask_human", "apply_answers",
      "plan", "ask_review", "apply_review_edits",
    ],
  },
  { key: "summary", label: "Содержание (модель)", nodes: ["summary"] },
  { key: "render", label: "Рендер", nodes: ["render", "image_export"] },
  { key: "validate", label: "Проверка утечек", nodes: ["validate"] },
  { key: "report", label: "Отчёт и завершение", nodes: ["report", "finalize"] },
];

/**
 * Тариф GigaChat из `masker.yaml` (`llm.pricing`): ввод и вывод стоят по-разному
 * (0.289 ₽ за 1000 токенов вывода почти втрое дороже 0.096 ₽ за ввод), а
 * `report.json` отдаёт только итоговую сумму — разбивки по узлам в контракте нет.
 * Используем те же ставки, что и движок, только чтобы честно распределить уже
 * посчитанную им сумму между узлами графа; когда тариф не задан (`cost === null`),
 * эта оценка не считается вовсе — деньги не показываем.
 */
const PROMPT_RUB_PER_1K = 0.096;
const COMPLETION_RUB_PER_1K = 0.289;

const CHART_COLOR_TOKENS = [
  "--color-text-blue",
  "--color-text-teal",
  "--color-text-purple",
  "--color-text-orange",
  "--color-text-cyan",
  "--color-text-pink",
] as const;

type OrderedStage = { name: string; durationMs: number; order: number };

/** Один столбец категорийной диаграммы (источник / уровень / решение). */
type CategoryDatum = { key: string; label: string; count: number };

/**
 * Группирует счётчик по словарю подписей. С `order` держит заданный порядок
 * категорий (нужно для уровней уверенности — от надёжного к спорному) и
 * дописывает в конец всё, чего в порядке не было, а не молчит про него.
 * Без `order` сортирует по убыванию — так на диаграмме сверху самый частый
 * случай.
 */
function buildCategoryData(
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

/** Сколько ссылок решил каждый источник (`report.decisions.byRef[].decidedBy`). */
function countByDecidedBy(byRef: { decidedBy: DecisionSource }[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const decision of byRef) {
    counts[decision.decidedBy] = (counts[decision.decidedBy] ?? 0) + 1;
  }
  return counts;
}

/** Суммарная длительность узлов слоя — 0, если ни один узел слоя не измерен. */
function buildLayerData(runtime: RuntimeMetrics): CategoryDatum[] {
  const covered = new Set(STAGE_LAYERS.flatMap((layer) => layer.nodes));
  const layers = STAGE_LAYERS.map((layer) => ({
    key: layer.key,
    label: layer.label,
    count: layer.nodes.reduce((sum, node) => sum + (runtime.stages[node]?.duration_ms ?? 0), 0),
  }));
  const leftoverNodes = Object.keys(runtime.stages).filter((node) => !covered.has(node));
  const leftover = leftoverNodes.reduce((sum, node) => sum + (runtime.stages[node]?.duration_ms ?? 0), 0);
  return leftover > 0
    ? [...layers, { key: "other", label: "Прочее", count: leftover }].filter((item) => item.count > 0)
    : layers.filter((item) => item.count > 0);
}

/** Тело вкладки «Ресурсы»: сколько времени и денег стоил прогон и на что они ушли. */
export function ReportResources({ report, runtime }: ReportResourcesProps) {
  const telemetry = report.telemetry;
  const { token } = useTheme();
  const [showMinor, setShowMinor] = useState(false);

  if (!telemetry) {
    return (
      <EmptyState
        title="Метрики недоступны"
        description="Движок не записал телеметрию для этого прогона."
      />
    );
  }

  const totalTokens = telemetry.llm.promptTokens + telemetry.llm.completionTokens;
  const stages = runtime ? orderedStages(runtime, telemetry.events) : [];
  const visibleStages = stages.filter((stage) => stage.durationMs >= MINOR_STAGE_THRESHOLD_MS);
  const minorStages = stages.filter((stage) => stage.durationMs < MINOR_STAGE_THRESHOLD_MS);
  const totalDuration = stages.reduce((sum, stage) => sum + stage.durationMs, 0);
  const longest = visibleStages.reduce<OrderedStage | null>(
    (best, stage) => (!best || stage.durationMs > best.durationMs ? stage : best),
    null,
  );
  const cost = formatCost(telemetry.llm.cost);

  const sourceData = buildCategoryData(report.summary.bySource, SOURCE_LABELS);
  const levelData = buildCategoryData(report.summary.byLevel, LEVEL_LABELS, LEVEL_ORDER);
  const decidedByData = report.decisions
    ? buildCategoryData(countByDecidedBy(report.decisions.byRef), DECIDED_BY_LABEL)
    : [];
  const totalSource = Object.values(report.summary.bySource).reduce((sum, count) => sum + count, 0);
  const nonLlmShare = totalSource > 0
    ? Math.round(((totalSource - (report.summary.bySource.llm ?? 0)) / totalSource) * 100)
    : null;

  return (
    <VStack gap={5}>
      <Grid columns={{ minWidth: 180, max: 4, repeat: "fit" }} gap={3}>
        <MetricCard label="Общее время" value={runtime ? formatDuration(totalDuration) : "—"} />
        <MetricCard
          label="Дольше всего"
          value={longest ? stageTitle(longest.name) : "—"}
          note={longest ? formatDuration(longest.durationMs) : undefined}
        />
        <MetricCard
          label="Вызовов модели"
          value={String(telemetry.llm.calls)}
          note={telemetry.llm.calls === 0 ? "модель не понадобилась" : undefined}
        />
        {cost ? (
          <MetricCard label="Стоимость" value={cost} />
        ) : (
          <MetricCard label="Стоимость" value="—" note="тариф не задан" />
        )}
      </Grid>

      {runtime ? (
        <Section>
          <VStack gap={3}>
            <Heading level={4}>Конвейер по слоям</Heading>
            <CategoryBarChart
              data={buildLayerData(runtime)}
              colors={CHART_COLOR_TOKENS.map((name) => token(name))}
              axisColor={token("--color-text-secondary")}
              gridColor={token("--color-border")}
              tooltipBackground={token("--color-background-popover")}
              tooltipBorder={token("--color-border")}
              tooltipText={token("--color-text-primary")}
              valueFormatter={formatDuration}
            />
            <Text type="supporting" color="secondary">
              Поиск данных показан одним слоем: узел «detect» считает правила, локальный NER,
              GLiNER и LLM-арбитраж одним замером времени. Разбивку по этим слоям должен дать
              бэкенд отдельной задачей — сейчас таких данных в телеметрии нет.
            </Text>
          </VStack>
        </Section>
      ) : null}

      {runtime ? (
        <Section>
          <VStack gap={3}>
            <Heading level={4}>По узлам графа</Heading>
            <PipelineChart
              stages={visibleStages}
              accentColor={token("--color-text-blue")}
              axisColor={token("--color-text-secondary")}
              gridColor={token("--color-border")}
              tooltipBackground={token("--color-background-popover")}
              tooltipBorder={token("--color-border")}
              tooltipText={token("--color-text-primary")}
            />
            {minorStages.length > 0 ? (
              <VStack gap={2}>
                <Button
                  size="sm"
                  variant="ghost"
                  label={`${showMinor ? "Скрыть" : "Показать"} ещё ${minorStages.length} стадий, меньше ${MINOR_STAGE_THRESHOLD_MS} мс`}
                  onClick={() => setShowMinor((value) => !value)}
                />
                {showMinor ? (
                  <List hasDividers density="compact">
                    {minorStages.map((stage) => (
                      <ListItem
                        key={stage.name}
                        label={stageTitle(stage.name)}
                        endContent={<Text color="secondary">{formatDuration(stage.durationMs)}</Text>}
                      />
                    ))}
                  </List>
                ) : null}
              </VStack>
            ) : null}
          </VStack>
        </Section>
      ) : null}

      <Grid columns={{ minWidth: 260, max: 3, repeat: "fit" }} gap={4}>
        <Section>
          <VStack gap={3}>
            <Heading level={4}>Чем нашли</Heading>
            <CategoryBarChart
              data={sourceData}
              colors={CHART_COLOR_TOKENS.map((name) => token(name))}
              axisColor={token("--color-text-secondary")}
              gridColor={token("--color-border")}
              tooltipBackground={token("--color-background-popover")}
              tooltipBorder={token("--color-border")}
              tooltipText={token("--color-text-primary")}
            />
            {nonLlmShare !== null ? (
              <Text type="supporting" color="secondary">
                {`${nonLlmShare}% сущностей нашли правила и локальный NER без обращения к модели.`}
              </Text>
            ) : null}
          </VStack>
        </Section>
        <Section>
          <VStack gap={3}>
            <Heading level={4}>С какой уверенностью</Heading>
            <CategoryBarChart
              data={levelData}
              colors={CHART_COLOR_TOKENS.map((name) => token(name))}
              axisColor={token("--color-text-secondary")}
              gridColor={token("--color-border")}
              tooltipBackground={token("--color-background-popover")}
              tooltipBorder={token("--color-border")}
              tooltipText={token("--color-text-primary")}
            />
          </VStack>
        </Section>
        {decidedByData.length > 0 ? (
          <Section>
            <VStack gap={3}>
              <Heading level={4}>Кем принято решение</Heading>
              <CategoryBarChart
                data={decidedByData}
                colors={CHART_COLOR_TOKENS.map((name) => token(name))}
                axisColor={token("--color-text-secondary")}
                gridColor={token("--color-border")}
                tooltipBackground={token("--color-background-popover")}
                tooltipBorder={token("--color-border")}
                tooltipText={token("--color-text-primary")}
              />
            </VStack>
          </Section>
        ) : null}
      </Grid>

      {telemetry.llm.calls === 0 ? (
        <Banner
          status="info"
          title="Модель не понадобилась"
          description="Все решения для этого документа приняты без вызова языковой модели."
          collapsible={false}
        />
      ) : (
        <Grid columns={{ minWidth: 300, max: 2, repeat: "fit" }} gap={4}>
          <NodeCostChart
            telemetry={telemetry}
            colors={CHART_COLOR_TOKENS.map((name) => token(name))}
            mutedColor={token("--color-background-muted")}
            tooltipBackground={token("--color-background-popover")}
            tooltipBorder={token("--color-border")}
            tooltipText={token("--color-text-primary")}
          />
          <Section>
            <VStack gap={3}>
              <Heading level={4}>Расход модели</Heading>
              <List hasDividers>
                <ListItem
                  label={`Токены: ${totalTokens.toLocaleString("ru-RU")}`}
                  description={`Ввод: ${telemetry.llm.promptTokens.toLocaleString("ru-RU")}; вывод: ${telemetry.llm.completionTokens.toLocaleString("ru-RU")}`}
                />
                {/*
                  Диагностическое сообщение движка полезно, только пока нет
                  готовой суммы (например, объясняет, почему тариф не задан).
                  Когда сумма уже есть, оно лишь дублирует её с шестью знаками
                  после запятой и кодом валюты — карточка «Стоимость» выше уже
                  показывает то же число аккуратно.
                */}
                {telemetry.llm.cost === null ? <ListItem label={telemetry.llm.message} /> : null}
              </List>
            </VStack>
          </Section>
        </Grid>
      )}

      <ProcessingLog events={telemetry.events} runtime={runtime} unavailableNote={telemetry.runtime.note} />
    </VStack>
  );
}

function MetricCard({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <Card padding={4}>
      <VStack gap={1}>
        <Text type="supporting">{label}</Text>
        <Heading level={3}>{value}</Heading>
        {note ? <Text type="supporting" color="secondary">{note}</Text> : null}
      </VStack>
    </Card>
  );
}

type CategoryBarChartProps = {
  data: CategoryDatum[];
  colors: string[];
  axisColor: string;
  gridColor: string;
  tooltipBackground: string;
  tooltipBorder: string;
  tooltipText: string;
  valueFormatter?: (value: number) => string;
};

/** Горизонтальная диаграмма по категориям — источник, уверенность, решение. */
function CategoryBarChart({
  data,
  colors,
  axisColor,
  gridColor,
  tooltipBackground,
  tooltipBorder,
  tooltipText,
  valueFormatter,
}: CategoryBarChartProps) {
  if (data.length === 0) {
    return <Text color="secondary">Данных нет.</Text>;
  }
  const format = valueFormatter ?? ((value: number) => value.toLocaleString("ru-RU"));
  const chartData = data.map((item) => ({ name: item.label, count: item.count }));
  return (
    <ResponsiveContainer width="100%" height={Math.max(80, chartData.length * 36)}>
      <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 4 }}>
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
          width={170}
          stroke={axisColor}
          tick={{ fill: axisColor, fontSize: 12 }}
          axisLine={{ stroke: gridColor }}
          tickLine={false}
        />
        <Tooltip
          formatter={(value) => format(Number(value))}
          contentStyle={{ background: tooltipBackground, border: `1px solid ${tooltipBorder}`, borderRadius: 8 }}
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

type PipelineChartProps = {
  stages: OrderedStage[];
  accentColor: string;
  axisColor: string;
  gridColor: string;
  tooltipBackground: string;
  tooltipBorder: string;
  tooltipText: string;
};

/** Горизонтальный «водопад» по стадиям графа — доля времени видна на глаз. */
function PipelineChart({
  stages,
  accentColor,
  axisColor,
  gridColor,
  tooltipBackground,
  tooltipBorder,
  tooltipText,
}: PipelineChartProps) {
  if (stages.length === 0) {
    return <Text color="secondary">Заметных по времени стадий нет.</Text>;
  }
  const data = stages.map((stage) => ({ name: stageTitle(stage.name), durationMs: stage.durationMs }));
  return (
    <ResponsiveContainer width="100%" height={Math.max(120, data.length * 40)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 4 }}>
        <XAxis
          type="number"
          tickFormatter={(value: number) => formatDuration(value)}
          stroke={axisColor}
          tick={{ fill: axisColor, fontSize: 12 }}
          axisLine={{ stroke: gridColor }}
          tickLine={{ stroke: gridColor }}
        />
        <YAxis
          type="category"
          dataKey="name"
          width={140}
          stroke={axisColor}
          tick={{ fill: axisColor, fontSize: 12 }}
          axisLine={{ stroke: gridColor }}
          tickLine={false}
        />
        <Tooltip
          formatter={(value) => formatDuration(Number(value))}
          contentStyle={{ background: tooltipBackground, border: `1px solid ${tooltipBorder}`, borderRadius: 8 }}
          labelStyle={{ color: tooltipText }}
          itemStyle={{ color: tooltipText }}
          cursor={{ fill: gridColor, opacity: 0.4 }}
        />
        <Bar dataKey="durationMs" fill={accentColor} radius={[0, 4, 4, 0]} maxBarSize={24} />
      </BarChart>
    </ResponsiveContainer>
  );
}

type NodeCostChartProps = {
  telemetry: Telemetry;
  colors: string[];
  mutedColor: string;
  tooltipBackground: string;
  tooltipBorder: string;
  tooltipText: string;
};

type NodeSlice = { node: string; label: string; value: number; calls: number; promptTokens: number; completionTokens: number };

/**
 * Круговая по узлам графа. Когда тариф известен, откладываем оценённую
 * стоимость узла (в ₽, по ставкам движка) — так видно, какой узел ест деньги,
 * а не просто какой шлёт больше запросов. Без тарифа — честно откладываем
 * токены, деньги не придумываем.
 */
function NodeCostChart({ telemetry, colors, mutedColor, tooltipBackground, tooltipBorder, tooltipText }: NodeCostChartProps) {
  const byCost = telemetry.llm.cost !== null;
  const data: NodeSlice[] = telemetry.llm.byNode
    .map((item) => ({
      node: item.node,
      label: stageTitle(item.node),
      calls: item.calls,
      promptTokens: item.promptTokens,
      completionTokens: item.completionTokens,
      value: byCost
        ? estimateNodeCostRub(item.promptTokens, item.completionTokens)
        : item.promptTokens + item.completionTokens,
    }))
    .filter((item) => item.value > 0);
  const total = data.reduce((sum, item) => sum + item.value, 0);

  if (total === 0) {
    return (
      <Banner
        status="info"
        title="Расход по узлам недоступен"
        description="Поставщик не вернул разбивку токенов по этапам."
        collapsible={false}
      />
    );
  }

  return (
    <Section>
      <VStack gap={3}>
        <Heading level={4}>{byCost ? "Стоимость по узлам" : "Токены по узлам"}</Heading>
        <HStack gap={4} wrap="wrap" vAlign="center">
          <ResponsiveContainer width={180} height={180}>
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="label"
                innerRadius={48}
                outerRadius={80}
                paddingAngle={data.length > 1 ? 2 : 0}
                stroke={mutedColor}
              >
                {data.map((item, index) => (
                  <Cell key={item.node} fill={colors[index % colors.length]} />
                ))}
              </Pie>
              <Tooltip
                formatter={(value) => {
                  const numeric = Number(value);
                  return byCost ? formatRub(numeric) : numeric.toLocaleString("ru-RU");
                }}
                contentStyle={{ background: tooltipBackground, border: `1px solid ${tooltipBorder}`, borderRadius: 8 }}
                labelStyle={{ color: tooltipText }}
                itemStyle={{ color: tooltipText }}
              />
            </PieChart>
          </ResponsiveContainer>
          <StackItem size="fill">
            <List density="compact">
              {data.map((item, index) => (
                <ListItem
                  key={item.node}
                  label={`${item.label} · ${byCost ? formatRub(item.value) : `${item.value.toLocaleString("ru-RU")} ток.`}`}
                  description={`${item.calls} выз. · ввод ${item.promptTokens.toLocaleString("ru-RU")}, вывод ${item.completionTokens.toLocaleString("ru-RU")}`}
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
      </VStack>
    </Section>
  );
}

type ProcessingLogProps = {
  events: Telemetry["events"];
  runtime: RuntimeMetrics | null | undefined;
  /** `report.telemetry.runtime.note` — почему времени нет, если его нет. */
  unavailableNote: string;
};

/**
 * Лента обработки — что, в каком узле и через сколько времени от старта
 * произошло. Сообщения берутся из `report.telemetry.events` (они есть
 * всегда), время от старта — из `runtime.events[].elapsed_ms`, недетерминиро­
 * ванного companion-артефакта; без него лог остаётся без времени, а не
 * выдумывает его.
 */
function ProcessingLog({ events, runtime, unavailableNote }: ProcessingLogProps) {
  const elapsedBySequence = new Map(
    (runtime?.events ?? []).map((event) => [event.sequence, event.elapsed_ms]),
  );

  return (
    <Section>
      <VStack gap={3}>
        <List hasDividers header={<Heading level={4}>Журнал обработки</Heading>}>
          {events.map((event) => {
            const elapsed = elapsedBySequence.get(event.sequence);
            return (
              <ListItem
                key={event.sequence}
                label={event.message}
                description={stageTitle(event.node)}
                endContent={
                  elapsed !== undefined ? (
                    <Text hasTabularNumbers color="secondary">{formatDuration(elapsed)}</Text>
                  ) : undefined
                }
              />
            );
          })}
        </List>
        {!runtime ? (
          <Text type="supporting" color="secondary">
            {unavailableNote || "Время каждого шага недоступно — движок не записал длительности для этого прогона."}
          </Text>
        ) : null}
      </VStack>
    </Section>
  );
}

function orderedStages(runtime: RuntimeMetrics, events: Telemetry["events"]): OrderedStage[] {
  const eventOrder = new Map(events.map((event) => [event.node, event.sequence]));
  return Object.entries(runtime.stages)
    .map(([name, value]) => ({
      name,
      durationMs: value.duration_ms,
      order: eventOrder.get(name) ?? 10_000 + Math.max(0, FALLBACK_ORDER.indexOf(name)),
    }))
    .sort((left, right) => left.order - right.order);
}

function stageTitle(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

/** Оценка стоимости узла в рублях по ставкам `llm.pricing` из `masker.yaml`. */
function estimateNodeCostRub(promptTokens: number, completionTokens: number): number {
  return (promptTokens / 1000) * PROMPT_RUB_PER_1K + (completionTokens / 1000) * COMPLETION_RUB_PER_1K;
}

function formatRub(amount: number): string {
  return `${amount.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽`;
}

function formatCost(cost: Record<string, unknown> | null): string | null {
  if (!cost || typeof cost.amount !== "string") return null;
  const amount = Number(cost.amount);
  if (!Number.isFinite(amount)) return null;
  if (cost.currency === "RUB") return formatRub(amount);
  return `${amount.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${String(cost.currency ?? "")}`;
}

function formatDuration(milliseconds: number): string {
  return milliseconds >= 1000 ? `${(milliseconds / 1000).toFixed(1)} с` : `${Math.round(milliseconds)} мс`;
}
