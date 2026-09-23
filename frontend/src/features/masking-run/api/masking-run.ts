import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type { UploadSource } from "../../../entity/document/model/types";
import type { MaskStyle } from "../../../entity/rule-profile/model/types";
import type { CompiledTypeOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { clientApiWithAuth } from "../../../shared/api/mutators/authMutator";
import { uploadApiFilesUploadPost } from "../../../shared/api/generated/core/files/files";
import {
  createRunApiRunsPost,
  getArtifactsApiRunsRunIdArtifactsGet,
  getRunEventsApiRunsRunIdEventsGet,
  getQuestionsApiRunsRunIdQuestionsGet,
  getReportApiRunsRunIdReportGet,
  getRunApiRunsRunIdGet,
  listRunsApiRunsGet,
  postAnswersApiRunsRunIdAnswersPost,
  postRegenerateApiRunsRunIdRegeneratePost,
  postReviewApiRunsRunIdReviewPost,
} from "../../../shared/api/generated/core/runs/runs";
import type {
  AnswersRequest,
  ArtifactOut,
  AskEnvelopeOut,
  ReviewEdits,
  RegenerateRequest,
  ListRunsApiRunsGetParams,
  ReportOut,
  RunProgressEvent,
  RunListResponse,
  RunResponse,
} from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";

export type RunStatus = RunResponse["status"];

/**
 * Конверт ответов человека. `schema_version` приходит из
 * `buildAnswerEnvelope` обычным числом: версию задаёт движок, и сужать её до
 * литерала здесь нельзя — расхождение версий обязано доехать до бэкенда и
 * получить честный 422, а не быть скрытым типом на клиенте.
 */
export type AnswerEnvelopeInput = {
  schema_version: number;
  answers: Record<string, string>;
};

/** Прогон ещё крутится в графе — состояние нужно перечитывать. */
export function isRunPending(status: RunStatus | null | undefined): boolean {
  return status === "queued" || status === "running";
}

/** Прогон дошёл до конца: отчёт и артефакты на месте (утечка — тоже конец). */
export function isRunFinished(status: RunStatus | null | undefined): boolean {
  return status === "done" || status === "leaked";
}

/**
 * Отчёт и обезличенный документ уже собраны. Так выглядит и завершённый
 * прогон, и прогон на паузе правок оператора: узлы `render` и `report`
 * отработали до второго прерывания, поэтому экрану проверки есть что
 * показать ещё до утверждения документа.
 */
export function hasRunResult(status: RunStatus | null | undefined): boolean {
  return isRunFinished(status) || status === "awaiting_review";
}

/**
 * Проверяет, есть ли уже готовый файл для выдачи. Это только наличие артефакта,
 * а не гарантия его безопасности: результат со статусом `leaked` требует
 * отдельного предупреждения перед скачиванием.
 */
export function hasReadyArtifactForDownload(
  status: RunStatus | null | undefined,
  fileUrl: string,
): boolean {
  return hasRunResult(status) && fileUrl.length > 0;
}

/**
 * Как часто опрашивать состояние прогона. Транспорт намеренно обычный HTTP:
 * ни WebSocket, ни SSE — опрос переживает обрыв связи и перезагрузку вкладки,
 * потому что читает состояние из чекпойнтера LangGraph, а не из соединения.
 */
const POLL_INTERVAL_MS = 1500;

export const runKeys = {
  all: ["runs"] as const,
  list: (params?: ListRunsApiRunsGetParams) => ["runs", "list", params ?? {}] as const,
  detail: (runId: string) => ["runs", runId] as const,
  questions: (runId: string) => ["runs", runId, "questions"] as const,
  report: (runId: string) => ["runs", runId, "report"] as const,
  artifacts: (runId: string) => ["runs", runId, "artifacts"] as const,
};

/** Безопасная для UI часть живого снимка графа: бэкенд не отдаёт в ней текст документа. */
export type RunProgress = Pick<RunProgressEvent, "sequence" | "node" | "content">;

export type StartRunInput = {
  source: UploadSource;
  maskStyle: MaskStyle;
  /** `null` означает все встроенные типы; `[]` — ни одного. */
  types: string[] | null;
  /** Кастомные типы, скомпилированные пользователем. */
  customTypes: CompiledTypeOut[];
  /** Цвет фона маркера — `#RRGGBB`, только для `maskStyle: "marker"`
   * (бэкенд игнорирует его для "заливки", см. `mask-style-picker.tsx`). */
  highlightColor?: string;
};

/** Добавляет выбранные пользовательские типы к явному списку типов прогона. */
export function selectedTypesForRun(
  types: string[] | null,
  customTypes: CompiledTypeOut[],
): string[] | null {
  // null — выбор «все»: движок добавит в полный реестр и пользовательские типы.
  if (types === null) return null;

  const customTypeIds = customTypes.flatMap((type) => {
    if (type.outcome === "compile" && type.spec?.id) return [type.spec.id];
    if (type.outcome === "use_builtin" && type.type_id) return [type.type_id];
    return [];
  });

  return [...new Set([...types, ...customTypeIds])];
}

/**
 * Запуск прогона. Для нового файла — сперва загрузка в MinIO, затем
 * `POST /api/runs`; для уже загруженного объекта («Повторить прогон» в
 * `run-details-dialog.tsx`) — сразу `POST /api/runs` по его `object_name`,
 * без повторной загрузки байтов: объект переживает прогон именно для этого.
 */
export function useStartRun() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      source,
      maskStyle,
      types,
      customTypes,
      highlightColor,
    }: StartRunInput): Promise<RunResponse> => {
      const objectName =
        source.kind === "existing"
          ? source.objectName
          : await (async () => {
              const uploaded = await uploadApiFilesUploadPost({ file: source.file });
              if (uploaded.status !== 200) {
                throw new Error("Не удалось загрузить файл");
              }
              return uploaded.data.object_name;
            })();

      const compiledSpecs = customTypes
        .filter((t) => t.outcome === "compile" && t.spec != null)
        .map((t) => t.spec as unknown as Record<string, unknown>);

      // Явно включаем custom ids: при снятых встроенных флажках список состоит
      // только из пользовательских типов и не превращается на бэкенде во «все».
      const typesToSend = selectedTypesForRun(types, customTypes);

      const created = await createRunApiRunsPost({
        object_name: objectName,
        types: typesToSend,
        mask_style: maskStyle,
        custom_types: compiledSpecs.length > 0 ? compiledSpecs : undefined,
        // "Заливка" всегда чёрная на бэкенде — цвет ей не нужен, а дефолт
        // запроса совпал бы с выбором пользователя только случайно.
        highlight_background: maskStyle === "marker" ? highlightColor : undefined,
      });
      if (created.status !== 202) {
        throw new Error("Не удалось запустить обезличивание");
      }
      return created.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: runKeys.all });
    },
  });
}

/**
 * Лента прогресса независима от основного polling `GET /runs/{id}`: ошибка
 * этого необязательного представления не мешает дождаться финального статуса.
 */
export function useRunProgress(runId: string | null, enabled: boolean) {
  const [events, setEvents] = useState<RunProgress[]>([]);
  const [isUnavailable, setUnavailable] = useState(false);

  useEffect(() => {
    if (runId === null || !enabled) return;
    let cancelled = false;
    let after = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const response = await getRunEventsApiRunsRunIdEventsGet(runId, { after });
        if (response.status !== 200) throw new Error("Лента недоступна");
        if (cancelled) return;
        after = response.data.next_after;
        if (response.data.events.length > 0) {
          setEvents((previous) => [...previous, ...response.data.events]);
        }
        timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
      } catch {
        if (!cancelled) setUnavailable(true);
      }
    };

    setEvents([]);
    setUnavailable(false);
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, runId]);

  return { events, isUnavailable };
}

/** Состояние прогона; пока он идёт — с опросом, дальше запрос замирает. */
export function useRunState(runId: string | null) {
  return useQuery({
    queryKey: runKeys.detail(runId ?? ""),
    enabled: runId !== null,
    queryFn: async (): Promise<RunResponse> => {
      const response = await getRunApiRunsRunIdGet(runId as string);
      if (response.status !== 200) {
        throw new Error("Прогон не найден");
      }
      return response.data;
    },
    refetchInterval: (query) =>
      isRunPending(query.state.data?.status) ? POLL_INTERVAL_MS : false,
  });
}

/**
 * Конверт вопросов приостановленного прогона. Ответ `404` — это «вопросов
 * нет», а не сбой: запрос включается только на статусе `awaiting_answers`.
 */
export function useRunQuestions(runId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: runKeys.questions(runId ?? ""),
    enabled: runId !== null && enabled,
    queryFn: async (): Promise<AskEnvelopeOut> => {
      const response = await getQuestionsApiRunsRunIdQuestionsGet(runId as string);
      if (response.status !== 200) {
        throw new Error("Вопросы недоступны");
      }
      return response.data;
    },
  });
}

/** `report.json` прогона — включается, когда прогон дошёл до конца. */
export function useRunReport(runId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: runKeys.report(runId ?? ""),
    enabled: runId !== null && enabled,
    queryFn: async (): Promise<ReportOut> => {
      const response = await getReportApiRunsRunIdReportGet(runId as string);
      if (response.status !== 200) {
        throw new Error("Отчёт недоступен");
      }
      return response.data;
    },
  });
}

/** Список файлов рендера прогона (`preview`, `masked_highlight`, `masked_black`). */
export function useRunArtifacts(runId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: runKeys.artifacts(runId ?? ""),
    enabled: runId !== null && enabled,
    queryFn: async (): Promise<ArtifactOut[]> => {
      const response = await getArtifactsApiRunsRunIdArtifactsGet(runId as string);
      if (response.status !== 200) {
        throw new Error("Артефакты недоступны");
      }
      return response.data;
    },
  });
}

export type RuntimeMetrics = {
  stages: Record<string, { calls: number; duration_ms: number }>;
  /**
   * Та же лента, что и `report.telemetry.events`, но с временем от старта
   * прогона (`elapsed_ms`) — этого поля нет в `report.json`, чтобы отчёт
   * оставался побайтово детерминированным (`masker.telemetry.runtime_metrics`).
   * Сшивается с `report.telemetry.events` по `sequence`.
   */
  events?: { sequence: number; elapsed_ms: number; node: string; message: string }[];
};

/** Недетерминированный companion-артефакт с длительностями стадий. */
export function useRuntimeMetrics(runId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["runs", runId, "runtime-metrics"],
    enabled: runId !== null && enabled,
    queryFn: async (): Promise<RuntimeMetrics | null> => {
      try {
        const response = await clientApiWithAuth.get<RuntimeMetrics>(
          `/runs/${runId}/artifacts/runtime_metrics`,
        );
        return response.data;
      } catch {
        return null;
      }
    },
  });
}

/**
 * Отправка ответов человека. Прогон продолжится фоном, поэтому после ответа
 * инвалидируются состояние, вопросы и отчёт — их перечитает опрос.
 */
export function useSubmitAnswers(runId: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (envelope: AnswerEnvelopeInput): Promise<RunResponse> => {
      // Схема сгенерирована из OpenAPI и сужает версию до литерала `1`.
      // Клиент версию не подменяет: если движок поднимет её, конверт уйдёт
      // как есть и вернётся честный 422, а не молчаливое несовпадение.
      const response = await postAnswersApiRunsRunIdAnswersPost(
        runId as string,
        envelope as AnswersRequest,
      );
      if (response.status !== 202) {
        throw new Error("Ответы не приняты");
      }
      return response.data;
    },
    onSuccess: () => {
      if (runId === null) return;
      void queryClient.invalidateQueries({ queryKey: runKeys.detail(runId) });
      void queryClient.invalidateQueries({ queryKey: runKeys.questions(runId) });
      void queryClient.invalidateQueries({ queryKey: runKeys.report(runId) });
      void queryClient.invalidateQueries({ queryKey: runKeys.artifacts(runId) });
    },
  });
}

/**
 * Утверждение документа: правки оператора уходят вторым прерыванием в граф,
 * и документ пересобирается там же. Клиент ничего не «применяет» сам.
 */
export function useSubmitReview(runId: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (edits: ReviewEdits): Promise<RunResponse> => {
      const response = await postReviewApiRunsRunIdReviewPost(runId as string, {
        schema_version: 1,
        edits,
      });
      if (response.status !== 202) {
        throw new Error("Правки не приняты");
      }
      return response.data;
    },
    onSuccess: () => {
      if (runId === null) return;
      void queryClient.invalidateQueries({ queryKey: runKeys.detail(runId) });
      void queryClient.invalidateQueries({ queryKey: runKeys.report(runId) });
      void queryClient.invalidateQueries({ queryKey: runKeys.artifacts(runId) });
    },
  });
}

/**
 * Применяет черновые правки, но оставляет прогон на следующей паузе проверки.
 * Файл продолжает обновлять `useRunState`: 202 означает только, что сервер
 * принял работу, а не что новый артефакт уже готов.
 */
export function useRegenerateReview(runId: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ edits, expectedRevision }: {
      edits: ReviewEdits;
      expectedRevision: number;
    }): Promise<RunResponse> => {
      const response = await postRegenerateApiRunsRunIdRegeneratePost(
        runId as string,
        {
          schema_version: 1,
          edits,
          expected_revision: expectedRevision,
        } as RegenerateRequest,
      );
      if (response.status !== 202) {
        throw new Error("Не удалось запустить перегенерацию");
      }
      return response.data;
    },
    onSuccess: () => {
      if (runId === null) return;
      void queryClient.invalidateQueries({ queryKey: runKeys.detail(runId) });
      void queryClient.invalidateQueries({ queryKey: runKeys.report(runId) });
      void queryClient.invalidateQueries({ queryKey: runKeys.artifacts(runId) });
      void queryClient.invalidateQueries({ queryKey: runKeys.all });
    },
  });
}

/** Журнал обработок текущего пользователя. */
export function useRunList(params?: ListRunsApiRunsGetParams) {
  return useQuery({
    queryKey: runKeys.list(params),
    queryFn: async (): Promise<RunListResponse> => {
      const response = await listRunsApiRunsGet(params);
      if (response.status !== 200) {
        throw new Error("Журнал недоступен");
      }
      return response.data;
    },
  });
}

/**
 * Скачать артефакт файлом.
 *
 * Прямая ссылка не годится: эндпоинт закрыт Bearer-токеном, который браузер
 * к навигации не приложит. Поэтому файл берётся авторизованным клиентом и
 * отдаётся пользователю как временная `blob:`-ссылка.
 */
export async function downloadArtifact(
  runId: string,
  role: string,
  fileName: string,
): Promise<void> {
  const response = await clientApiWithAuth.get<Blob>(
    `/runs/${runId}/artifacts/${role}`,
    { responseType: "blob" },
  );

  const url = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.style.display = "none";
  document.body.append(link);
  link.click();
  link.remove();
  // Не отзывать blob URL синхронно: браузер ещё может не начать загрузку.
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

/**
 * Локальная ссылка на артефакт для вьюера.
 *
 * Вьюер грузит документ обычным `fetch(fileUrl)` и заголовков авторизации не
 * ставит, а эндпоинт артефакта закрыт Bearer-токеном. Поэтому файл забирается
 * авторизованным клиентом в память и отдаётся вьюеру как `blob:`-ссылка;
 * ссылка живёт ровно столько, сколько открыт документ.
 */
export function useArtifactObjectUrl(
  runId: string | null,
  role: string,
  enabled: boolean,
  artifactRevision: number,
) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    if (runId === null || !enabled) {
      setObjectUrl(null);
      return;
    }

    let cancelled = false;
    let created: string | null = null;

    clientApiWithAuth
      .get<Blob>(`/runs/${runId}/artifacts/${role}`, { responseType: "blob" })
      .then((response) => {
        if (cancelled) return;
        created = URL.createObjectURL(response.data);
        setObjectUrl(created);
      })
      .catch(() => {
        if (!cancelled) setObjectUrl(null);
      });

    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [runId, role, enabled, artifactRevision]);

  return objectUrl;
}

/** Удалить прогон в любом статусе; если он активен — сервер его остановит. */
export function useDeleteRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (runId: string): Promise<void> => {
      const response = await clientApiWithAuth.delete(`/runs/${runId}`);
      if (response.status !== 204) {
        throw new Error("Не удалось удалить прогон");
      }
    },
    onSuccess: (_data, runId) => {
      void queryClient.invalidateQueries({ queryKey: runKeys.all });
      queryClient.removeQueries({ queryKey: runKeys.detail(runId) });
    },
  });
}
