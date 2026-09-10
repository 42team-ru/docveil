import { describe, expect, it } from "vitest";

import {
  buildAnchorIndex,
  parseDocxLocator,
  type AnchorOccurrenceInput,
  type DocxOutline,
} from "./anchor-index";

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

/** Таблица из строк, каждая строка — список ячеек, ячейка — список абзацев. */
function table(...rows: HTMLElement[][][]): HTMLElement {
  const tableEl = document.createElement("table");
  for (const cells of rows) {
    const tr = document.createElement("tr");
    for (const paragraphs of cells) {
      const td = document.createElement("td");
      for (const p of paragraphs) td.appendChild(p);
      tr.appendChild(td);
    }
    tableEl.appendChild(tr);
  }
  return tableEl;
}

function outline(
  bodyParagraphs: HTMLElement[],
  tables: HTMLElement[] = [],
): DocxOutline {
  return { bodyParagraphs, tables };
}

function occurrence(
  id: string,
  marker: string,
  index: number,
  overrides: Partial<AnchorOccurrenceInput> = {},
): AnchorOccurrenceInput {
  return {
    id,
    marker,
    hint: { kind: "body", index },
    segmentOrder: index,
    chunkStart: 0,
    ...overrides,
  };
}

function inCell(
  id: string,
  marker: string,
  cell: { table: number; row: number; cell: number; para: number },
  overrides: Partial<AnchorOccurrenceInput> = {},
): AnchorOccurrenceInput {
  return {
    id,
    marker,
    hint: { kind: "table", ...cell },
    segmentOrder: 0,
    chunkStart: 0,
    ...overrides,
  };
}

describe("parseDocxLocator", () => {
  it("разбирает обе формы локатора docx", () => {
    expect(parseDocxLocator(["body", 7])).toEqual({ kind: "body", index: 7 });
    expect(parseDocxLocator(["table", 0, 1, 2, 3])).toEqual({
      kind: "table",
      table: 0,
      row: 1,
      cell: 2,
      para: 3,
    });
  });

  it("неизвестную форму не выдаёт за абзац", () => {
    // До правки `locator[1]` читался как номер абзаца независимо от формы,
    // поэтому pdf-локатор молча превращался в подсказку «абзац 3».
    expect(parseDocxLocator(["page", 3, 10, 40])).toBeNull();
    expect(parseDocxLocator(["sheet", "Реестр", 4, 2])).toBeNull();
    expect(parseDocxLocator(["table", 0, 1])).toBeNull();
  });
});

describe("buildAnchorIndex", () => {
  it("привязывает обычный маркер-ран по подсказке locator", () => {
    const paragraphs = [
      paragraph("преамбула"),
      paragraph({ marker: "[ОРГАНИЗАЦИЯ-1]......." }),
    ];
    const result = buildAnchorIndex(outline(paragraphs), [
      occurrence("o1", "[ОРГАНИЗАЦИЯ-1]", 1),
    ]);

    const r = result.get("o1");
    expect(r?.status).toBe("resolved");
    if (r?.status === "resolved") {
      expect(r.paragraphIndex).toBe(1);
      expect(r.run.textContent).toBe("[ОРГАНИЗАЦИЯ-1].......");
    }
  });

  it("маркер с заполнителем сравнивается без учёта хвоста", () => {
    const paragraphs = [
      paragraph("КПП ", { marker: "[КПП-1]...." }),
      // marker-стиль добивает неразрывными пробелами, а не точками.
      paragraph("e-mail: ", { marker: "[ПОЧТА]    " }),
    ];
    const result = buildAnchorIndex(outline(paragraphs), [
      occurrence("kpp", "[КПП-1]", 0),
      occurrence("mail", "[ПОЧТА]", 1, { chunkStart: 1 }),
    ]);

    expect(result.get("kpp")?.status).toBe("resolved");
    expect(result.get("mail")?.status).toBe("resolved");
  });

  it("разруливает повтор одного маркера в одном абзаце по порядку вхождений", () => {
    const paragraphs = [
      paragraph(
        "Заказчик и ",
        { marker: "[ФИО-4]............" },
        " и Исполнитель и ",
        { marker: "[ФИО-4]................" },
        " (ст. 706 ГК РФ).",
      ),
    ];
    const result = buildAnchorIndex(outline(paragraphs), [
      occurrence("first", "[ФИО-4]", 0, { chunkStart: 0 }),
      occurrence("second", "[ФИО-4]", 0, { chunkStart: 50 }),
    ]);

    const first = result.get("first");
    const second = result.get("second");
    expect(first?.status).toBe("resolved");
    expect(second?.status).toBe("resolved");
    if (first?.status === "resolved" && second?.status === "resolved") {
      expect(first.run).not.toBe(second.run);
      expect(first.run.textContent?.startsWith("[ФИО-4]............")).toBe(true);
      expect(second.run.textContent?.startsWith("[ФИО-4]................")).toBe(true);
    }
  });

  it("находит маркер в ячейке таблицы по точному адресу локатора", () => {
    // Реальный случай из contract_08_roles.docx:
    // locator ["table", 0, 0, 0, 0], маркер [ИСПОЛНИТЕЛЬ-ТЕЛЕФОН].
    const target = paragraph("Телефон: ", { marker: "[ИСПОЛНИТЕЛЬ-ТЕЛЕФОН]" });
    const tables = [
      table(
        [[target], [paragraph("вторая ячейка")]],
        [[paragraph("вторая строка")]],
      ),
    ];
    const result = buildAnchorIndex(outline([paragraph("шапка")], tables), [
      inCell("phone", "[ИСПОЛНИТЕЛЬ-ТЕЛЕФОН]", {
        table: 0,
        row: 0,
        cell: 0,
        para: 0,
      }),
    ]);

    const r = result.get("phone");
    expect(r?.status).toBe("resolved");
    if (r?.status === "resolved") expect(r.run).toBe(target.querySelector("span:last-child"));
  });

  it("одинаковые маркеры в разных ячейках не путаются", () => {
    const first = paragraph({ marker: "[ЗАКАЗЧИК-ИНН]" });
    const second = paragraph({ marker: "[ЗАКАЗЧИК-ИНН]" });
    const tables = [table([[first], [second]])];

    const result = buildAnchorIndex(outline([], tables), [
      inCell("a", "[ЗАКАЗЧИК-ИНН]", { table: 0, row: 0, cell: 0, para: 0 }),
      inCell("b", "[ЗАКАЗЧИК-ИНН]", { table: 0, row: 0, cell: 1, para: 0 }, {
        chunkStart: 1,
      }),
    ]);

    const a = result.get("a");
    const b = result.get("b");
    expect(a?.status).toBe("resolved");
    expect(b?.status).toBe("resolved");
    if (a?.status === "resolved" && b?.status === "resolved") {
      expect(a.run).not.toBe(b.run);
      expect(first.contains(a.run)).toBe(true);
      expect(second.contains(b.run)).toBe(true);
    }
  });

  it("вторая таблица адресуется своим индексом", () => {
    const target = paragraph({ marker: "[ИСПОЛНИТЕЛЬ-СЧЁТ]" });
    const tables = [
      table([[paragraph("первая таблица")]]),
      table([[target]]),
    ];

    const result = buildAnchorIndex(outline([], tables), [
      inCell("acc", "[ИСПОЛНИТЕЛЬ-СЧЁТ]", { table: 1, row: 0, cell: 0, para: 0 }),
    ]);

    expect(result.get("acc")?.status).toBe("resolved");
  });

  it("табличная привязка не сбивает drift для следующих абзацев тела", () => {
    // Абзацы тела сдвинуты на +1 относительно подсказки; между ними вклинилось
    // вхождение из таблицы. Оно живёт в своей системе координат и не должно
    // ни двигать cursor, ни портить drift.
    const paragraphs = [
      paragraph("зазор"),
      paragraph({ marker: "[ЗАКАЗЧИК-ОРГАНИЗАЦИЯ]" }),
      paragraph({ marker: "[ЗАКАЗЧИК-ФИО]" }),
    ];
    const tables = [table([[paragraph({ marker: "[ИСПОЛНИТЕЛЬ-ТЕЛЕФОН]" })]])];

    const result = buildAnchorIndex(outline(paragraphs, tables), [
      occurrence("org", "[ЗАКАЗЧИК-ОРГАНИЗАЦИЯ]", 0, { segmentOrder: 0 }),
      inCell("phone", "[ИСПОЛНИТЕЛЬ-ТЕЛЕФОН]", {
        table: 0,
        row: 0,
        cell: 0,
        para: 0,
      }, { segmentOrder: 1 }),
      occurrence("person", "[ЗАКАЗЧИК-ФИО]", 1, { segmentOrder: 2 }),
    ]);

    const org = result.get("org");
    const person = result.get("person");
    expect(result.get("phone")?.status).toBe("resolved");
    expect(org?.status).toBe("resolved");
    expect(person?.status).toBe("resolved");
    if (org?.status === "resolved" && person?.status === "resolved") {
      expect(org.paragraphIndex).toBe(1);
      expect(person.paragraphIndex).toBe(2);
    }
  });

  it("несуществующий адрес ячейки — not-found, а не соседняя ячейка", () => {
    const tables = [table([[paragraph({ marker: "[ЗАКАЗЧИК-ИНН]" })]])];
    const result = buildAnchorIndex(outline([], tables), [
      inCell("far", "[ЗАКАЗЧИК-ИНН]", { table: 0, row: 5, cell: 0, para: 0 }),
    ]);

    expect(result.get("far")?.status).toBe("not-found");
  });

  it("абзац тела не ищется среди абзацев таблицы", () => {
    // bodyParagraphs собирается без абзацев внутри таблиц — ровно так же, как
    // бэкенд считает индекс в ["body", N].
    const result = buildAnchorIndex(
      outline([paragraph("текст")], [table([[paragraph({ marker: "[ИНН]" })]])]),
      [occurrence("inn", "[ИНН]", 0)],
    );

    expect(result.get("inn")?.status).toBe("not-found");
  });

  it("не найденный маркер помечается not-found, а не привязывается наугад", () => {
    const paragraphs = [paragraph("обычный текст без маркеров")];
    const result = buildAnchorIndex(outline(paragraphs), [
      occurrence("missing", "[ИНН]", 0),
    ]);

    expect(result.get("missing")?.status).toBe("not-found");
  });

  it("не найденное вхождение не двигает курсор — следующие ищутся как обычно", () => {
    const paragraphs = [paragraph("нет маркера"), paragraph({ marker: "[СЧЁТ-1]" })];
    const result = buildAnchorIndex(outline(paragraphs), [
      occurrence("missing", "[ИНН]", 0),
      occurrence("found", "[СЧЁТ-1]", 1, { chunkStart: 1 }),
    ]);

    expect(result.get("missing")?.status).toBe("not-found");
    expect(result.get("found")?.status).toBe("resolved");
  });

  it("сбитая на середине дельта чинится следующей успешной привязкой", () => {
    const paragraphs = [
      paragraph("зазор 1"),
      paragraph("зазор 2"),
      paragraph({ marker: "[ОРГАНИЗАЦИЯ-1]" }),
      paragraph({ marker: "[ФИО-1]" }),
    ];
    const result = buildAnchorIndex(outline(paragraphs), [
      occurrence("org", "[ОРГАНИЗАЦИЯ-1]", 0, { chunkStart: 0 }),
      occurrence("person", "[ФИО-1]", 1, { chunkStart: 1 }),
    ]);

    const org = result.get("org");
    const person = result.get("person");
    expect(org?.status).toBe("resolved");
    expect(person?.status).toBe("resolved");
    if (org?.status === "resolved" && person?.status === "resolved") {
      expect(org.paragraphIndex).toBe(2);
      expect(person.paragraphIndex).toBe(3);
    }
  });

  it("маркер, разбитый на несколько соседних ранов, безопасно не находится", () => {
    const paragraphs = [paragraph({ marker: "[ОРГАНИЗАЦИЯ-1" }, { marker: "]......." })];
    const result = buildAnchorIndex(outline(paragraphs), [
      occurrence("org", "[ОРГАНИЗАЦИЯ-1]", 0),
    ]);

    expect(result.get("org")?.status).toBe("not-found");
  });
});
