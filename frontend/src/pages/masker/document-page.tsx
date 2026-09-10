import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { CheckCircle2, Download, FileBarChart2, ListChecks, Sheet } from "lucide-react";
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
  useSubmitReview,
} from "../../features/masking-run/api/masking-run";
import { useReviewData } from "../../features/pii-review/api/use-review-data";
import { ReviewPanel } from "../../features/pii-review/ui/review-panel";
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
 * Рабочий стол документа: проверка и отчёт делят одну шапку и панель,
 * переключение — таб в шапке, а не переход по страницам. Документ и его
 * `blob:`-ссылка (`useReviewData`) читаются один раз здесь, а не в каждой
 * вкладке — поэтому смена таба не перекачивает файл заново.
 */
export function DocumentPage() {
  const { runId: routeRunId } = useParams<"runId">();
  const runId = routeRunId ?? null;
  const navigate = useNavigate();
  const showToast = useToast();

  const [searchParams, setSearchParams] = useSearchParams();
  const tab: DocumentTab = searchParams.get("tab") === "report" ? "report" : "review";

  const {
    status,
    extraction,
    document: reviewedDocument,
    report,
    ask,
  } = useReviewData(runId);

  const [notFoundIds, setNotFoundIds] = useState<Set<string>>(new Set());
  const [isConfirmApproveOpen, setIsConfirmApproveOpen] = useState(false);

  const setDocumentGroups = useReviewStore((state) => state.setDocumentGroups);
  const confirmedCount = useConfirmedGroupCount();
  const totalCount = useTotalGroupCount();
  const allConfirmed = confirmedCount === totalCount;

  const occurrences = useMemo(() => flattenPiiOccurrences(extraction), [extraction]);

  // Счётчики проверки живут в сторе и должны считать по открытому документу,
  // а не по фикстуре, и одинаково — на вкладках «Проверка» и «Отчёт».
  const documentGroups = useMemo(() => {
    const minConfidence = new Map<string, number>();
    for (const occurrence of occurrences) {
      const known = minConfidence.get(occurrence.groupId);
      minConfidence.set(
        occurrence.groupId,
        known === undefined ? occurrence.confidence : Math.min(known, occurrence.confidence),
      );
    }
    return [...minConfidence].map(([id, confidence]) => ({
      id,
      minConfidence: confidence,
    }));
  }, [occurrences]);

  useEffect(() => {
    setDocumentGroups(documentGroups);
  }, [documentGroups, setDocumentGroups]);

  const ready = hasRunResult(status);
  const submitReview = useSubmitReview(runId);

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

  /** Скачивает подсвеченный вариант — тот же файл, что открыт во вьюере. */
  async function handleDownload() {
    if (runId === null) return;
    try {
      await downloadArtifact(runId, "masked_highlight", reviewedDocument.name);
    } catch {
      showToast({ body: "Не удалось скачать обезличенный документ", type: "error" });
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
              onClick={() => navigate("/documents")}
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
              variant={allConfirmed ? "success" : "neutral"}
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
              <Button
                size="sm"
                variant="secondary"
                label="Скачать"
                icon={<Icon icon={Download} size="sm" />}
                isDisabled={!ready}
                onClick={() => void handleDownload()}
              />
              <Button
                size="sm"
                variant={allConfirmed ? "primary" : "secondary"}
                label="Утвердить документ"
                icon={<Icon icon={CheckCircle2} size="sm" />}
                isDisabled={status !== "awaiting_review" || submitReview.isPending}
                isLoading={submitReview.isPending}
                onClick={() => setIsConfirmApproveOpen(true)}
              />
            </HStack>
          ) : (
            <HStack gap={2}>
              <Button size="sm" variant="ghost" label="CSV" icon={<Icon icon={Sheet} size="sm" />} />
              <Button size="sm" variant="ghost" label="XLSX" icon={<Icon icon={Sheet} size="sm" />} />
              <Button
                size="sm"
                variant="primary"
                label="PDF-отчёт"
                icon={<Icon icon={Download} size="sm" />}
              />
            </HStack>
          )
        }
        contentId={CONTENT_PANEL_ID}
        contentPadding={tab === "review" ? 0 : 6}
        isContentScrollable={tab !== "review"}
        panel={
          tab === "review" ? (
            <ReviewPanel
              extraction={extraction}
              report={report}
              ask={ask}
              runId={runId}
              totalCount={totalCount}
              notFoundIds={notFoundIds}
            />
          ) : undefined
        }
      >
        {tab === "review" ? (
          <ReviewView
            document={reviewedDocument}
            extraction={extraction}
            occurrences={occurrences}
            onNotFoundChange={setNotFoundIds}
          />
        ) : (
          <ReportView report={report} />
        )}
      </ScreenLayout>
      <AlertDialog
        isOpen={isConfirmApproveOpen}
        onOpenChange={setIsConfirmApproveOpen}
        title="Утвердить документ?"
        description={
          allConfirmed
            ? "Документ пересоберётся с вашими правками и уйдёт в финальный отчёт. Отменить утверждение будет нельзя."
            : `Подтверждено ${confirmedCount} из ${totalCount} — остальные вхождения уйдут в документ как есть. Отменить утверждение будет нельзя.`
        }
        actionLabel="Утвердить"
        actionVariant="primary"
        isActionLoading={submitReview.isPending}
        onAction={handleApprove}
      />
    </>
  );
}
