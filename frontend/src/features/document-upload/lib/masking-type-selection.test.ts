import { describe, expect, it } from "vitest";

import {
  areAllTypesSelected,
  hasAnyTypeSelected,
  toggleAllTypes,
  updateTypeSelection,
} from "./masking-type-selection";

describe("выбор типов маскирования", () => {
  it("снимает все типы в пустой список, а не превращает пустой список во все", () => {
    const cleared = toggleAllTypes(null);

    expect(cleared).toEqual([]);
    expect(areAllTypesSelected(cleared)).toBe(false);
    expect(toggleAllTypes(cleared)).toBeNull();
  });

  it("сворачивает полный ручной выбор в состояние «все типы»", () => {
    expect(updateTypeSelection(["inn"], "phone", true, ["inn", "phone"]))
      .toBeNull();
  });

  it("не разрешает запуск без встроенных и пользовательских типов", () => {
    expect(hasAnyTypeSelected([], 0)).toBe(false);
    expect(hasAnyTypeSelected(["inn"], 0)).toBe(true);
    expect(hasAnyTypeSelected([], 1)).toBe(true);
    expect(hasAnyTypeSelected(null, 0)).toBe(true);
  });
});
