import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { useReviewStore } from "../../../entity/pii/model/review-store";
import { KEEP_OPTION, MASK_OPTION, type AskEnvelope } from "../../../entity/pii/model/types";
import { MaskingSetupDialog } from "./masking-setup-dialog";

const mutate = vi.hoisted(() => vi.fn());
vi.mock("../../masking-run/api/masking-run", () => ({ useSubmitAnswers: () => ({ mutate, isPending: false, isError: false }) }));
vi.mock("@astryxdesign/core/Dialog", () => ({
  Dialog: ({ children, isOpen }: { children: ReactNode; isOpen: boolean }) => isOpen ? <section>{children}</section> : null,
  DialogHeader: ({ title }: { title: string }) => <h2>{title}</h2>,
}));

const ask: AskEnvelope = {
  schemaVersion: 1, threadId: "run", document: { name: "test.docx", format: "docx" },
  questions: [{ id: "TYPE-phone", kind: "type", target: "phone", title: "Телефон", prompt: "Маскировать?",
    options: [MASK_OPTION, KEEP_OPTION], default: MASK_OPTION, critical: false, found: 1, samples: [], anchors: [] }],
};
const host = document.createElement("main");
document.body.append(host);
let root = createRoot(host);
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
afterEach(async () => {
  await act(async () => root.unmount());
  root = createRoot(host);
  useReviewStore.setState({ questionAnswers: {} });
  mutate.mockClear();
});

it("подтверждает типы по умолчанию и продолжает прогон без повторного вопроса", async () => {
  await act(async () => root.render(<MaskingSetupDialog runId="run" ask={ask} isSelecting isProcessing={false} error={null} onSelected={() => {}} onLeave={() => {}} />));
  expect(host.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  expect(mutate).toHaveBeenCalledWith({ schema_version: 1, answers: { "TYPE-phone": MASK_OPTION } });
});

it("сохраняет типы, но не отвечает за человека на уточнения", async () => {
  const mixed: AskEnvelope = { ...ask, questions: [...ask.questions, { ...ask.questions[0], id: "PROFILE-P1", kind: "profile" }] };
  const onSelected = vi.fn();
  await act(async () => root.render(<MaskingSetupDialog runId="run" ask={mixed} isSelecting isProcessing={false} error={null} onSelected={onSelected} onLeave={() => {}} />));
  expect(host.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  expect(onSelected).toHaveBeenCalledOnce();
  expect(mutate).not.toHaveBeenCalled();
  expect(useReviewStore.getState().questionAnswers).toEqual({ "TYPE-phone": MASK_OPTION });
});

it("показывает ожидание, ошибку и закрывает диалог после обработки", async () => {
  const props = { runId: "run", ask: null, isSelecting: false, onSelected: () => {}, onLeave: () => {} };
  await act(async () => root.render(<MaskingSetupDialog {...props} isProcessing error={null} />));
  expect(host.textContent).toContain("Обработка документа");
  await act(async () => root.render(<MaskingSetupDialog {...props} isProcessing={false} error="Ошибка сети" />));
  expect(host.textContent).toContain("Ошибка сети");
  await act(async () => root.render(<MaskingSetupDialog {...props} isProcessing={false} error={null} />));
  expect(host.textContent).toBe("");
});
