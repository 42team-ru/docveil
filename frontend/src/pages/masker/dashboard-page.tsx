import { useNavigate } from "react-router";
import { ArrowRight, CheckCircle2, FileClock, Files } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Grid } from "@astryxdesign/core/Grid";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { Icon } from "@astryxdesign/core/Icon";
import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";

import type { RunListItem } from "../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { formatMoment } from "../../shared/lib/format-moment";
import { pluralRu } from "../../shared/lib/plural-ru";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";
import { useRunList } from "../../features/masking-run/api/masking-run";
import { RunStatusToken } from "../../entity/document/ui/run-status-token";
import "./dashboard-page.css";

const LIST_SIZE = 5;

function SummaryCard({
  label,
  count,
  note,
  icon,
}: {
  label: string;
  count: number | null;
  note: string;
  icon: typeof Files;
}) {
  return (
    <Card padding={4} className="min-w-0">
      <HStack gap={3} vAlign="start">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-default bg-muted text-secondary">
          <Icon icon={icon} size="md" />
        </span>
        <VStack gap={1} className="min-w-0">
          <Text type="supporting" color="secondary">{label}</Text>
          <Heading level={2}>
            {count === null ? "—" : `${count} ${pluralRu(count, ["документ", "документа", "документов"])}`}
          </Heading>
          <Text type="supporting" color="secondary" textWrap="pretty">{note}</Text>
        </VStack>
      </HStack>
    </Card>
  );
}

function eventTitle(status: RunListItem["status"]): string {
  switch (status) {
    case "queued": return "Документ поставлен в очередь";
    case "running": return "Документ обрабатывается";
    case "awaiting_answers": return "Нужны ответы оператора";
    case "awaiting_review": return "Ожидает завершения проверки";
    case "done": return "Обезличивание завершено";
    case "leaked": return "Проверка утечек не пройдена";
    case "failed": return "Обработка завершилась ошибкой";
    case "cancelled": return "Обработка отменена";
  }
}

function openLabel(status: RunListItem["status"]): string {
  if (status === "awaiting_review") return "Продолжить проверку";
  if (status === "done") return "Открыть результат";
  return "Открыть документ";
}

function openRun(run: RunListItem, navigate: ReturnType<typeof useNavigate>) {
  const suffix = run.status === "done" ? "?tab=report" : "";
  void navigate(`/documents/${run.id}${suffix}`, { viewTransition: true });
}

function RunRows({ runs, navigate, mode }: {
  runs: RunListItem[];
  navigate: ReturnType<typeof useNavigate>;
  mode: "activity" | "review" | "done";
}) {
  const isNarrow = useMediaQuery("(max-width: 600px)", false);
  if (runs.length === 0) {
    const title = mode === "review"
      ? "Проверок не ожидается"
      : mode === "done"
        ? "Готовых документов пока нет"
        : "Действий пока нет";
    const description = mode === "review"
      ? "Документы появятся здесь, когда будут ждать вашего решения."
      : mode === "done"
        ? "Завершённые обработки появятся здесь."
        : "Запустите обработку документа, чтобы увидеть её состояние здесь.";
    return <EmptyState isCompact title={title} description={description} />;
  }

  return (
    <VStack gap={0}>
      {runs.map((run) => (
        <HStack
          key={run.id}
          as="article"
          gap={3}
          vAlign="center"
          wrap={isNarrow ? "wrap" : "nowrap"}
          padding={3}
          width="100%"
          className="dashboard-run-row"
        >
          <StackItem size="fill" className={isNarrow ? "min-w-0 w-full" : "min-w-0"}>
            <VStack gap={1} className="min-w-0">
              <Text weight="medium" textWrap="pretty">{run.document.name}</Text>
              <HStack gap={2} wrap="wrap" vAlign="center">
                <RunStatusToken status={run.status} />
                <Text type="supporting" color="secondary" size="sm">
                  {formatMoment(run.finished_at ?? run.created_at)}
                </Text>
              </HStack>
              {mode === "activity" ? (
                <Text type="supporting" color="secondary" textWrap="pretty">
                  {eventTitle(run.status)}
                </Text>
              ) : null}
            </VStack>
          </StackItem>
          <Button
            size="sm"
            variant={mode === "review" ? "primary" : "secondary"}
            label={openLabel(run.status)}
            onClick={() => openRun(run, navigate)}
          />
        </HStack>
      ))}
    </VStack>
  );
}

function RunSection({ title, subtitle, runs, navigate, mode, onShowAll }: {
  title: string;
  subtitle: string;
  runs: ReturnType<typeof useRunList>;
  navigate: ReturnType<typeof useNavigate>;
  mode: "activity" | "review" | "done";
  onShowAll?: () => void;
}) {
  return (
    <Card padding={0}>
      <VStack gap={0}>
        <HStack gap={3} vAlign="center" padding={4} wrap="wrap">
          <StackItem size="fill">
            <VStack gap={1}>
              <Heading level={4}>{title}</Heading>
              <Text type="supporting" color="secondary">{subtitle}</Text>
            </VStack>
          </StackItem>
          {onShowAll ? (
            <Button
              size="sm"
              variant="ghost"
              label="Все документы"
              icon={<Icon icon={ArrowRight} size="sm" />}
              onClick={onShowAll}
            />
          ) : null}
        </HStack>
        {runs.isLoading ? (
          <Section padding={4}>
            <div className="h-36 animate-pulse rounded-lg bg-muted" />
          </Section>
        ) : runs.isError || !runs.data ? (
          <EmptyState
            isCompact
            title="Список недоступен"
            description="Обновите страницу или откройте журнал документов."
            actions={<Button size="sm" variant="secondary" label="Журнал документов" onClick={() => void navigate("/documents")} />}
          />
        ) : (
          <RunRows runs={runs.data.items} navigate={navigate} mode={mode} />
        )}
      </VStack>
    </Card>
  );
}

/** Рабочий стол собирает только состояния из журнала текущего аккаунта. */
export function DashboardPage() {
  const navigate = useNavigate();
  const reviewRuns = useRunList({ status: "awaiting_review", limit: LIST_SIZE });
  const completedRuns = useRunList({ status: "done", limit: LIST_SIZE });
  const recentRuns = useRunList({ limit: LIST_SIZE });

  return (
    <ScreenLayout title="Рабочий стол">
      <VStack gap={5}>
        <Grid columns={{ minWidth: 240, max: 2, repeat: "fit" }} gap={4}>
          <SummaryCard
            label="Нужно проверить"
            count={reviewRuns.isError ? null : reviewRuns.data?.total ?? null}
            note="Документы, которые ждут решения оператора."
            icon={FileClock}
          />
          <SummaryCard
            label="Готово к скачиванию"
            count={completedRuns.isError ? null : completedRuns.data?.total ?? null}
            note="Обезличивание завершено, результат можно открыть."
            icon={CheckCircle2}
          />
        </Grid>

        <Grid columns={{ minWidth: 280, max: 2, repeat: "fit" }} gap={4}>
          <RunSection
            title="Требуют проверки"
            subtitle="Сначала — документы, ожидающие вашего решения."
            runs={reviewRuns}
            navigate={navigate}
            mode="review"
            onShowAll={() => void navigate("/documents")}
          />
          <RunSection
            title="Недавние действия"
            subtitle="Состояния последних прогонов из журнала документов."
            runs={recentRuns}
            navigate={navigate}
            mode="activity"
            onShowAll={() => void navigate("/documents")}
          />
        </Grid>

        <RunSection
          title="Готовы к скачиванию"
          subtitle="Завершённые документы можно открыть на вкладке отчёта."
          runs={completedRuns}
          navigate={navigate}
          mode="done"
          onShowAll={() => void navigate("/documents")}
        />
      </VStack>
    </ScreenLayout>
  );
}
