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
 * `"redacted"` — режим тулбара «Оригинал»/«Только замены»: возвращает ран к
 * исходному виду чёрного редакта, будто подсветки нет вовсе.
 */
export type PaintState = PiiDecisionKind | "redacted";

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
  redacted: {
    background: "rgb(0, 0, 0)",
    color: "rgb(0, 0, 0)",
    strike: false,
  },
};

export function paintRun(
  run: HTMLElement,
  state: PaintState,
  isSelected: boolean,
): void {
  const style = STATUS_STYLE[state];
  run.style.backgroundColor = style.background;
  run.style.color = style.color;
  run.style.textDecoration = style.strike ? "line-through" : "none";
  run.style.borderRadius = "2px";
  run.style.cursor = "pointer";
  run.style.outline = isSelected ? "3px solid var(--color-border-blue)" : "none";
  run.style.outlineOffset = "2px";
}
