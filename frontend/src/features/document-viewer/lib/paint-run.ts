import type { PiiDecisionKind } from "../../../entity/pii/model/types";

/**
 * Ран уже стоит в DOM как непрозрачный чёрный редакт (`w:shd fill="000000"`
 * из исходного docx). Наша работа — не добавить подсветку, а перекрасить уже
 * существующий ран в статусный цвет. Токены берём напрямую через CSS custom
 * properties — так уже сделано для выделения строки в
 * прежней строке списка масок (`var(--color-accent)` и т.п.), это
 * принятый в проекте способ ссылаться на токены там, где нет подходящего
 * пропа компонента. Tailwind-утилиты вроде `bg-yellow-subtle` здесь не
 * применимы: `tailwind-theme.css` в проекте пока нигде не импортирован
 * (`src/app/styles/app.css` тянет только reset/astryx/theme), чинить это
 * попутно — отдельная, не относящаяся к задаче правка.
 *
 * `"original"` — режим тулбара «Оригинал»: не перекрашивает исходный текст
 * preview-артефакта и не скрывает его.
 */
export type PaintState = PiiDecisionKind | "original";

const STATUS_STYLE: Record<
  PaintState,
  { background: string; color: string; strike: boolean }
> = {
  pending: {
    background: "var(--color-background-yellow)",
    color: "var(--color-text-yellow)",
    strike: false,
  },
  confirmed: {
    background: "var(--color-background-green)",
    color: "var(--color-text-green)",
    strike: false,
  },
  rejected: {
    background: "var(--color-background-gray)",
    color: "var(--color-text-gray)",
    strike: true,
  },
  original: {
    background: "transparent",
    color: "inherit",
    strike: false,
  },
};

function applyPaintStyle(
  el: HTMLElement,
  style: { background: string; color: string; strike: boolean },
  isSelected: boolean,
): void {
  el.style.backgroundColor = style.background;
  el.style.color = style.color;
  el.style.textDecoration = style.strike ? "line-through" : "none";
  el.style.borderRadius = "2px";
  el.style.cursor = "pointer";
  el.style.outline = isSelected ? "3px solid var(--color-border-blue)" : "none";
  el.style.outlineOffset = "2px";
}

export function paintRun(
  run: HTMLElement,
  state: PaintState,
  isSelected: boolean,
): void {
  // bbox overlay divs sit on top of the PDF canvas — the PDF artifact already
  // has its own visual highlighting. Only show the selection outline, no fill.
  const effectiveState: PaintState = run.dataset.piiBbox ? "original" : state;
  const style = STATUS_STYLE[effectiveState];
  applyPaintStyle(run, style, isSelected);
  // Дополнительные region-div'ы для bbox-вьюера (одна сущность → N строк в PDF).
  // Они хранятся рядом на том же page-контейнере с атрибутом `data-pii-region-of`.
  const ownId = run.dataset.piiId;
  if (ownId && run.parentElement) {
    const extras = run.parentElement.querySelectorAll<HTMLElement>(
      `[data-pii-region-of="${CSS.escape(ownId)}"]`,
    );
    for (const extra of extras) {
      applyPaintStyle(extra, style, isSelected);
    }
  }
}
