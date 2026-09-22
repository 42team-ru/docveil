import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { CheckCircle2, Download, FileBarChart2, ListChecks } from "lucide-react";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { HStack } from "@astryxdesign/core/Stack";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Text } from "@astryxdesign/core/Text";
import { useToast } from "@astryxdesign/core/Toast";

import type { DocumentFormat } from "../../entity/document/model/types";
import { FormatToken } from "../../entity/document/ui/format-token";
import { flattenPiiOccurrences } from "../../entity/pii/model/flatten";
import { buildReviewEdits } from "../../entity/pii/model/review-edits";
import { useReviewStore } from "../../entity/pii/model/review-store";
import {
  useConfirmedGroupCount,
  useTotalGroupCount,
} from "../../entity/pii/model/selectors";
import {
  downloadArtifact,
  hasRunResult,
  isRunPending,
  runKeys,
  useRegenerateReview,
  useRunProgress,
  useSubmitReview,
} from "../../features/masking-run/api/masking-run";
import { useReviewData } from "../../features/pii-review/api/use-review-data";
import { ReviewPanel } from "../../features/pii-review/ui/review-panel";
import { MaskingSetupDialog } from "../../features/pii-review/ui/masking-setup-dialog";
import { UploadSelectionDialog } from "../../features/document-upload/ui/upload-selection-dialog";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";
import { ReportView } from "./report-view";
import { ReviewView } from "./review-view";

type DocumentTab = "review" | "report";

/**
 * Один и тот же контейнер тела экрана — под ним каждый раз оказывается
 * либо `ReviewView`, либо `ReportView`. `aria-controls` таба указывает сюда
 * же вне зависимости от выбора: это правда то тело, которое таб переключает.
 */
const CONTENT_PANEL_ID = "document-tab-panel";

/**
 * Ширина отчёта на широком мониторе: колонки текста и карточек читаются
 * глазами без прокрутки взглядом через весь экран. Вкладка «Проверка» этот
 * предел не получает — там документ с боковой панелью честно занимает всю
 * доступную ширину.
 */
const REPORT_CONTENT_WIDTH = 1200;

/**
 * Рабочий стол документа: проверка и отчёт делят одну шапку и панель,
 * переключение — таб в шапке, а не переход по страницам. Документ и его
 * `blob:`-ссылка (`useReviewData`) читаются один раз здесь, а не в каждой
 * вкладке — поэтому смена таба не перекачивает файл заново.
 */
export function DocumentPage() {
  const { runId: routeRunId } = useParams<"runId">();
  const runId = routeRunId ?? null;
  const navigate = useNavigate();
  const location = useLocation();
  const uploadIds: string[] = location.state?.uploadIds ?? [];
  const chooseUpload = location.state?.chooseUpload === true && uploadIds.length > 1;
  const showToast = useToast();

  const [searchParams, setSearchParams] = useSearchParams();
  const tab: DocumentTab = searchParams.get("tab") === "report" ? "report" : "review";

  const {
    status,
    artifactRevision,
    extraction,
    document: reviewedDocument,
    report,
    ask,
    isLoading,
    error,
  } = useReviewData(runId);

  const [selectedTypesRunId, setSelectedTypesRunId] = useState<string | null>(null);
  const progress = useRunProgress(runId, isRunPending(status));
  useEffect(() => {
    useReviewStore.setState({ questionAnswers: {} });
  }, [runId]);
  const isSelectingTypes = selectedTypesRunId !== runId && Boolean(ask?.questions.some((question) => question.kind === "type"));

  const [notFoundIds, setNotFoundIds] = useState<Set<string>>(new Set());
  const [isConfirmApproveOpen, setIsConfirmApproveOpen] = useState(false);
  const [regenerationRevision, setRegenerationRevision] = useState<number | null>(null);
  const [isDownloading, setIsDownloading] = useState(false);

  const setDocumentGroups = useReviewStore((state) => state.setDocumentGroups);
  const hasUnappliedChanges = useReviewStore((state) =>
    Object.keys(state.groupDecisions).length > 0
      || Object.keys(state.occurrenceDecisions).length > 0
      || Object.keys(state.typeOverrides).length > 0
      || Object.keys(state.occurrenceTypeOverrides).length > 0
      || state.manualOccurrences.length > 0,
  );
  const confirmedCount = useConfirmedGroupCount();
  const totalCount = useTotalGroupCount();
  const allConfirmed = confirmedCount === totalCount;

  const occurrences = useMemo(() => flattenPiiOccurrences(extraction), [extraction]);

  // Счётчики проверки живут в сторе и должны считать по открытому документу,
  // а не по фикстуре, и одинаково — на вкладках «Проверка» и «Отчёт».
  const documentGroups = useMemo(() => {
    const groups = new Map<
      string,
      {
        minConfidence: number;
        appliedDecision: "confirmed" | "rejected";
        appliedOccurrenceDecisions: Record<string, "confirmed" | "rejected">;
      }
    >();
    for (const occurrence of occurrences) {
      const known = groups.get(occurrence.groupId);
      groups.set(occurrence.groupId, {
        minConfidence: known === undefined
          ? occurrence.confidence
          : Math.min(known.minConfidence, occurrence.confidence),
        appliedDecision:
          known === undefined
            ? occurrence.action === "keep"
              ? "rejected"
              : "confirmed"
            : known.appliedDecision === "rejected" && occurrence.action === "keep"
              ? "rejected"
              : "confirmed",
        appliedOccurrenceDecisions: {
          ...known?.appliedOccurrenceDecisions,
          [occurrence.id]: occurrence.action === "keep" ? "rejected" : "confirmed",
        },
      });
    }
    return [...groups].map(([id, group]) => ({
      id,
      minConfidence: group.minConfidence,
      appliedDecision: group.appliedDecision,
      appliedOccurrenceDecisions: group.appliedOccurrenceDecisions,
    }));
  }, [occurrences]);

  useEffect(() => {
    if (runId !== null) setDocumentGroups(`${runId}:${artifactRevision}`, documentGroups);
  }, [artifactRevision, documentGroups, runId, setDocumentGroups]);

  const ready = hasRunResult(status);
  const submitReview = useSubmitReview(runId);
  const regenerateReview = useRegenerateReview(runId);
  const isRegenerating = regenerationRevision !== null;
  const queryClient = useQueryClient();

  useEffect(() => {
    if (
      regenerationRevision !== null
      && status === "awaiting_review"
      && artifactRevision >= regenerationRevision
      && reviewedDocument.fileUrl
    ) {
      setRegenerationRevision(null);
      showToast({ body: "Файл перегенерирован с вашими изменениями", type: "info" });
      // `useRegenerateReview` инвалидирует отчёт сразу на 202 — граф тогда
      // только встал в очередь, новых замен в отчёте ещё нет. Настоящий
      // отчёт готов только теперь, когда прогон вернулся на `awaiting_review`
      // с нужной ревизией — без повторной инвалидации здесь панель «Замены»
      // остаётся на старом списке до перезагрузки страницы.
      if (runId !== null) {
        void queryClient.invalidateQueries({ queryKey: runKeys.report(runId) });
        void queryClient.invalidateQueries({ queryKey: runKeys.artifacts(runId) });
      }
    }
  }, [artifactRevision, queryClient, regenerationRevision, reviewedDocument.fileUrl, runId, showToast, status]);

  /**
   * Утверждение документа. Правки уходят вторым прерыванием в граф, и
   * документ пересобирается там же — интерфейс ничего не «применяет» сам,
   * поэтому маркеры остаются согласованными, а результат заново проверяется
   * на утечки. Кнопка только открывает диалог подтверждения — сам запрос
   * уходит из `onAction` диалога.
   */
  function handleApprove() {
    const state = useReviewStore.getState();
    submitReview.mutate(buildReviewEdits(extraction, state), {
      onSuccess: () => {
        setIsConfirmApproveOpen(false);
        showToast({
          body: "Правки приняты: документ пересобирается с ними",
          type: "info",
        });
      },
      onError: () => {
        setIsConfirmApproveOpen(false);
        showToast({
          body: "Прогон уже не ждёт правок — обновите страницу",
          type: "error",
        });
      },
    });
  }

  function handleRegenerate() {
    if (runId === null || isRegenerating) return;
    const expectedRevision = artifactRevision;
    setRegenerationRevision(expectedRevision + 1);
    regenerateReview.mutate(
      {
        edits: buildReviewEdits(extraction, useReviewStore.getState()),
        expectedRevision,
      },
      {
        onError: (mutationError) => {
          setRegenerationRevision(null);
          showToast({ body: mutationError.message || "Не удалось перегенерировать файл", type: "error" });
        },
      },
    );
  }

  /** Скачивает подсвеченный вариант — тот же файл, что открыт во вьюере. */
  async function handleDownload() {
    if (runId === null) return;
    setIsDownloading(true);
    try {
      await downloadArtifact(runId, "masked_highlight", reviewedDocument.name);
      showToast({ body: "Обезличенный документ скачан", type: "info" });
    } catch {
      showToast({ body: "Не удалось скачать обезличенный документ", type: "error" });
    } finally {
      setIsDownloading(false);
    }
  }

  if (runId === null) {
    return (
      <ScreenLayout title="Документ">
        <EmptyState
          title="Прогон не найден"
          description="Ссылка на документ неверна. Вернитесь в журнал и откройте документ заново."
          actions={
            <Button
              variant="primary"
              label="К документам"
              onClick={() => navigate("/documents", { viewTransition: true })}
            />
          }
        />
      </ScreenLayout>
    );
  }

  return (
    <>
      <ScreenLayout
        title={reviewedDocument.name}
        startContent={
          <FormatToken format={reviewedDocument.format.toUpperCase() as DocumentFormat} />
        }
        meta={
          tab === "review" ? (
            <Badge
              variant={ready ? "success" : "neutral"}
              label={`${confirmedCount}/${totalCount} подтверждено`}
            />
          ) : report ? (
            <HStack gap={2} vAlign="center">
              <Text type="supporting" color="secondary">
                {report.decisions?.mode === "interactive"
                  ? "с ответами оператора"
                  : "без вопросов оператору"}
              </Text>
            </HStack>
          ) : undefined
        }
        tabs={
          <TabList
            value={tab}
            onChange={(value) =>
              setSearchParams(
                (params) => {
                  const next = new URLSearchParams(params);
                  if (value === "report") next.set("tab", "report");
                  else next.delete("tab");
                  return next;
                },
                { replace: true },
              )
            }
            // Таб меняет тело экрана на месте, а не переходит по странице —
            // это настоящий tablist-паттерн, а не навигация: иконки и роль
            // делают это видно сразу, а не только по URL.
            role="tablist"
            size="sm"
          >
            <Tab
              value="review"
              label="Проверка"
              icon={<Icon icon={ListChecks} size="sm" />}
              panelId={CONTENT_PANEL_ID}
            />
            <Tab
              value="report"
              label="Отчёт"
              icon={<Icon icon={FileBarChart2} size="sm" />}
              panelId={CONTENT_PANEL_ID}
            />
          </TabList>
        }
        actions={
          tab === "review" ? (
            <HStack gap={2}>
              {uploadIds.length > 1 ? <Button size="sm" variant="ghost" label="Выбрать файл"
                onClick={() => void navigate(location.pathname, { replace: true, state: { uploadIds, chooseUpload: true } })} /> : null}
              <Button
                size="sm"
                variant={ready ? "primary" : "secondary"}
                label="Скачать обезличенный документ"
                icon={<Icon icon={Download} size="sm" />}
                isDisabled={!ready || hasUnappliedChanges || isRegenerating || isDownloading}
                isLoading={isDownloading}
                onClick={() => void handleDownload()}
              />
              <Button
                size="sm"
                variant="secondary"
                label="Завершить проверку"
                icon={<Icon icon={CheckCircle2} size="sm" />}
                isDisabled={status !== "awaiting_review" || submitReview.isPending || hasUnappliedChanges || isRegenerating}
                isLoading={submitReview.isPending}
                onClick={() => setIsConfirmApproveOpen(true)}
              />
            </HStack>
          ) : null
        }
        contentId={CONTENT_PANEL_ID}
        contentPadding={tab === "review" ? 0 : 6}
        isContentScrollable={tab !== "review"}
        contentWidth={tab === "report" ? REPORT_CONTENT_WIDTH : undefined}
        panel={
          tab === "review" ? (
            <ReviewPanel
              extraction={extraction}
              report={report}
              ask={ask}
              runId={runId}
              totalCount={totalCount}
              notFoundIds={notFoundIds}
              isEditingDisabled={isRegenerating}
            />
          ) : undefined
        }
      >
        {tab === "review" ? (
          <ReviewView
            document={reviewedDocument}
            extraction={extraction}
            occurrences={occurrences}
            pages={report?.pages ?? []}
            hasUnappliedChanges={hasUnappliedChanges}
            isRegenerating={isRegenerating}
            onRegenerate={handleRegenerate}
            onNotFoundChange={setNotFoundIds}
          />
        ) : (
          <ReportView report={report} runId={runId} />
        )}
      </ScreenLayout>
      <MaskingSetupDialog
        key={runId}
        runId={runId}
        ask={ask}
        isSelecting={!chooseUpload && isSelectingTypes}
        isProcessing={!chooseUpload && !isRegenerating && (isRunPending(status) || isLoading)}
        error={chooseUpload ? null : error}
        progress={progress.events}
        isProgressUnavailable={progress.isUnavailable}
        onSelected={() => setSelectedTypesRunId(runId)}
        onLeave={() => void navigate(uploadIds.length > 1 ? location.pathname : "/documents", {
          replace: uploadIds.length > 1,
          state: uploadIds.length > 1 ? { uploadIds, chooseUpload: true } : undefined,
          // Настоящий переход только когда уходим на /documents — открытие
          // диалога выбора файла на том же пути не должно триггерить снимок
          // всей страницы.
          viewTransition: uploadIds.length <= 1,
        })}
      />
      <UploadSelectionDialog
        isOpen={chooseUpload}
        uploadIds={uploadIds}
        onSelect={(id) => void navigate(`/documents/${id}`, {
          replace: true,
          state: { uploadIds, chooseUpload: false },
          viewTransition: true,
        })}
        onLeave={() => void navigate("/", { viewTransition: true })}
      />
      <AlertDialog
        isOpen={isConfirmApproveOpen}
        onOpenChange={setIsConfirmApproveOpen}
        title="Утвердить документ?"
        description={
          allConfirmed
            ? "Документ пересоберётся и проверка будет завершена."
            // Кнопка открытия этого диалога недоступна, пока есть
            // неприменённые правки, — если мы здесь, allConfirmed < totalCount
            // означает не незавершённость, а то, что часть находок оставлена
            // как есть намеренно (решение «оставить»).
            : `${confirmedCount} из ${totalCount} находок будут заменены на маркер, остальные — оставлены как есть по вашему решению. Документ пересоберётся с учётом этого.`
        }
        actionLabel="Утвердить"
        actionVariant="primary"
        isActionLoading={submitReview.isPending}
        onAction={handleApprove}
      />
    </>
  );
}
