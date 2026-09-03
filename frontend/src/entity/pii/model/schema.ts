import { z } from "zod";

import type {
  PiiChunk,
  PiiDocFormat,
  PiiExtraction,
  PiiOccurrence,
  PiiSource,
  PiiType,
} from "./types";

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

const rawPiiSchema = z.object({
  ref: z.string(),
  group_id: z.string(),
  marker: z.string(),
  type: z.string(),
  text: z.string(),
  normalized: z.string(),
  confidence: z.number(),
  source: z.string(),
  segment_order: z.number(),
  chunk_start: z.number(),
  chunk_end: z.number(),
  anchor: rawAnchorSchema,
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

const KNOWN_FORMATS: PiiDocFormat[] = ["docx", "pdf", "xlsx"];
const KNOWN_SOURCES: PiiSource[] = ["ner", "rule"];

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

/** Тип неизвестный бэкенду проходит как есть — UI решит, как его подписать. */
function toType(value: string): PiiType {
  return value as PiiType;
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
        type: toType(pii.type),
        text: pii.text,
        normalized: pii.normalized,
        confidence: pii.confidence,
        source: toSource(pii.source),
        segmentOrder: pii.segment_order,
        chunkStart: pii.chunk_start,
        chunkEnd: pii.chunk_end,
      }),
    ),
  }));

  return { chunkCount: raw.chunk_count, chunks };
}
