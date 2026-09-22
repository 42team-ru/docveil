import { z } from "zod";

import type {
  AskEnvelopeOut,
  ReportOut,
} from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import type {
  AnswerOption,
  AskEnvelope,
  Certificate,
  ConfidenceLevel,
  ContractParty,
  DecisionSource,
  EntityAction,
  MaskGroupRecord,
  MaskingReport,
  PiiChunk,
  PiiDocFormat,
  PiiExtraction,
  PiiOccurrence,
  PiiPage,
  PiiRegion,
  PiiSource,
  PiiType,
  PolicyQuestion,
  ReportDecisions,
} from "./types";
import { KEEP_CRITICAL_OPTION, KEEP_OPTION, MASK_OPTION } from "./types";

/**
 * Сырой контракт бэкенда — snake_case, как в присланном примере ответа.
 * Схема намеренно не строгая по типу ПДн (z.string() вместо enum): бэкенд ещё
 * не стабилизирован, а неизвестный тип должен доходить до UI как есть, а не
 * ронять весь парсинг.
 */
const rawAnchorSchema = z.object({
  format: z.string(),
  label: z.string(),
  locator: z.array(z.union([z.string(), z.number()])),
});

const rawRegionSchema = z.object({
  page: z.number(),
  x0: z.number(),
  y0: z.number(),
  x1: z.number(),
  y1: z.number(),
});

const rawPiiSchema = z.object({
  ref: z.string(),
  group_id: z.string(),
  marker: z.string(),
  decision: z.string().optional().nullable(),
  type: z.string(),
  text: z.string(),
  normalized: z.string(),
  confidence: z.number(),
  level: z.string(),
  source: z.string(),
  segment_order: z.number(),
  chunk_start: z.number(),
  chunk_end: z.number(),
  anchor: rawAnchorSchema,
  //: Пусто для docx/xlsx (нет PDF-артефакта) — не у всех прогонов есть план
  //: замен на момент разбора (`chunks[].pii[]` строится и до плана).
  regions: z.array(rawRegionSchema).optional(),
});

const rawChunkSchema = z.object({
  id: z.string(),
  text: z.string(),
  anchor: rawAnchorSchema,
  segment_order: z.number(),
  pii: z.array(rawPiiSchema),
});

const rawExtractionSchema = z.object({
  chunk_count: z.number(),
  chunks: z.array(rawChunkSchema),
});

/** Экспортирован для `use-review-data.ts` — формат по расширению реального
 * артефакта проверяется тем же списком, что и разбор отчёта. */
export const KNOWN_FORMATS: PiiDocFormat[] = [
  "docx",
  "pdf",
  "xlsx",
  "jpg",
  "jpeg",
  "png",
  "tif",
  "tiff",
];
const KNOWN_SOURCES: PiiSource[] = ["rule", "ner", "llm", "user", "block"];
const KNOWN_LEVELS: ConfidenceLevel[] = ["confirmed", "probable", "possible"];

function toDocFormat(value: string): PiiDocFormat {
  return (KNOWN_FORMATS as string[]).includes(value)
    ? (value as PiiDocFormat)
    : "docx";
}

function toSource(value: string): PiiSource {
  return (KNOWN_SOURCES as string[]).includes(value)
    ? (value as PiiSource)
    : "rule";
}

/**
 * Уровень неизвестен молча по умолчанию `probable` — тот же выбор, что и у
 * бэкенда для чекпойнтов до Р8 (`graph/serde.py::entity_from_dict`): самый
 * строгий вариант из «не подтверждено», не тихое `confirmed`.
 */
function toLevel(value: string): ConfidenceLevel {
  return (KNOWN_LEVELS as string[]).includes(value)
    ? (value as ConfidenceLevel)
    : "probable";
}

/** То же самое, но для `plan.groups[].level`, где пустая строка — законное значение. */
function toGroupLevel(value: string): ConfidenceLevel | "" {
  return value === "" || (KNOWN_LEVELS as string[]).includes(value)
    ? (value as ConfidenceLevel | "")
    : "";
}

/** Тип неизвестный бэкенду проходит как есть — UI решит, как его подписать. */
function toType(value: string): PiiType {
  return value as PiiType;
}

function toRegions(
  regions: z.infer<typeof rawRegionSchema>[] | undefined,
): PiiRegion[] {
  return (regions ?? []).map((region) => ({
    page: region.page,
    x0: region.x0,
    y0: region.y0,
    x1: region.x1,
    y1: region.y1,
  }));
}

/**
 * Парсит и нормализует ответ бэкенда в структуру, которой пользуется остальной
 * код (camelCase, типизированные enum-подобные поля). Бросает ZodError с
 * внятным путём при расхождении контракта — не глотает ошибку молча.
 */
export function parsePiiExtraction(payload: unknown): PiiExtraction {
  const raw = rawExtractionSchema.parse(payload);

  const chunks: PiiChunk[] = raw.chunks.map((chunk) => ({
    id: chunk.id,
    text: chunk.text,
    segmentOrder: chunk.segment_order,
    anchor: {
      format: toDocFormat(chunk.anchor.format),
      label: chunk.anchor.label,
      locator: chunk.anchor.locator,
    },
    pii: chunk.pii.map(
      (pii): PiiOccurrence => ({
        ref: pii.ref,
        groupId: pii.group_id,
        marker: pii.marker,
        action:
          pii.decision === "mask" || pii.decision === "keep"
            ? pii.decision
            : null,
        type: toType(pii.type),
        text: pii.text,
        normalized: pii.normalized,
        confidence: pii.confidence,
        level: toLevel(pii.level),
        source: toSource(pii.source),
        segmentOrder: pii.segment_order,
        chunkStart: pii.chunk_start,
        chunkEnd: pii.chunk_end,
        regions: toRegions(pii.regions),
      }),
    ),
  }));

  return { chunkCount: raw.chunk_count, chunks };
}

/* ------------------------------------------------------------------ *
 * Полный `report.json`.
 *
 * `parsePiiExtraction` выше разбирает только чанки — этого хватало, пока
 * остальные экраны жили на фикстурах. `parseMaskingReport` читает отчёт
 * целиком: сводку, план замен, профили сторон, карточку договора, решения
 * движка и проверку утечек.
 * ------------------------------------------------------------------ */

/**
 * Якорь приходит с разным именем ключа в разных секциях одного и того же
 * отчёта: `format` в `entities`/`chunks` (`report/payload.py`) и `fmt` в
 * `profile_judge` (`graph/serde.py`). Разбираем обе формы одним местом, а не
 * двумя парсерами: расхождение чужое, но чинить его придётся здесь.
 */
const rawEitherAnchorSchema = z
  .object({
    format: z.string().optional(),
    fmt: z.string().optional(),
    label: z.string(),
    locator: z.array(z.union([z.string(), z.number()])),
  })
  .transform((raw) => ({
    format: toDocFormat(raw.format ?? raw.fmt ?? ""),
    label: raw.label,
    locator: raw.locator,
  }));

const rawSummarySchema = z.object({
  entities_total: z.number(),
  by_type: z.record(z.string(), z.number()),
  by_source: z.record(z.string(), z.number()),
  by_level: z.record(z.string(), z.number()),
  minimum_confidence: z.number().nullable(),
});

const rawPlanGroupSchema = z.object({
  id: z.string(),
  marker: z.string(),
  type: z.string(),
  type_title: z.string(),
  profile_id: z.string(),
  ref_count: z.number(),
  sample: z.string(),
  level: z.string(),
});

const rawPlanSchema = z.object({
  requested_types: z.array(z.string()),
  groups: z.array(rawPlanGroupSchema),
  skipped: z.object({
    count: z.number(),
    by_reason: z.record(z.string(), z.number()),
  }),
});

const rawProfileMemberSchema = z.object({
  ref: z.string(),
  anchor: rawEitherAnchorSchema,
  entity: z.object({
    type: z.string(),
    text: z.string(),
    normalized: z.string(),
    confidence: z.number(),
    source: z.string(),
  }),
});

const rawProfileSchema = z.object({
  id: z.string(),
  role_id: z.string(),
  role_title: z.string(),
  marker_label: z.string(),
  confidence: z.number(),
  role_confidence: z.number(),
  source: z.string(),
  evidence: z.array(z.string()),
  members: z.array(rawProfileMemberSchema),
});

const rawPartySchema = z.object({
  name: z.string().nullable(),
  role_title: z.string().nullable(),
  inn: z.string().nullable(),
  ogrn: z.string().nullable(),
});

const rawContractSummarySchema = z.object({
  customer: rawPartySchema.nullable().optional().default(null),
  supplier: rawPartySchema.nullable().optional().default(null),
  federal_law: z.array(z.string()).optional().default([]),
  contract_amount: z.string().nullable().optional().default(null),
  delivery_periods: z.array(z.string()).optional().default([]),
  payment_terms: z.string().nullable().optional().default(null),
  contract_number: z.string().nullable().optional().default(null),
  generated_at: z.string().optional().default(""),
  llm_calls: z.number().optional().default(0),
  brief_summary: z.string().nullable().optional().default(null),
  document_kind: z.object({
    status: z.enum(["contract", "non_contract", "unknown"]).optional().default("unknown"),
    genre: z.string().nullable().optional().default(null),
  }).optional().default({ status: "unknown", genre: null }),
});

const rawTelemetrySchema = z.object({
  events: z.array(z.object({ sequence: z.number(), node: z.string(), message: z.string() })).optional().default([]),
  llm: z.object({
    calls: z.number(), prompt_tokens: z.number(), completion_tokens: z.number(),
    status: z.string(), message: z.string(), cost: z.record(z.string(), z.unknown()).nullable().optional().default(null),
    by_node: z.array(z.object({
      node: z.string(), calls: z.number(), prompt_tokens: z.number(), completion_tokens: z.number(),
    })).optional().default([]),
    // Тариф активного на момент прогона профиля — раньше отсутствовал в
    // контракте, и report-resources.tsx оценивал стоимость по узлам зашитым
    // тарифом GigaChat, который на другом активном профиле был бы неверным.
    pricing: z.record(z.string(), z.unknown()).nullable().optional().default(null),
  }),
  runtime: z.object({ available: z.boolean(), note: z.string().optional().default("") }),
});

const rawDecisionsSchema = z.object({
  mode: z.string(),
  thread_id: z.string(),
  by_ref: z.array(
    z.object({
      ref: z.string(),
      action: z.string(),
      decided_by: z.string(),
      question_id: z.string(),
      reason: z.string(),
    }),
  ),
  critical_unmasked: z.array(
    z.object({
      question_id: z.string(),
      kind: z.string(),
      target: z.string(),
      count: z.number(),
    }),
  ),
  diagnostics: z.array(z.string()),
});

const rawCertificateCheckSchema = z.object({
  name: z.string(),
  ok: z.boolean(),
  detail: z.string(),
});

const rawCertificateSchema = z.object({
  ok: z.boolean(),
  checks: z.array(rawCertificateCheckSchema),
});

const rawValidationSchema = z.object({
  status: z.string(),
  ok: z.boolean().optional(),
  leaked_count: z.number().optional(),
  residual_count: z.number().optional(),
  checked_artifacts: z.array(z.string()).optional(),
  certificate: rawCertificateSchema.nullable().optional(),
});

const rawMarkerLegendItemSchema = z.object({
  shown_label: z.string(),
  canonical_label: z.string(),
  pages: z.array(z.number()),
});

const rawDetectionCoverageSchema = z.object({
  requested_types: z.array(z.string()),
  active_detector_types: z.array(z.string()),
  requested_without_detector: z.array(z.string()),
});

const rawReportSchema = z.object({
  report_version: z.number(),
  input: z.string(),
  format: z.string(),
  selected_types: z.array(z.string()),
  entity_count: z.number(),
  chunk_count: z.number(),
  chunks: z.array(rawChunkSchema),
  summary: rawSummarySchema,
  detection_coverage: rawDetectionCoverageSchema,
  document_coverage: z.record(z.string(), z.unknown()),
  limitations: z.array(z.string()),
  // Секции ниже движок кладёт не всегда: `plan` появляется только когда план
  // построен, `profile_judge` — при `--profile` (PDF его не строит вовсе,
  // `run_service._run_options`), `decisions`/`validation` — после
  // соответствующих узлов графа. На бэкенде это `X | None = None`
  // (`api/schemas/report.py`) — Pydantic сериализует такое как JSON `null`,
  // ключ не пропускает, поэтому `.optional()` одного не хватает: `null`
  // — валидный, а не только отсутствующий ключ.
  plan: rawPlanSchema.nullable().optional(),
  profile_judge: z
    .object({ profiles: z.array(rawProfileSchema) })
    .loose()
    .nullable()
    .optional(),
  contract_summary: rawContractSummarySchema.nullable().optional(),
  decisions: rawDecisionsSchema.nullable().optional(),
  validation: rawValidationSchema.optional(),
  //: Р8, «снять одним кликом» — группы уровня `possible`; движок кладёт
  //: пустой массив, даже когда плана нет вовсе.
  review_possible: z.array(rawPlanGroupSchema).optional(),
  marker_legend: z.array(rawMarkerLegendItemSchema).optional(),
  //: Дубль `validation.certificate` на верхнем уровне report.json (план М3).
  certificate: rawCertificateSchema.nullable().optional(),
  telemetry: rawTelemetrySchema.nullable().optional(),
  //: Размеры страниц PDF-артефакта (план feat/highlight-coords-edits, К1) —
  //: пусто для docx/xlsx, движок кладёт `[]`, а не опускает ключ вовсе.
  pages: z
    .array(
      z.object({
        page: z.number(),
        width_pt: z.number(),
        height_pt: z.number(),
      }),
    )
    .optional(),
});

function toMode(value: string): ReportDecisions["mode"] {
  return value === "interactive" || value === "non_interactive"
    ? value
    : "unknown";
}

function toPlanGroup(
  group: z.infer<typeof rawPlanGroupSchema>,
): MaskGroupRecord {
  return {
    id: group.id,
    marker: group.marker,
    type: toType(group.type),
    typeTitle: group.type_title,
    profileId: group.profile_id,
    refCount: group.ref_count,
    sample: group.sample,
    level: toGroupLevel(group.level),
  };
}

function toCertificate(
  certificate: z.infer<typeof rawCertificateSchema> | null | undefined,
): Certificate | null {
  return certificate
    ? {
        ok: certificate.ok,
        checks: certificate.checks.map((check) => ({
          name: check.name,
          ok: check.ok,
          detail: check.detail,
        })),
      }
    : null;
}

/**
 * Разбирает `report.json` целиком. Тип входа — `ReportOut`, сгенерированный
 * Orval'ом из ответа `GET /runs/{id}/report` (`response_model=ReportOut`
 * на бэкенде, `api/schemas/report.py`): форма проверена сервером ещё до
 * этой функции, `zod` здесь — второй, а не единственный рубеж, и вдобавок
 * терпимее к неизвестным значениям (см. `toType`).
 *
 * Решения движка берутся из `decisions.by_ref`, а не из `chunks[].pii[]`:
 * в чанках их нет вовсе (проверено на настоящей выдаче — `decision` движок
 * кладёт только в плоский `entities[]`), а `by_ref` вдобавок несёт и то,
 * какое решение чем было перекрыто.
 */
export function parseMaskingReport(payload: ReportOut): MaskingReport {
  const raw = rawReportSchema.parse(payload);
  const profileJudge = raw.profile_judge as
    | { profiles: z.infer<typeof rawProfileSchema>[] }
    | null
    | undefined;

  return {
    reportVersion: raw.report_version,
    input: raw.input,
    format: toDocFormat(raw.format),
    selectedTypes: raw.selected_types.map(toType),
    entityCount: raw.entity_count,
    extraction: parsePiiExtraction({
      chunk_count: raw.chunk_count,
      chunks: payloadChunks(payload),
    }),
    summary: {
      entitiesTotal: raw.summary.entities_total,
      byType: raw.summary.by_type,
      bySource: raw.summary.by_source,
      byLevel: raw.summary.by_level,
      minimumConfidence: raw.summary.minimum_confidence,
    },
    plan: raw.plan
      ? {
          requestedTypes: raw.plan.requested_types.map(toType),
          groups: raw.plan.groups.map(toPlanGroup),
          skipped: {
            count: raw.plan.skipped.count,
            byReason: raw.plan.skipped.by_reason,
          },
        }
      : null,
    reviewPossible: (raw.review_possible ?? []).map(toPlanGroup),
    profiles: (profileJudge?.profiles ?? []).map((profile) => ({
      id: profile.id,
      roleId: profile.role_id,
      roleTitle: profile.role_title,
      markerLabel: profile.marker_label,
      confidence: profile.confidence,
      roleConfidence: profile.role_confidence,
      source: toSource(profile.source),
      evidence: profile.evidence,
      members: profile.members.map((member) => ({
        ref: member.ref,
        type: toType(member.entity.type),
        text: member.entity.text,
        normalized: member.entity.normalized,
        confidence: member.entity.confidence,
        source: toSource(member.entity.source),
        anchor: member.anchor,
      })),
    })),
    contractSummary: raw.contract_summary
      ? {
          customer: toParty(raw.contract_summary.customer),
          supplier: toParty(raw.contract_summary.supplier),
          federalLaw: raw.contract_summary.federal_law,
          contractAmount: raw.contract_summary.contract_amount,
          deliveryPeriods: raw.contract_summary.delivery_periods,
          paymentTerms: raw.contract_summary.payment_terms,
          contractNumber: raw.contract_summary.contract_number,
          generatedAt: raw.contract_summary.generated_at,
          llmCalls: raw.contract_summary.llm_calls,
          briefSummary: raw.contract_summary.brief_summary,
          documentKind: raw.contract_summary.document_kind,
        }
      : null,
    decisions: raw.decisions
      ? {
          mode: toMode(raw.decisions.mode),
          threadId: raw.decisions.thread_id,
          byRef: raw.decisions.by_ref.map((decision) => ({
            ref: decision.ref,
            action: decision.action as EntityAction,
            decidedBy: decision.decided_by as DecisionSource,
            questionId: decision.question_id,
            reason: decision.reason,
          })),
          criticalUnmasked: raw.decisions.critical_unmasked.map((item) => ({
            questionId: item.question_id,
            kind: item.kind,
            target: item.target,
            count: item.count,
          })),
          diagnostics: raw.decisions.diagnostics,
        }
      : null,
    validation: raw.validation
      ? {
          status: raw.validation.status,
          ok: raw.validation.ok ?? false,
          leakedCount: raw.validation.leaked_count ?? 0,
          residualCount: raw.validation.residual_count ?? 0,
          checkedArtifacts: raw.validation.checked_artifacts ?? [],
          certificate: toCertificate(raw.validation.certificate),
        }
      : null,
    certificate: toCertificate(raw.certificate),
    telemetry: raw.telemetry ? {
      events: raw.telemetry.events.map((event) => ({ sequence: event.sequence, node: event.node, message: event.message })),
      llm: {
        calls: raw.telemetry.llm.calls,
        promptTokens: raw.telemetry.llm.prompt_tokens,
        completionTokens: raw.telemetry.llm.completion_tokens,
        status: raw.telemetry.llm.status,
        message: raw.telemetry.llm.message,
        cost: raw.telemetry.llm.cost,
        pricing: raw.telemetry.llm.pricing,
        byNode: raw.telemetry.llm.by_node.map((item) => ({
          node: item.node,
          calls: item.calls,
          promptTokens: item.prompt_tokens,
          completionTokens: item.completion_tokens,
        })),
      },
      runtime: raw.telemetry.runtime,
    } : null,
    markerLegend: (raw.marker_legend ?? []).map((item) => ({
      shownLabel: item.shown_label,
      canonicalLabel: item.canonical_label,
      pages: item.pages,
    })),
    detectionCoverage: {
      requestedTypes: raw.detection_coverage.requested_types.map(toType),
      activeDetectorTypes:
        raw.detection_coverage.active_detector_types.map(toType),
      requestedWithoutDetector:
        raw.detection_coverage.requested_without_detector.map(toType),
    },
    limitations: raw.limitations,
    documentCoverage: raw.document_coverage,
    pages: (raw.pages ?? []).map(
      (page): PiiPage => ({
        page: page.page,
        widthPt: page.width_pt,
        heightPt: page.height_pt,
      }),
    ),
  };
}

/** Чанки берутся из исходного payload: `rawChunkSchema` уже проверил их форму. */
function payloadChunks(payload: unknown): unknown {
  return (payload as { chunks: unknown }).chunks;
}

function toParty(
  raw: z.infer<typeof rawPartySchema> | null,
): ContractParty | null {
  return raw
    ? {
        name: raw.name,
        roleTitle: raw.role_title,
        inn: raw.inn,
        ogrn: raw.ogrn,
      }
    : null;
}

/* ------------------------------------------------------------------ *
 * Конверт паузы (`questions.json`) — отдельный артефакт, не часть отчёта.
 * ------------------------------------------------------------------ */

const rawQuestionSchema = z.object({
  id: z.string(),
  kind: z.string(),
  target: z.string(),
  title: z.string(),
  prompt: z.string(),
  options: z.array(z.string()),
  default: z.string(),
  critical: z.boolean(),
  found: z.number(),
  samples: z.array(z.string()),
  // Здесь якорь — метка строкой («абзац 5»), а не объект: конверт вопросов
  // адресован человеку, а не резолверу привязки.
  anchors: z.array(z.string()),
});

const rawAskEnvelopeSchema = z.object({
  schema_version: z.number(),
  thread_id: z.string(),
  document: z.object({ name: z.string(), format: z.string() }),
  questions: z.array(rawQuestionSchema),
});

const KNOWN_QUESTION_KINDS: PolicyQuestion["kind"][] = [
  "type",
  "profile",
  "entity",
];

function toQuestionKind(value: string): PolicyQuestion["kind"] {
  return (KNOWN_QUESTION_KINDS as string[]).includes(value)
    ? (value as PolicyQuestion["kind"])
    : "entity";
}

/**
 * Вариант ответа проходит только из закрытого набора движка: любая другая
 * строка молча превратилась бы в `default` уже на бэкенде, и оператор увидел
 * бы «маскировать» там, где нажимал «оставить».
 */
function toAnswerOption(value: string): AnswerOption {
  if (value === KEEP_OPTION) return KEEP_OPTION;
  if (value === KEEP_CRITICAL_OPTION) return KEEP_CRITICAL_OPTION;
  return MASK_OPTION;
}

/**
 * Разбирает конверт паузы графа — то, что движок пишет в `questions.json`.
 * Тип входа — `AskEnvelopeOut`, сгенерированный Orval'ом из ответа
 * `GET /runs/{id}/questions` (`response_model=AskEnvelopeOut`).
 */
export function parseAskEnvelope(payload: AskEnvelopeOut): AskEnvelope {
  const raw = rawAskEnvelopeSchema.parse(payload);

  return {
    schemaVersion: raw.schema_version,
    threadId: raw.thread_id,
    document: {
      name: raw.document.name,
      format: toDocFormat(raw.document.format),
    },
    questions: raw.questions.map((question) => ({
      id: question.id,
      kind: toQuestionKind(question.kind),
      target: question.target,
      title: question.title,
      prompt: question.prompt,
      options: question.options.map(toAnswerOption),
      default: toAnswerOption(question.default),
      critical: question.critical,
      found: question.found,
      samples: question.samples,
      anchors: question.anchors,
    })),
  };
}
