import { describe, expect, it } from "vitest";

import {
  normalizeDragRect,
  pageDimsByNumber,
  pixelRectToRegion,
  primaryRegion,
  regionToPixelRect,
} from "./bbox-geometry";

describe("regionToPixelRect / pixelRectToRegion", () => {
  it("переводит регион 0..1 в пиксели страницы и обратно без потерь", () => {
    const region = { page: 2, x0: 0.1, y0: 0.2, x1: 0.5, y1: 0.3 };

    const rectPx = regionToPixelRect(region, 1000, 2000);
    expect(rectPx.x).toBeCloseTo(100);
    expect(rectPx.y).toBeCloseTo(400);
    expect(rectPx.width).toBeCloseTo(400);
    expect(rectPx.height).toBeCloseTo(200);

    const back = pixelRectToRegion(rectPx, 2, 1000, 2000);
    expect(back.page).toBe(2);
    expect(back.x0).toBeCloseTo(region.x0);
    expect(back.y0).toBeCloseTo(region.y0);
    expect(back.x1).toBeCloseTo(region.x1);
    expect(back.y1).toBeCloseTo(region.y1);
  });

  it("зажимает координаты вне 0..1", () => {
    const rectPx = regionToPixelRect(
      { page: 0, x0: -0.5, y0: 0, x1: 1.5, y1: 1 },
      100,
      100,
    );
    expect(rectPx).toEqual({ x: 0, y: 0, width: 100, height: 100 });
  });

  it("не переставляет x0/x1 местами, если они уже перепутаны", () => {
    // x0 > x1 в исходных данных быть не должно (бэкенд валидирует), но
    // функция не должна тихо выдать отрицательную ширину.
    const rectPx = regionToPixelRect({ page: 0, x0: 0.8, y0: 0, x1: 0.2, y1: 1 }, 100, 100);
    expect(rectPx.x).toBeCloseTo(20);
    expect(rectPx.width).toBeCloseTo(60);
  });

  it("pixelRectToRegion бросает на странице нулевого размера", () => {
    expect(() =>
      pixelRectToRegion({ x: 0, y: 0, width: 10, height: 10 }, 0, 0, 0),
    ).toThrow(/размера/);
  });
});

describe("normalizeDragRect", () => {
  it("нормализует протяжку в любом направлении к левому верхнему углу", () => {
    expect(normalizeDragRect(50, 50, 10, 10)).toEqual({
      x: 10,
      y: 10,
      width: 40,
      height: 40,
    });
    expect(normalizeDragRect(10, 10, 50, 50)).toEqual({
      x: 10,
      y: 10,
      width: 40,
      height: 40,
    });
    expect(normalizeDragRect(10, 50, 50, 10)).toEqual({
      x: 10,
      y: 10,
      width: 40,
      height: 40,
    });
  });
});

describe("primaryRegion", () => {
  it("берёт первый регион вхождения", () => {
    const regions = [
      { page: 0, x0: 0, y0: 0, x1: 0.1, y1: 0.1 },
      { page: 1, x0: 0, y0: 0, x1: 0.1, y1: 0.1 },
    ];
    expect(primaryRegion(regions)).toBe(regions[0]);
  });

  it("null для вхождения без regions", () => {
    expect(primaryRegion([])).toBeNull();
  });
});

describe("pageDimsByNumber", () => {
  it("строит быстрый поиск по номеру страницы", () => {
    const pages = [
      { page: 0, widthPt: 595, heightPt: 842 },
      { page: 1, widthPt: 595, heightPt: 842 },
    ];
    const byNumber = pageDimsByNumber(pages);
    expect(byNumber.get(0)).toEqual(pages[0]);
    expect(byNumber.get(5)).toBeUndefined();
  });
});
