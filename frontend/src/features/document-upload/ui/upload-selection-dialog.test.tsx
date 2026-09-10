import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { useUploadQueueStore } from "../../../entity/document/model/upload-queue-store";
import { UploadSelectionDialog } from "./upload-selection-dialog";

vi.mock("@astryxdesign/core/Dialog", () => ({
  Dialog: ({ children, isOpen }: { children: ReactNode; isOpen: boolean }) => isOpen ? <section>{children}</section> : null,
  DialogHeader: ({ title }: { title: string }) => <h2>{title}</h2>,
}));

const host = document.createElement("main");
document.body.append(host);
let root = createRoot(host);
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
afterEach(async () => {
  await act(async () => root.unmount());
  root = createRoot(host);
  useUploadQueueStore.getState().clear();
});

it("открывает выбранный файл и блокирует ещё не загруженные", async () => {
  const queue = useUploadQueueStore.getState();
  queue.add([new File(["a"], "first.docx"), new File(["b"], "second.pdf"), new File(["c"], "outside.pdf")]);
  const [first, second] = useUploadQueueStore.getState().items;
  queue.markStarted(first.id, "run-first");
  queue.markStarting(second.id);
  const onSelect = vi.fn();
  await act(async () => root.render(<UploadSelectionDialog isOpen uploadIds={[first.id, second.id]} onSelect={onSelect} onLeave={() => {}} />));
  expect(host.textContent).toContain("first.docx");
  expect(host.textContent).toContain("second.pdf");
  expect(host.textContent).not.toContain("outside.pdf");
  const buttons = [...host.querySelectorAll("button")].filter((button) => button.textContent?.includes("Открыть"));
  expect(buttons[1].disabled).toBe(true);
  await act(async () => buttons[0].click());
  expect(onSelect).toHaveBeenCalledWith("run-first");
  await act(async () => queue.markStarted(second.id, "run-second"));
  expect(buttons[1].disabled).toBe(false);
  await act(async () => buttons[1].click());
  expect(onSelect).toHaveBeenLastCalledWith("run-second");
});

it("показывает ошибку файла с возможностью вернуться к загрузке", async () => {
  const queue = useUploadQueueStore.getState();
  queue.add([new File(["a"], "failed.docx")]);
  const [file] = useUploadQueueStore.getState().items;
  queue.markFailed(file.id, "Ошибка загрузки");
  const onLeave = vi.fn();
  await act(async () => root.render(<UploadSelectionDialog isOpen uploadIds={[file.id]} onSelect={() => {}} onLeave={onLeave} />));
  expect(host.textContent).toContain("Ошибка загрузки");
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent?.includes("К загрузке"))?.click());
  expect(onLeave).toHaveBeenCalledOnce();
});
