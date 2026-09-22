/**
 * jsdom не реализует `CSS.escape` (часть CSSOM, а не DOM) — в реальных
 * браузерах это глобальная функция, доступная всегда. Без полифилла любой
 * код, использующий `CSS.escape` при построении селектора из id
 * (`paint-run.ts`, `manual-highlight.ts`), падает только в тестах —
 * поведение приложения в браузере не отличается.
 *
 * Реализация — стандартный спек-алгоритм CSSOM (`CSS.escape()`), тот же, что
 * годами использовался как полифилл до нативной поддержки в браузерах.
 */
if (typeof globalThis.CSS === "undefined") {
  // @ts-expect-error — минимальный объект под то, что реально используется в проекте.
  globalThis.CSS = {};
}

if (typeof globalThis.CSS.escape !== "function") {
  globalThis.CSS.escape = (value: string): string => {
    const string = String(value);
    const length = string.length;
    let result = "";
    let index = -1;
    let codeUnit: number;

    while (++index < length) {
      codeUnit = string.charCodeAt(index);
      if (codeUnit === 0x0000) {
        result += "�";
        continue;
      }
      if (
        (codeUnit >= 0x0001 && codeUnit <= 0x001f) ||
        codeUnit === 0x007f ||
        (index === 0 && codeUnit >= 0x0030 && codeUnit <= 0x0039) ||
        (index === 1 &&
          codeUnit >= 0x0030 &&
          codeUnit <= 0x0039 &&
          string.charCodeAt(0) === 0x002d)
      ) {
        result += `\\${codeUnit.toString(16)} `;
        continue;
      }
      if (
        index === 0 &&
        length === 1 &&
        codeUnit === 0x002d
      ) {
        result += `\\${string.charAt(index)}`;
        continue;
      }
      if (
        codeUnit >= 0x0080 ||
        codeUnit === 0x002d ||
        codeUnit === 0x005f ||
        (codeUnit >= 0x0030 && codeUnit <= 0x0039) ||
        (codeUnit >= 0x0041 && codeUnit <= 0x005a) ||
        (codeUnit >= 0x0061 && codeUnit <= 0x007a)
      ) {
        result += string.charAt(index);
        continue;
      }
      result += `\\${string.charAt(index)}`;
    }
    return result;
  };
}
