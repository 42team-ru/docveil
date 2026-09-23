import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { CheckCircle2, Download, FileBarChart2, ListChecks } from "lucide-react";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { Layout, LayoutContent, LayoutHeader } from "@astryxdesign/core/Layout";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Heading, Text } from "@astryxdesign/core/Text";
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
  hasReadyArtifactForDownload,
  hasRunResult,
  isRunFinished,
  isRunPending,
  runKeys,
  useRegenerateReview,
  useRunProgress,
  useSubmitReview,
} from "../../features/masking-run/api/masking-run";
import { useReviewData } from "../../features/pii-review/api/use-review-data";
import { ReviewPanel } from "../../features/pii-review/ui/review-panel";
import {
  canStartReviewSubmission,
  reviewConfirmationDescription,
  shouldShowReviewFinish,
} from "../../features/pii-review/lib/review-lifecycle";
import { MaskingSetupDialog } from "../../features/pii-review/ui/masking-setup-dialog";
import { UploadSelectionDialog } from "../../features/document-upload/ui/upload-selection-dialog";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";
import { maskedOccurrences } from "../../features/masking-report/lib/report-occurrences";
import { pluralRu } from "../../shared/lib/plural-ru";
import { ReportView } from "./report-view";
import { ReviewView } from "./review-view";

type DocumentTab = "result" | "review" | "report";

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
 * Ширина карточки «Документ готов»: это три строки текста и две кнопки, а
 * не таблица. Задаётся самой карточке (`width`/`maxWidth`), а не через
 * `contentWidth` экрана — тот центрирует блок «шапка+тело+панель» целиком, а
 * не отдельно взятую карточку внутри тела, и с одной вкладкой без панели
 * карточка просто прижималась к левому краю вместо центра. Центрирует
 * оборачивающий `VStack hAlign="center"` рядом с местом рендера.
 */
const RESULT_CONTENT_WIDTH = 640;

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
  const requestedTab = searchParams.get("tab");
  const isNarrowReview = useMediaQuery("(max-width: 1024px)", false);
  const [mobileReviewTab, setMobileReviewTab] = useState<"document" | "changes">("document");

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
  const isCompletedSafely = status === "done" && report?.validation?.ok === true;
  const hasUnsafeResult = status === "leaked" || (status === "done" && report?.validation?.ok === false);
  const tab: DocumentTab = requestedTab === "report"
    ? "report"
    : requestedTab === "review"
      ? "review"
      : hasUnsafeResult
        ? "report"
        : isCompletedSafely
        ? "result"
        : "review";

  function selectTab(value: DocumentTab) {
    setSearchParams((params) => {
      const next = new URLSearchParams(params);
      if (value === "result") next.delete("tab");
      else next.set("tab", value);
      return next;
    }, { replace: true });
  }

  const [selectedTypesRunId, setSelectedTypesRunId] = useState<string | null>(null);
  const progress = useRunProgress(runId, isRunPending(status));
  useEffect(() => {
    useReviewStore.setState({ questionAnswers: {} });
  }, [runId]);
  const isSelectingTypes = selectedTypesRunId !== runId && Boolean(ask?.questions.some((question) => question.kind === "type"));

  const [notFoundIds, setNotFoundIds] = useState<Set<string>>(new Set());
  const [isConfirmApproveOpen, setIsConfirmApproveOpen] = useState(false);
  const [isUnsafeDownloadConfirmOpen, setIsUnsafeDownloadConfirmOpen] = useState(false);
  const [isReviewSubmitted, setIsReviewSubmitted] = useState(false);
  const [regenerationRevision, setRegenerationRevision] = useState<number | null>(null);
  const [isDownloading, setIsDownloading] = useState(false);
  const statusRef = useRef(status);
  const reviewSubmittedRef = useRef(false);
  statusRef.current = status;

  const setDocumentGroups = useReviewStore((state) => state.setDocumentGroups);
  const discardDraftChanges = useReviewStore((state) => state.discardDraftChanges);
  const hasUnappliedChanges = useReviewStore((state) =>
    Object.keys(state.groupDecisions).length > 0
      || Object.keys(state.occurrenceDecisions).length > 0
      || Object.keys(state.typeOverrides).length > 0
      || Object.keys(state.occurrenceTypeOverrides).length > 0
      || state.manualOccurrences.length > 0,
  );
  const confirmedCount = useConfirmedGroupCount();
  const totalCount = useTotalGroupCount();
  const isReviewFinished = isRunFinished(status);
  const hasBlockingReviewChanges = hasUnappliedChanges && !isReviewFinished;

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
  const canDownload = ready && report?.validation?.ok === true && !hasUnsafeResult;
  const hasReadyArtifact = hasReadyArtifactForDownload(status, reviewedDocument.fileUrl);
  const replacementCount = report ? maskedOccurrences(report).length : null;
  const submitReview = useSubmitReview(runId);
  const regenerateReview = useRegenerateReview(runId);
  const isRegenerating = regenerationRevision !== null;
  const queryClient = useQueryClient();

  useEffect(() => {
    if (status !== "awaiting_review") {
      reviewSubmittedRef.current = false;
      setIsReviewSubmitted(false);
    }
    if (isRunFinished(status)) setIsConfirmApproveOpen(false);
  }, [status]);

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
    if (!canStartReviewSubmission(statusRef.current, submitReview.isPending, reviewSubmittedRef.current)) return;

    reviewSubmittedRef.current = true;
    setIsReviewSubmitted(true);
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
        reviewSubmittedRef.current = false;
        setIsReviewSubmitted(false);
        setIsConfirmApproveOpen(false);
        showToast({
          body: "Прогон уже не ждёт правок — обновите страницу",
          type: "error",
        });
      },
    });
  }

  function handleRegenerate() {
    if (runId === null || statusRef.current !== "awaiting_review" || isRegenerating) return;
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
  async function handleDownload(allowFailedValidation = false) {
    if (runId === null || !hasReadyArtifact) return;
    if (!canDownload && !allowFailedValidation) {
      setIsUnsafeDownloadConfirmOpen(true);
      return;
    }
    setIsDownloading(true);
    try {
      await downloadArtifact(runId, "masked_highlight", reviewedDocument.name);
      showToast({ body: "Обезличенный документ скачан", type: "info" });
    } catch (e) {
      console.log(e);
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

  const reviewView = (
    <ReviewView
      document={reviewedDocument}
      extraction={extraction}
      pages={report?.pages ?? []}
      hasUnappliedChanges={hasUnappliedChanges}
      isRegenerating={isRegenerating}
      isReviewFinished={isReviewFinished}
      onRegenerate={handleRegenerate}
      onDiscardChanges={discardDraftChanges}
      onNotFoundChange={setNotFoundIds}
    />
  );

  return (
    <>
      <ScreenLayout
        title={reviewedDocument.name}
        startContent={
          <FormatToken format={reviewedDocument.format.toUpperCase() as DocumentFormat} />
        }
        meta={
          tab === "review" && totalCount > 0 ? (
            <Badge
              variant={isReviewFinished ? "success" : "neutral"}
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
            onChange={(value) => selectTab(value as DocumentTab)}
            // Таб меняет тело экрана на месте, а не переходит по странице —
            // это настоящий tablist-паттерн, а не навигация: иконки и роль
            // делают это видно сразу, а не только по URL.
            role="tablist"
            size="sm"
          >
            {isCompletedSafely ? (
              <Tab
                value="result"
                label="Результат"
                icon={<Icon icon={CheckCircle2} size="sm" />}
                panelId={CONTENT_PANEL_ID}
              />
            ) : null}
            <Tab
              value="review"
              label={isCompletedSafely ? "Документ" : "Проверка"}
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
          tab === "review" && !isNarrowReview ? (
            <HStack gap={2}>
              {uploadIds.length > 1 ? <Button size="sm" variant="ghost" label="Выбрать файл"
                onClick={() => void navigate(location.pathname, { replace: true, state: { uploadIds, chooseUpload: true } })} /> : null}
              <Button
                size="sm"
                variant={isCompletedSafely ? "secondary" : hasReadyArtifact ? "primary" : "secondary"}
                label="Скачать обезличенный документ"
                icon={<Icon icon={Download} size="sm" />}
                isDisabled={!hasReadyArtifact || hasBlockingReviewChanges || isRegenerating || isDownloading}
                isLoading={isDownloading}
                onClick={() => void handleDownload()}
              />
              {shouldShowReviewFinish(status) ? (
                <Button
                  size="sm"
                  variant="secondary"
                  label="Завершить проверку"
                  icon={<Icon icon={CheckCircle2} size="sm" />}
                  isDisabled={submitReview.isPending || isReviewSubmitted || hasUnappliedChanges || isRegenerating}
                  isLoading={submitReview.isPending}
                  onClick={() => setIsConfirmApproveOpen(true)}
                />
              ) : null}
            </HStack>
          ) : tab === "report" && hasReadyArtifact ? (
            <Button
              size="sm"
              variant="secondary"
              label="Скачать обезличенный документ"
              icon={<Icon icon={Download} size="sm" />}
              isDisabled={hasBlockingReviewChanges || isRegenerating || isDownloading}
              isLoading={isDownloading}
              onClick={() => void handleDownload()}
            />
          ) : null
        }
        contentId={CONTENT_PANEL_ID}
        contentPadding={tab === "review" ? 0 : 8}
        isContentScrollable={tab !== "review"}
        contentWidth={tab === "report" ? REPORT_CONTENT_WIDTH : undefined}
        panel={
          tab === "review" && !isNarrowReview ? (
            <ReviewPanel
              extraction={extraction}
              report={report}
              ask={ask}
              runId={runId}
              totalCount={totalCount}
              notFoundIds={notFoundIds}
              isEditingDisabled={isRegenerating || isReviewFinished}
              isReadOnly={isReviewFinished}
            />
          ) : undefined
        }
      >
        {tab === "result" ? (
          <VStack hAlign="center">
            <Card padding={6} width="100%" maxWidth={RESULT_CONTENT_WIDTH}>
              <VStack gap={5}>
                <VStack gap={2}>
                  <Heading level={2}>Документ готов</Heading>
                  <Text color="secondary" textWrap="pretty">
                    Обезличивание завершено. Скачайте готовый файл или посмотрите замены в отчёте.
                  </Text>
                </VStack>
                <VStack gap={2}>
                  <Text weight="semibold" textWrap="pretty" className="break-all">
                    {reviewedDocument.name}
                  </Text>
                  {replacementCount !== null ? (
                    <Text color="secondary">
                      {replacementCount} {pluralRu(replacementCount, ["фрагмент скрыт", "фрагмента скрыты", "фрагментов скрыто"])}.
                    </Text>
                  ) : null}
                </VStack>
                <HStack gap={3} wrap="wrap">
                  <Button
                    size="lg"
                    width={isNarrowReview ? "100%" : undefined}
                    variant="primary"
                    label="Скачать обезличенный документ"
                    icon={<Icon icon={Download} size="sm" />}
                    isDisabled={!hasReadyArtifact || isDownloading}
                    isLoading={isDownloading}
                    onClick={() => void handleDownload()}
                  />
                  <Button
                    variant="ghost"
                    label="Посмотреть замены"
                    onClick={() => selectTab("report")}
                  />
                </HStack>
              </VStack>
            </Card>
          </VStack>
        ) : tab === "review" && isNarrowReview ? (
          <Layout
            height="fill"
            header={
              <LayoutHeader hasDivider>
                <TabList
                  value={mobileReviewTab}
                  onChange={(value) => setMobileReviewTab(value as "document" | "changes")}
                  size="sm"
                  layout="fill"
                  role="tablist"
                >
                  <Tab value="document" label="Документ" panelId="mobile-review-panel" />
                  <Tab value="changes" label="Замены" panelId="mobile-review-panel" />
                </TabList>
              </LayoutHeader>
            }
            content={
              <LayoutContent padding={0} id="mobile-review-panel">
                {mobileReviewTab === "document" ? reviewView : (
                  <ReviewPanel
                    extraction={extraction}
                    report={report}
                    ask={ask}
                    runId={runId}
                    totalCount={totalCount}
                    notFoundIds={notFoundIds}
                    isEditingDisabled={isRegenerating || isReviewFinished}
                    isReadOnly={isReviewFinished}
                    isNarrow
                  />
                )}
              </LayoutContent>
            }
          />
        ) : tab === "review" ? (
          reviewView
        ) : (
          <ReportView report={report} runId={runId} status={status} canDownload={canDownload} />
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
        isOpen={!isReviewFinished && isConfirmApproveOpen}
        onOpenChange={setIsConfirmApproveOpen}
        title="Утвердить документ?"
        description={
          reviewConfirmationDescription(confirmedCount, totalCount)
        }
        actionLabel="Утвердить"
        actionVariant="primary"
        isActionLoading={submitReview.isPending}
        onAction={handleApprove}
      />
      <AlertDialog
        isOpen={isUnsafeDownloadConfirmOpen}
        onOpenChange={setIsUnsafeDownloadConfirmOpen}
        title="Проверка результата не пройдена"
        description={report?.validation
          ? `Проверка обнаружила ${report.validation.leakedCount} возможных утечек и ${report.validation.residualCount} остаточных совпадений. В скачанном файле могут остаться исходные данные.`
          : "Безопасность результата не подтверждена. В скачанном файле могут остаться исходные данные."}
        cancelLabel="Отмена"
        actionLabel="Скачать всё равно"
        actionVariant="destructive"
        isActionLoading={isDownloading}
        onAction={() => {
          setIsUnsafeDownloadConfirmOpen(false);
          void handleDownload(true);
        }}
      />
    </>
  );
}
