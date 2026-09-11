import { useMemo } from "react";

import { parseAskEnvelope, parseMaskingReport } from "../../../entity/pii/model/schema";
import type {
  AskEnvelope,
  MaskingReport,
  PiiDocFormat,
  PiiExtraction,
} from "../../../entity/pii/model/types";
import {
  hasRunResult,
  useArtifactObjectUrl,
  useRunQuestions,
  useRunReport,
  useRunState,
  type RunStatus,
} from "../../masking-run/api/masking-run";

export type ReviewedDocument = {
  name: string;
  format: PiiDocFormat;
  /**
   * Ссылка на файл для вьюера. Пустая строка — документа ещё нет: прогон
   * стоит на вопросах, узел `render` не выполнялся. Вьюер обязан пережить
   * это состояние, а не грузить несуществующий адрес.
   */
  fileUrl: string;
  /** Ссылка на `preview` с исходным текстом для режима «Оригинал». */
  originalFileUrl: string;
};

export type ReviewData = {
  /** Прогон, открытый на рабочем столе документа (`/documents/:runId`); `null` — не выбран. */
  runId: string | null;
  status: RunStatus | null;
  extraction: PiiExtraction;
  document: ReviewedDocument;
  /**
   * Весь `report.json` прогона. `null` — отчёта ещё нет: пока граф стоит на
   * вопросах, узел `report` не выполнялся. Экраны обязаны уметь показать это
   * состояние, а не падать.
   */
  report: MaskingReport | null;
  /**
   * Конверт паузы графа, если прогон остановился на вопросах к человеку.
   * `null` — вопросов не было либо на них уже ответили.
   */
  ask: AskEnvelope | null;
  isLoading: boolean;
  error: string | null;
};

const EMPTY_EXTRACTION: PiiExtraction = { chunkCount: 0, chunks: [] };

/**
 * Единственная точка входа за данными рабочего стола документа
 * (`/documents/:runId`) — общая для вкладок «Проверка» и «Отчёт».
 *
 * Вызывается один раз в `DocumentPage`, а не в каждой вкладке: так `blob:`-
 * ссылка на документ (`useArtifactObjectUrl`) живёт всё время, что открыт
 * рабочий стол, и переключение таба не перекачивает файл заново.
 *
 * Состояние прогона опрашивается, пока граф крутится, вопросы забираются на
 * паузе `ask_human`, отчёт и документ — когда прогон дошёл до конца.
 * Разбирают ответы те же `parseMaskingReport`/`parseAskEnvelope`, что раньше
 * разбирали фикстуры: форма контракта одна и та же, менялся только источник.
 *
 * Документ для вьюера — `masked_highlight` этого же прогона; исходных ПДн в
 * нём нет, поэтому оператор смотрит именно обезличенный файл, а не оригинал.
 */
export function useReviewData(runId: string | null): ReviewData {
  const runState = useRunState(runId);
  const status = runState.data?.status ?? null;
  // Отчёт и файл рендера существуют и на паузе правок оператора, не только
  // на завершённом прогоне: экран проверки для того и открывается.
  const hasResult = hasRunResult(status);

  const questions = useRunQuestions(runId, status === "awaiting_answers");
  const report = useRunReport(runId, hasResult);
  const fileUrl = useArtifactObjectUrl(runId, "masked_highlight", hasResult);
  const originalFileUrl = useArtifactObjectUrl(runId, "preview", hasResult);

  const parsedReport = useMemo(
    () => (report.data === undefined ? null : parseMaskingReport(report.data)),
    [report.data],
  );
  const parsedAsk = useMemo(
    () => (status !== "awaiting_answers" || questions.data === undefined ? null : parseAskEnvelope(questions.data)),
    [questions.data, status],
  );

  const document: ReviewedDocument = {
    name: parsedReport?.input ?? runState.data?.document.name ?? "",
    format: (parsedReport?.format ??
      runState.data?.document.format ??
      "docx") as PiiDocFormat,
    fileUrl: fileUrl ?? "",
    originalFileUrl: originalFileUrl ?? "",
  };

  return {
    runId,
    status,
    extraction: parsedReport?.extraction ?? EMPTY_EXTRACTION,
    document,
    report: parsedReport,
    ask: parsedAsk,
    isLoading: runState.isLoading || report.isLoading || questions.isLoading,
    error: errorTextOf(runState.error) ?? runState.data?.error
      ?? (status === "awaiting_answers" ? errorTextOf(questions.error) : null)
      ?? (hasResult ? errorTextOf(report.error) : null),
  };
}

function errorTextOf(error: unknown): string | null {
  if (error === null || error === undefined) return null;
  return error instanceof Error ? error.message : String(error);
}
