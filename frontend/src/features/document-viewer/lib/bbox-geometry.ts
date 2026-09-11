import type { PiiPage, PiiRegion } from "../../../entity/pii/model/types";

/** Прямоугольник в пикселях страницы (CSS px, тот же базис, что и у
 * `canvas.clientWidth/clientHeight` — не backing-store `canvas.width`). */
export type PixelRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/**
 * Первый (представительный) регион вхождения. Сущность, перенесённая через
 * границу страницы, даёт две записи (`masker/highlights`, план К1) — второй
 * регион здесь не интерактивен: редкий случай, не годовой ценой поддержки
 * второго якоря на одно вхождение.
 */
export function primaryRegion(regions: PiiRegion[]): PiiRegion | null {
  return regions[0] ?? null;
}

/** 0..1-регион → прямоугольник в CSS-пикселях страницы заданного размера. */
export function regionToPixelRect(
  region: PiiRegion,
  pageWidthPx: number,
  pageHeightPx: number,
): PixelRect {
  const x0 = clamp01(region.x0);
  const y0 = clamp01(region.y0);
  const x1 = clamp01(region.x1);
  const y1 = clamp01(region.y1);
  return {
    x: Math.min(x0, x1) * pageWidthPx,
    y: Math.min(y0, y1) * pageHeightPx,
    width: Math.abs(x1 - x0) * pageWidthPx,
    height: Math.abs(y1 - y0) * pageHeightPx,
  };
}

/** Обратное преобразование — прямоугольник протяжки мышью → регион 0..1. */
export function pixelRectToRegion(
  rect: PixelRect,
  page: number,
  pageWidthPx: number,
  pageHeightPx: number,
): PiiRegion {
  if (pageWidthPx <= 0 || pageHeightPx <= 0) {
    throw new Error(
      `pixelRectToRegion: страница без размера (${pageWidthPx}x${pageHeightPx})`,
    );
  }
  const x0 = clamp01(rect.x / pageWidthPx);
  const y0 = clamp01(rect.y / pageHeightPx);
  const x1 = clamp01((rect.x + rect.width) / pageWidthPx);
  const y1 = clamp01((rect.y + rect.height) / pageHeightPx);
  return { page, x0, y0, x1, y1 };
}

/**
 * Прямоугольник протяжки мышью: точки может дать в любом порядке (тянуть
 * можно в любую сторону от точки начала) — здесь всегда `x/y` левого
 * верхнего угла и неотрицательные `width/height`.
 */
export function normalizeDragRect(
  x0: number,
  y0: number,
  x1: number,
  y1: number,
): PixelRect {
  return {
    x: Math.min(x0, x1),
    y: Math.min(y0, y1),
    width: Math.abs(x1 - x0),
    height: Math.abs(y1 - y0),
  };
}

/** `report.pages[]` → быстрый поиск размеров по номеру страницы. */
export function pageDimsByNumber(pages: PiiPage[]): Map<number, PiiPage> {
  return new Map(pages.map((page) => [page.page, page]));
}
