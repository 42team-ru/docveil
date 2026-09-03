import type { PiiAnchor, PiiExtraction, PiiSource, PiiType } from "./types";

/**
 * Плоское вхождение — join чанка и одного его pii-элемента. Общая точка входа
 * и для `features/document-viewer` (нужны id/marker/groupId/anchor для
 * привязки к DOM), и для `features/pii-review` (нужны type/confidence/source
 * для списка) — обе фичи читают её из сущности, не друг у друга, как того
 * требует ARCHITECTURE.md.
 *
 * Несёт весь `anchor` целиком, а не разобранный «номер абзаца»: формат
 * локатора у docx (`["body", N]`) и xlsx (`["sheet", имя, row, col]`)
 * настолько разный, что разбирать его здесь означало бы протащить
 * docx-специфичную интерпретацию в формат-агностичную сущность. Разбор —
 * дело конкретного резолвера привязки (`anchor-index.ts` для docx,
 * `xlsx-anchor-index.ts` для xlsx).
 */
export type FlatPiiOccurrence = {
  id: string;
  chunkId: string;
  groupId: string;
  marker: string;
  type: PiiType;
  confidence: number;
  source: PiiSource;
  /** Правдоподобный текст до маскирования — из JSON, в самом документе его нет. */
  originalText: string;
  normalized: string;
  anchor: PiiAnchor;
  segmentOrder: number;
  chunkStart: number;
  chunkEnd: number;
};

/** В JSON бэкенда нет своего id вхождения — синтезируем детерминированно. */
export function occurrenceId(
  chunkId: string,
  segmentOrder: number,
  chunkStart: number,
  chunkEnd: number,
): string {
  return `${chunkId}:${segmentOrder}:${chunkStart}-${chunkEnd}`;
}

export function flattenPiiOccurrences(
  extraction: PiiExtraction,
): FlatPiiOccurrence[] {
  const result: FlatPiiOccurrence[] = [];

  for (const chunk of extraction.chunks) {
    for (const pii of chunk.pii) {
      result.push({
        id: occurrenceId(chunk.id, pii.segmentOrder, pii.chunkStart, pii.chunkEnd),
        chunkId: chunk.id,
        groupId: pii.groupId,
        marker: pii.marker,
        type: pii.type,
        confidence: pii.confidence,
        source: pii.source,
        originalText: pii.text,
        normalized: pii.normalized,
        anchor: chunk.anchor,
        segmentOrder: pii.segmentOrder,
        chunkStart: pii.chunkStart,
        chunkEnd: pii.chunkEnd,
      });
    }
  }

  return result;
}

export function groupOccurrences(
  occurrences: FlatPiiOccurrence[],
): Map<string, FlatPiiOccurrence[]> {
  const map = new Map<string, FlatPiiOccurrence[]>();

  for (const occurrence of occurrences) {
    const list = map.get(occurrence.groupId) ?? [];
    list.push(occurrence);
    map.set(occurrence.groupId, list);
  }

  return map;
}
