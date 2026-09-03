/**
 * Привязка вхождений ПДн к уже промаскированным ранам в отрендеренном docx.
 *
 * Ключевой факт, подтверждённый спайком на реальном документе заказчика:
 * DOM не содержит исходного текста ПДн — маркер (`[ФИО-1]` и т.п.) уже вписан
 * в документ бэкендом как обычный текстовый ран, дополненный точками до
 * исходной длины. Поэтому задача не «вырезать диапазон символов по офсетам»,
 * а «найти уже готовый ран с точным текстом маркера» — точное совпадение
 * строки, а не эвристика.
 *
 * Правило поиска — монотонное выравнивание: `anchor.locator` даёт подсказку
 * по абзацу, `drift` (расхождение подсказки и найденного индекса) пересчиты-
 * вается на каждой успешной привязке и живёт один шаг, `cursor` запрещает
 * искать раньше уже привязанного абзаца — так повтор одного маркера в одном
 * документе (напр. один и тот же [ФИО-4] дважды в одном абзаце) разбирается
 * по порядку вхождений, а не хватает случайный дубликат.
 */

export type AnchorResolution =
  | { status: "resolved"; paragraphIndex: number; run: HTMLElement }
  | { status: "not-found" };

export type AnchorOccurrenceInput = {
  id: string;
  marker: string;
  /** anchor.locator[1] — номер абзаца-подсказки от бэкенда. */
  locatorHint: number;
  /** Порядок в документе для сортировки перед выравниванием. */
  segmentOrder: number;
  chunkStart: number;
};

/** Насколько далеко от подсказки допустимо искать ран, в абзацах. */
const SEARCH_WINDOW = 8;

function stripDots(text: string): string {
  return text.replace(/\.+\s*$/, "").trim();
}

function isLeafSpan(el: Element): el is HTMLElement {
  return el.tagName === "SPAN" && el.children.length === 0;
}

/** Раны-кандидаты внутри абзаца, в порядке документа. docx-preview рендерит
 * каждый w:r как отдельный лист-span без вложенных элементов — это же верно
 * для ранов внутри ячеек таблиц, отдельной ветки для них не нужно. */
function candidateRuns(paragraph: Element): HTMLElement[] {
  return Array.from(paragraph.querySelectorAll("span")).filter(isLeafSpan);
}

function findRun(
  paragraphs: HTMLElement[],
  occupied: Map<number, Set<HTMLElement>>,
  marker: string,
  target: number,
  cursor: number,
): { paragraphIndex: number; run: HTMLElement } | null {
  for (let radius = 0; radius <= SEARCH_WINDOW; radius++) {
    const indices = radius === 0 ? [target] : [target - radius, target + radius];

    for (const paragraphIndex of indices) {
      if (paragraphIndex < cursor) continue;
      const paragraph = paragraphs[paragraphIndex];
      if (!paragraph) continue;

      const used = occupied.get(paragraphIndex);
      for (const run of candidateRuns(paragraph)) {
        if (used?.has(run)) continue;
        if (stripDots(run.textContent ?? "") !== marker) continue;
        return { paragraphIndex, run };
      }
    }
  }

  return null;
}

/**
 * Строит привязку occurrence → ран для всего документа. Не React, не
 * побочные эффекты кроме чтения DOM — чистая функция, покрыта тестами.
 */
export function buildAnchorIndex(
  paragraphs: HTMLElement[],
  occurrences: AnchorOccurrenceInput[],
): Map<string, AnchorResolution> {
  const ordered = [...occurrences].sort((a, b) =>
    a.segmentOrder !== b.segmentOrder
      ? a.segmentOrder - b.segmentOrder
      : a.chunkStart - b.chunkStart,
  );

  const occupied = new Map<number, Set<HTMLElement>>();
  const result = new Map<string, AnchorResolution>();

  let cursor = 0;
  let drift = 0;

  for (const occurrence of ordered) {
    const target = occurrence.locatorHint + drift;
    const found = findRun(paragraphs, occupied, occurrence.marker, target, cursor);

    if (!found) {
      result.set(occurrence.id, { status: "not-found" });
      continue;
    }

    const set = occupied.get(found.paragraphIndex) ?? new Set<HTMLElement>();
    set.add(found.run);
    occupied.set(found.paragraphIndex, set);

    drift = found.paragraphIndex - occurrence.locatorHint;
    cursor = found.paragraphIndex;

    result.set(occurrence.id, {
      status: "resolved",
      paragraphIndex: found.paragraphIndex,
      run: found.run,
    });
  }

  return result;
}
