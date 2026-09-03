import { describe, expect, it } from "vitest";

import { buildAnchorIndex, type AnchorOccurrenceInput } from "./anchor-index";

/** Абзац с рядом ранов: обычный текст вперемешку с уже промаскированными
 * ранами (`marker` — undefined для обычного текста). */
function paragraph(...parts: (string | { marker: string })[]): HTMLElement {
  const p = document.createElement("p");
  for (const part of parts) {
    const span = document.createElement("span");
    if (typeof part === "string") {
      span.textContent = part;
    } else {
      span.textContent = part.marker;
      span.style.backgroundColor = "rgb(0, 0, 0)";
      span.style.color = "rgb(0, 0, 0)";
    }
    p.appendChild(span);
  }
  return p;
}

function occurrence(
  id: string,
  marker: string,
  locatorHint: number,
  overrides: Partial<AnchorOccurrenceInput> = {},
): AnchorOccurrenceInput {
  return { id, marker, locatorHint, segmentOrder: locatorHint, chunkStart: 0, ...overrides };
}

describe("buildAnchorIndex", () => {
  it("привязывает обычный маркер-ран по подсказке locator", () => {
    const paragraphs = [
      paragraph("преамбула"),
      paragraph({ marker: "[ОРГАНИЗАЦИЯ-1]......." }),
    ];
    const result = buildAnchorIndex(paragraphs, [occurrence("o1", "[ОРГАНИЗАЦИЯ-1]", 1)]);

    const r = result.get("o1");
    expect(r?.status).toBe("resolved");
    if (r?.status === "resolved") {
      expect(r.paragraphIndex).toBe(1);
      expect(r.run.textContent).toBe("[ОРГАНИЗАЦИЯ-1].......");
    }
  });

  it("маркер с точками разной длины сравнивается без учёта заполнителя", () => {
    const paragraphs = [
      paragraph("КПП ", { marker: "[КПП-1]...." }),
      paragraph("e-mail: ", { marker: "[ПОЧТА].............." }),
    ];
    const result = buildAnchorIndex(paragraphs, [
      occurrence("kpp", "[КПП-1]", 0),
      occurrence("mail", "[ПОЧТА]", 1, { chunkStart: 1 }),
    ]);

    expect(result.get("kpp")?.status).toBe("resolved");
    expect(result.get("mail")?.status).toBe("resolved");
  });

  it("разруливает повтор одного маркера в одном абзаце по порядку вхождений", () => {
    // Реальный случай из test.docx (p117): [ФИО-4] встречается дважды в одном
    // предложении — оба вхождения настоящие, не дубликат парсинга.
    const paragraphs = [
      paragraph(
        "Заказчик и ",
        { marker: "[ФИО-4]............" },
        " и Исполнитель и ",
        { marker: "[ФИО-4]................" },
        " (ст. 706 ГК РФ).",
      ),
    ];
    const result = buildAnchorIndex(paragraphs, [
      occurrence("first", "[ФИО-4]", 0, { chunkStart: 0 }),
      occurrence("second", "[ФИО-4]", 0, { chunkStart: 50 }),
    ]);

    const first = result.get("first");
    const second = result.get("second");
    expect(first?.status).toBe("resolved");
    expect(second?.status).toBe("resolved");
    if (first?.status === "resolved" && second?.status === "resolved") {
      // Два разных рана, не один и тот же переиспользованный дважды.
      expect(first.run).not.toBe(second.run);
      expect(first.run.textContent?.startsWith("[ФИО-4]............")).toBe(true);
      expect(second.run.textContent?.startsWith("[ФИО-4]................")).toBe(true);
    }
  });

  it("находит маркер внутри ячейки таблицы тем же поиском по span", () => {
    const p = paragraph({ marker: "[АДРЕС-1]" });
    const table = document.createElement("table");
    const td = document.createElement("td");
    td.appendChild(p);
    table.appendChild(td);

    // querySelectorAll("p") на реальном документе достаёт абзацы внутри ячеек
    // наравне с абзацами верхнего уровня — в тесте это эмулирует сам список
    // параграфов, который передаёт вызывающий код.
    const paragraphs = [paragraph("шапка"), p];
    const result = buildAnchorIndex(paragraphs, [occurrence("addr", "[АДРЕС-1]", 1)]);

    expect(result.get("addr")?.status).toBe("resolved");
  });

  it("не найденный маркер помечается not-found, а не привязывается наугад", () => {
    const paragraphs = [paragraph("обычный текст без маркеров")];
    const result = buildAnchorIndex(paragraphs, [occurrence("missing", "[ИНН]", 0)]);

    expect(result.get("missing")?.status).toBe("not-found");
  });

  it("не найденное вхождение не двигает курсор — следующие ищутся как обычно", () => {
    const paragraphs = [
      paragraph("нет маркера"),
      paragraph({ marker: "[СЧЁТ-1]" }),
    ];
    const result = buildAnchorIndex(paragraphs, [
      occurrence("missing", "[ИНН]", 0),
      occurrence("found", "[СЧЁТ-1]", 1, { chunkStart: 1 }),
    ]);

    expect(result.get("missing")?.status).toBe("not-found");
    expect(result.get("found")?.status).toBe("resolved");
  });

  it("сбитая на середине дельта чинится следующей успешной привязкой", () => {
    // Первый маркер сдвинут на +2 относительно подсказки (напр. бэк не считал
    // пустые абзацы, которые докинула таблица). drift подхватывает сдвиг, и
    // второй маркер находится по скорректированному target, а не по прежней
    // некорректной дельте.
    const paragraphs = [
      paragraph("зазор 1"),
      paragraph("зазор 2"),
      paragraph({ marker: "[ОРГАНИЗАЦИЯ-1]" }),
      paragraph({ marker: "[ФИО-1]" }),
    ];
    const result = buildAnchorIndex(paragraphs, [
      occurrence("org", "[ОРГАНИЗАЦИЯ-1]", 0, { chunkStart: 0 }),
      occurrence("person", "[ФИО-1]", 1, { chunkStart: 1 }),
    ]);

    const org = result.get("org");
    const person = result.get("person");
    expect(org?.status).toBe("resolved");
    expect(person?.status).toBe("resolved");
    if (org?.status === "resolved" && person?.status === "resolved") {
      expect(org.paragraphIndex).toBe(2);
      // drift = 2 подхвачен, поэтому [ФИО-1] с подсказкой 1 находится в
      // абзаце 3 (1 + drift), а не ищется от исходной неверной подсказки.
      expect(person.paragraphIndex).toBe(3);
    }
  });

  it("маркер, разбитый на несколько соседних ранов, безопасно не находится", () => {
    // Известное ограничение: candidateRuns сравнивает текст одного span
    // целиком. Если бэкенд когда-нибудь отдаст маркер, разрезанный docx-preview
    // на два соседних рана (в спайке на реальном файле такого не встретилось),
    // текущая реализация помечает вхождение not-found — это безопасная
    // деградация (вхождение остаётся в панели непривязанным), а не ложная
    // привязка к постороннему рану.
    const paragraphs = [
      paragraph({ marker: "[ОРГАНИЗАЦИЯ-1" }, { marker: "]......." }),
    ];
    const result = buildAnchorIndex(paragraphs, [occurrence("org", "[ОРГАНИЗАЦИЯ-1]", 0)]);

    expect(result.get("org")?.status).toBe("not-found");
  });
});
