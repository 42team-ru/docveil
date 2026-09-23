import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { maskingReportFixture, reviewedDocumentFixture } from "../../entity/pii/model/fixtures";
import type { SelectionCapture } from "../../features/document-viewer/lib/read-selection";

const selectionCapture = vi.hoisted(() => ({} as SelectionCapture));

vi.mock("../../features/document-viewer/ui/document-viewer", () => ({
  DocumentViewer: ({ onSelectionCapture }: { onSelectionCapture?: (capture: SelectionCapture) => void }) =>
    createElement("button", {
      type: "button",
      "data-testid": "capture-selection",
      onClick: () => onSelectionCapture?.(selectionCapture),
    }, "Выделить текст"),
}));

vi.mock("../../features/pii-review/ui/add-pii-trigger", () => ({
  AddPiiTrigger: ({ capture }: { capture: SelectionCapture | null }) => capture
    ? createElement("button", { type: "button", "data-testid": "add-pii-trigger" }, "Добавить как ПДн")
    : null,
}));

vi.mock("../../features/pii-review/ui/document-toolbar", () => ({
  DocumentToolbar: () => null,
}));

vi.mock("@astryxdesign/core/AlertDialog", () => ({
  AlertDialog: ({ isOpen, title }: { isOpen: boolean; title: string }) => isOpen
    ? createElement("div", null, title)
    : null,
}));

const { ReviewView } = await import("./review-view");
const host = document.createElement("main");
document.body.append(host);
let root: Root;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeEach(() => {
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
});

it("не открывает создание ручной ПДн и редакторы после завершения проверки", async () => {
  await act(async () => root.render(
    <ReviewView
      document={{ ...reviewedDocumentFixture, originalFileUrl: "/contract-roles.docx" }}
      extraction={maskingReportFixture.extraction}
      pages={[]}
      hasUnappliedChanges
      isRegenerating={false}
      isReviewFinished
      onRegenerate={() => undefined}
      onDiscardChanges={() => undefined}
      onNotFoundChange={() => undefined}
    />,
  ));

  expect(host.querySelector('[data-testid="add-pii-trigger"]')).toBeNull();
  expect(host.textContent).not.toContain("Перегенерировать файл");
  expect(host.textContent).not.toContain("Отменить изменения");

  const captureButton = host.querySelector<HTMLButtonElement>('[data-testid="capture-selection"]');
  await act(async () => captureButton?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  expect(host.querySelector('[data-testid="add-pii-trigger"]')).toBeNull();
});
