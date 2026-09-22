import { describe, expect, it } from "vitest";

import type { ManualPiiOccurrence } from "../../../entity/pii/model/types";
import {
  paintManualDocxHighlight,
  paintManualXlsxHighlight,
  unpaintManualHighlight,
} from "./manual-highlight";

function docxOccurrence(
  id: string,
  paragraphIndex: number,
  text: string,
): ManualPiiOccurrence {
  return {
    id,
    type: "person",
    text,
    anchor: { format: "docx", label: `абзац ${paragraphIndex + 1}`, locator: ["body", paragraphIndex] },
  };
}

function xlsxOccurrence(id: string, row: number, col: number, text: string): ManualPiiOccurrence {
  return {
    id,
    type: "person",
    text,
    anchor: { format: "xlsx", label: `Лист1!R${row}C${col}`, locator: ["sheet", "Лист1", row, col] },
  };
}

describe("paintManualDocxHighlight", () => {
  it("оборачивает выбранный текст внутри одного текстового узла абзаца", () => {
    const host = document.createElement("div");
    host.innerHTML = "<p>Договор подписал Иванов Иван Иванович вчера</p>";
    document.body.appendChild(host);

    const run = paintManualDocxHighlight(host, docxOccurrence("m1", 0, "Иванов Иван Иванович"), "all");

    expect(run).not.toBeNull();
    expect(run?.dataset.piiId).toBe("m1");
    expect(run?.tagName).toBe("SPAN");
    // Абзац читается точно так же, как исходный текст — оборачивание не потеряло и не задвоило символы.
    expect(host.querySelector("p")?.textContent).toBe("Договор подписал Иванов Иван Иванович вчера");
    expect(run?.textContent).toBe("Иванов Иван Иванович");
  });

  it("находит подстроку, если абзац уже разбит на несколько текстовых узлов/спанов", () => {
    const host = document.createElement("div");
    const p = document.createElement("p");
    const before = document.createElement("span");
    before.textContent = "Стороны: ";
    const middle = document.createElement("span");
    middle.textContent = "Петров";
    const after = document.createElement("span");
    after.textContent = " Пётр Петрович, далее Заказчик";
    p.append(before, middle, after);
    host.appendChild(p);

    // "ов Пётр" пересекает границу между middle и after.
    const run = paintManualDocxHighlight(host, docxOccurrence("m2", 0, "ов Пётр"), "all");

    expect(run).not.toBeNull();
    expect(run?.textContent).toBe("ов Пётр");
    expect(p.textContent).toBe("Стороны: Петров Пётр Петрович, далее Заказчик");
  });

  it("возвращает null, если текст выделения в абзаце не находится (документ успел перерисоваться)", () => {
    const host = document.createElement("div");
    host.innerHTML = "<p>Прочий текст</p>";

    const run = paintManualDocxHighlight(host, docxOccurrence("m3", 0, "Иванов"), "all");

    expect(run).toBeNull();
  });

  it("возвращает null для несуществующего индекса абзаца", () => {
    const host = document.createElement("div");
    host.innerHTML = "<p>Один абзац</p>";

    const run = paintManualDocxHighlight(host, docxOccurrence("m4", 5, "Один"), "all");

    expect(run).toBeNull();
  });

  it("не красит (transparent) в режиме «Оригинал»", () => {
    const host = document.createElement("div");
    host.innerHTML = "<p>Некий текст с Ивановым внутри</p>";

    const run = paintManualDocxHighlight(host, docxOccurrence("m5", 0, "Ивановым"), "original");

    expect(run?.style.backgroundColor).toBe("transparent");
  });
});

describe("paintManualXlsxHighlight", () => {
  it("находит ячейку по data-row/data-col и оборачивает вхождение", () => {
    const host = document.createElement("div");
    const table = document.createElement("table");
    const td = document.createElement("td");
    td.dataset.row = "2";
    td.dataset.col = "3";
    td.textContent = "ИНН 7701234567 у поставщика";
    table.appendChild(td);
    host.appendChild(table);

    const run = paintManualXlsxHighlight(host, xlsxOccurrence("m6", 2, 3, "7701234567"), "all");

    expect(run).not.toBeNull();
    expect(run?.dataset.piiId).toBe("m6");
    expect(td.textContent).toBe("ИНН 7701234567 у поставщика");
  });

  it("возвращает null, если ячейка с такими координатами не найдена", () => {
    const host = document.createElement("div");
    host.innerHTML = '<table><td data-row="0" data-col="0">x</td></table>';

    const run = paintManualXlsxHighlight(host, xlsxOccurrence("m7", 9, 9, "x"), "all");

    expect(run).toBeNull();
  });
});

describe("unpaintManualHighlight", () => {
  it("снимает data-pii-id и покраску с текстовой обёртки, не трогая остальной текст", () => {
    const host = document.createElement("div");
    host.innerHTML = "<p>Подписал Сидоров вчера</p>";
    const run = paintManualDocxHighlight(host, docxOccurrence("m8", 0, "Сидоров"), "all");
    expect(run).not.toBeNull();

    unpaintManualHighlight(host, "m8");

    expect(host.querySelector('[data-pii-id="m8"]')).toBeNull();
    expect(host.querySelector("p")?.textContent).toBe("Подписал Сидоров вчера");
  });
});
