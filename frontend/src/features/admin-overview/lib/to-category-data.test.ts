import { describe, expect, it } from "vitest";

import {
  documentFormatCategoryData,
  maskStyleCategoryData,
  runStatusCategoryData,
} from "./to-category-data";

describe("runStatusCategoryData", () => {
  it("подписывает статусы по-русски и держит порядок конвейера", () => {
    const data = runStatusCategoryData({ failed: 2, done: 5, queued: 1 });
    expect(data.map((item) => item.key)).toEqual(["queued", "done", "failed"]);
    expect(data.find((item) => item.key === "done")?.label).toBe("готов");
  });

  it("отбрасывает нулевые статусы", () => {
    const data = runStatusCategoryData({ done: 3, failed: 0 });
    expect(data).toHaveLength(1);
  });
});

describe("documentFormatCategoryData", () => {
  it("подписывает формат верхним регистром и сортирует по убыванию", () => {
    const data = documentFormatCategoryData({ pdf: 10, docx: 20 });
    expect(data[0]).toMatchObject({ key: "docx", label: "DOCX", count: 20 });
    expect(data[1]).toMatchObject({ key: "pdf", label: "PDF", count: 10 });
  });
});

describe("maskStyleCategoryData", () => {
  it("подписывает известные стили маскирования по-русски", () => {
    const data = maskStyleCategoryData({ marker: 4, blackbox: 1 });
    expect(data.find((item) => item.key === "marker")?.label).toBe("Маркер");
    expect(data.find((item) => item.key === "blackbox")?.label).toBe(
      "Чёрный прямоугольник",
    );
  });
});
