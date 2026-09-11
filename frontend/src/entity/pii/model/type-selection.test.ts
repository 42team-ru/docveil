import { describe, expect, it } from "vitest";
import { typeSelectionAnswer, withTypeSelectionDefaults } from "./type-selection";
import { MASK_OPTION, KEEP_OPTION, KEEP_CRITICAL_OPTION, type PolicyQuestion } from "./types";

const question: PolicyQuestion = {
  id: "TYPE-phone", kind: "type", target: "phone", title: "Телефон", prompt: "Маскировать?",
  options: [MASK_OPTION, KEEP_OPTION], default: MASK_OPTION, critical: false,
  found: 2, samples: [], anchors: [],
};

describe("выбор типов в диалоге", () => {
  it("передаёт снятый чекбокс как разрешённый ответ «оставить»", () => {
    expect(typeSelectionAnswer(question, false)).toBe(KEEP_OPTION);
    expect(typeSelectionAnswer(question, true)).toBe(MASK_OPTION);
  });
  it("не снимает обязательную маску", () => {
    expect(typeSelectionAnswer({ ...question, options: [MASK_OPTION], critical: true }, false)).toBe(MASK_OPTION);
  });
  it("сохраняет осознанный вариант критичного типа из контракта", () => {
    expect(typeSelectionAnswer({ ...question, options: [MASK_OPTION, KEEP_CRITICAL_OPTION] }, false)).toBe(KEEP_CRITICAL_OPTION);
  });
  it("сохраняет выбор типов и уточнения, заполняя только отсутствующие типы", () => {
    const questions = [question, { ...question, id: "TYPE-email" }, { ...question, id: "P1", kind: "profile" as const }];
    expect(withTypeSelectionDefaults(questions, { "TYPE-phone": KEEP_OPTION, P1: KEEP_OPTION })).toEqual({
      "TYPE-phone": KEEP_OPTION, "TYPE-email": MASK_OPTION, P1: KEEP_OPTION,
    });
    expect(withTypeSelectionDefaults(questions, {})).not.toHaveProperty("P1");
  });
  it("не переносит недопустимый старый ответ в обязательную маску", () => {
    expect(withTypeSelectionDefaults([{ ...question, options: [MASK_OPTION] }], { "TYPE-phone": KEEP_OPTION }))
      .toEqual({ "TYPE-phone": MASK_OPTION });
  });
});
