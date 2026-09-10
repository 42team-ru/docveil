/**
 * Привязка вхождений ПДн к уже промаскированным ранам в отрендеренном docx.
 *
 * Ключевой факт, подтверждённый спайком на реальном документе заказчика:
 * DOM не содержит исходного текста ПДн — маркер (`[ЗАКАЗЧИК-ИНН]` и т.п.) уже
 * вписан в документ бэкендом как обычный текстовый ран, дополненный до
 * исходной длины. Поэтому задача не «вырезать диапазон символов по офсетам»,
 * а «найти уже готовый ран с точным текстом маркера» — точное совпадение
 * строки, а не эвристика.
 *
 * Локаторов у docx два, и путать их нельзя (`iter_body_blocks`,
 * `backend/src/masker/ingest/docx_ingest.py`):
 *
 * - `["body", N]` — `N` — физический индекс среди **прямых** `w:p` тела
 *   документа; пустые абзацы посчитаны, абзацы внутри таблиц — нет. Точного
 *   соответствия с DOM нет (docx-preview добавляет и опускает узлы), поэтому
 *   здесь работает монотонное выравнивание: подсказка плюс `drift`,
 *   пересчитываемый на каждой успешной привязке, и `cursor`, запрещающий
 *   искать раньше уже привязанного абзаца.
 * - `["table", t, r, c, p]` — `t`-я **верхнеуровневая** таблица, `r`-я строка,
 *   `c`-я ячейка, `p`-й абзац внутри неё. Здесь адрес точный, и гадать не
 *   нужно: до этой правки `locator[1]` читался как номер абзаца, то есть для
 *   ячейки в качестве подсказки бралcя индекс таблицы — в тендерных договорах
 *   реквизиты сторон почти всегда в таблице, и такие вхождения либо не
 *   находились, либо цеплялись к чужому рану.
 *
 * `drift`/`cursor` двигают только попадания в тело: табличные абзацы живут в
 * своей системе координат и подсказку для следующего абзаца тела сбивать не
 * должны.
 */

/** Разобранный `anchor.locator` документа docx. */
export type AnchorHint =
  | { kind: "body"; index: number }
  | { kind: "table"; table: number; row: number; cell: number; para: number };

export type AnchorResolution =
  | { status: "resolved"; paragraphIndex: number; run: HTMLElement }
  | { status: "not-found" };

export type AnchorOccurrenceInput = {
  id: string;
  marker: string;
  /** Разобранный локатор от бэкенда. */
  hint: AnchorHint;
  /** Порядок в документе для сортировки перед выравниванием. */
  segmentOrder: number;
  chunkStart: number;
};

/**
 * Структура отрендеренного документа в терминах локаторов бэкенда. Собирает её
 * вьюер (`docx-viewer.tsx`), потому что это знание про DOM docx-preview, а не
 * про привязку.
 */
export type DocxOutline = {
  /** Абзацы тела: `<p>` без предка `<table>`, в порядке документа. */
  bodyParagraphs: HTMLElement[];
  /** Верхнеуровневые таблицы: `<table>` без предка `<table>`, в порядке документа. */
  tables: HTMLElement[];
};

/** Насколько далеко от подсказки допустимо искать ран, в абзацах. */
const SEARCH_WINDOW = 8;

/**
 * Индекс, под которым табличные привязки лежат в карте занятых ранов. Реальный
 * номер абзаца им не нужен — важно лишь не выдать один и тот же ран дважды, а
 * ячейки адресуются точно и между собой не пересекаются.
 */
const TABLE_PARAGRAPH_INDEX = -1;

/** Разобрать `anchor.locator` в подсказку. Неизвестная форма — `null`. */
export function parseDocxLocator(locator: (string | number)[]): AnchorHint | null {
  if (locator[0] === "body" && Number.isFinite(Number(locator[1]))) {
    return { kind: "body", index: Number(locator[1]) };
  }

  if (locator[0] === "table" && locator.length === 5) {
    const [, table, row, cell, para] = locator.map(Number);
    if ([table, row, cell, para].every(Number.isFinite)) {
      return { kind: "table", table, row, cell, para };
    }
  }

  return null;
}

function stripPadding(text: string): string {
  // blackbox добивает маркер точками, marker — неразрывными пробелами; `trim`
  // снимает и NBSP, поэтому обе формы заполнителя сравниваются одинаково.
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

function matchInParagraph(
  paragraph: Element | undefined,
  used: Set<HTMLElement> | undefined,
  marker: string,
): HTMLElement | null {
  if (!paragraph) return null;
  for (const run of candidateRuns(paragraph)) {
    if (used?.has(run)) continue;
    if (stripPadding(run.textContent ?? "") !== marker) continue;
    return run;
  }
  return null;
}

function findInBody(
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
      const run = matchInParagraph(
        paragraphs[paragraphIndex],
        occupied.get(paragraphIndex),
        marker,
      );
      if (run) return { paragraphIndex, run };
    }
  }

  return null;
}

/**
 * Абзац внутри ячейки таблицы по точному адресу. Ничего не ищет вокруг: если
 * адреса нет в DOM, это расхождение с документом, а не повод привязаться к
 * соседней ячейке.
 */
function cellParagraph(
  tables: HTMLElement[],
  hint: Extract<AnchorHint, { kind: "table" }>,
): HTMLElement | undefined {
  const table = tables[hint.table];
  if (!table) return undefined;

  const rows = Array.from(table.querySelectorAll("tr")).filter(
    (row) => row.closest("table") === table,
  );
  const row = rows[hint.row];
  if (!row) return undefined;

  const cells = Array.from(row.children).filter(
    (cell) => cell.tagName === "TD" || cell.tagName === "TH",
  );
  const cell = cells[hint.cell];
  if (!cell) return undefined;

  const paragraphs = Array.from(cell.querySelectorAll("p")).filter(
    (paragraph) => paragraph.closest("td, th") === cell,
  );
  return paragraphs[hint.para];
}

/**
 * Строит привязку occurrence → ран для всего документа. Не React, не
 * побочные эффекты кроме чтения DOM — чистая функция, покрыта тестами.
 */
export function buildAnchorIndex(
  outline: DocxOutline,
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

  const remember = (paragraphIndex: number, run: HTMLElement) => {
    const set = occupied.get(paragraphIndex) ?? new Set<HTMLElement>();
    set.add(run);
    occupied.set(paragraphIndex, set);
  };

  for (const occurrence of ordered) {
    if (occurrence.hint.kind === "table") {
      const paragraph = cellParagraph(outline.tables, occurrence.hint);
      const run = matchInParagraph(
        paragraph,
        occupied.get(TABLE_PARAGRAPH_INDEX),
        occurrence.marker,
      );

      if (!run) {
        result.set(occurrence.id, { status: "not-found" });
        continue;
      }

      remember(TABLE_PARAGRAPH_INDEX, run);
      result.set(occurrence.id, {
        status: "resolved",
        paragraphIndex: TABLE_PARAGRAPH_INDEX,
        run,
      });
      continue;
    }

    const target = occurrence.hint.index + drift;
    const found = findInBody(
      outline.bodyParagraphs,
      occupied,
      occurrence.marker,
      target,
      cursor,
    );

    if (!found) {
      result.set(occurrence.id, { status: "not-found" });
      continue;
    }

    remember(found.paragraphIndex, found.run);

    drift = found.paragraphIndex - occurrence.hint.index;
    cursor = found.paragraphIndex;

    result.set(occurrence.id, {
      status: "resolved",
      paragraphIndex: found.paragraphIndex,
      run: found.run,
    });
  }

  return result;
}
