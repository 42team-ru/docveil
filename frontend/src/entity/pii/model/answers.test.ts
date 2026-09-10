import { describe, expect, it } from "vitest";

import {
  buildAnswerEnvelope,
  isForcedQuestion,
  unansweredQuestions,
} from "./answers";
import { askEnvelopeFixture } from "./fixtures";
import {
  KEEP_CRITICAL_OPTION,
  KEEP_OPTION,
  MASK_OPTION,
  type PolicyQuestion,
} from "./types";

function question(overrides: Partial<PolicyQuestion> = {}): PolicyQuestion {
  return {
    id: "TYPE-phone",
    kind: "type",
    target: "phone",
    title: "Телефон",
    prompt: "Маскировать все «Телефон»?",
    options: [MASK_OPTION, KEEP_OPTION],
    default: MASK_OPTION,
    critical: false,
    found: 1,
    samples: [],
    anchors: [],
    ...overrides,
  };
}

describe("buildAnswerEnvelope", () => {
  it("собирает конверт в форме, которую ждёт движок", () => {
    const envelope = buildAnswerEnvelope([question()], {
      "TYPE-phone": KEEP_OPTION,
    });

    expect(envelope).toEqual({
      schema_version: 1,
      answers: { "TYPE-phone": KEEP_OPTION },
    });
  });

  it("не шлёт ответы на вопросы, которых движок не задавал", () => {
    const envelope = buildAnswerEnvelope([question()], {
      "TYPE-phone": KEEP_OPTION,
      "TYPE-email": KEEP_OPTION,
    });

    expect(Object.keys(envelope.answers)).toEqual(["TYPE-phone"]);
  });

  it("отбрасывает вариант, которого нет у вопроса", () => {
    // Движок заменил бы такую строку на default, то есть на «маскировать»:
    // оператор нажал бы «оставить», а получил бы маску и не узнал об этом.
    const forced = question({
      id: "TYPE-inn",
      options: [MASK_OPTION],
      critical: true,
    });

    const envelope = buildAnswerEnvelope([forced], {
      "TYPE-inn": KEEP_CRITICAL_OPTION,
    });

    expect(envelope.answers).toEqual({});
  });

  it("пропускает осознанное снятие, когда движок его предлагает", () => {
    // Так выглядит вопрос при прогоне с --unmask-critical.
    const unmaskable = question({
      id: "TYPE-inn",
      options: [MASK_OPTION, KEEP_CRITICAL_OPTION],
      critical: true,
    });

    const envelope = buildAnswerEnvelope([unmaskable], {
      "TYPE-inn": KEEP_CRITICAL_OPTION,
    });

    expect(envelope.answers).toEqual({ "TYPE-inn": KEEP_CRITICAL_OPTION });
  });

  it("неотвеченный вопрос в конверт не попадает", () => {
    const envelope = buildAnswerEnvelope([question()], {});
    expect(envelope.answers).toEqual({});
  });
});

describe("unansweredQuestions", () => {
  it("показывает, что движок решит за оператора", () => {
    const questions = askEnvelopeFixture.questions;
    const pending = unansweredQuestions(questions, {
      "TYPE-org_name": KEEP_OPTION,
    });

    expect(pending).toHaveLength(questions.length - 1);
    expect(pending.map((q) => q.id)).not.toContain("TYPE-org_name");
  });
});

describe("isForcedQuestion", () => {
  it("критичный тип без разрешения на снятие — выбора нет", () => {
    const inn = askEnvelopeFixture.questions.find((q) => q.id === "TYPE-inn");
    expect(inn && isForcedQuestion(inn)).toBe(true);
  });

  it("обычный тип оставляет выбор", () => {
    const phone = askEnvelopeFixture.questions.find(
      (q) => q.id === "TYPE-phone",
    );
    expect(phone && isForcedQuestion(phone)).toBe(false);
  });
});
