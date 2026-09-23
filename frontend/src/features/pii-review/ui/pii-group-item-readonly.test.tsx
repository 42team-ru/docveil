import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { flattenPiiOccurrences } from "../../../entity/pii/model/flatten";
import { maskingReportFixture } from "../../../entity/pii/model/fixtures";
import { PiiGroupItem } from "./pii-group-item";

const host = document.createElement("main");
document.body.append(host);
let root: Root;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
  configurable: true,
  value: vi.fn(),
});

beforeEach(() => {
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
});

it("убирает меню смены типа группы и вхождения после завершения проверки", async () => {
  const occurrence = flattenPiiOccurrences(maskingReportFixture.extraction)[0];
  expect(occurrence).toBeDefined();
  if (!occurrence) return;

  const groupOccurrences = flattenPiiOccurrences(maskingReportFixture.extraction)
    .filter((item) => item.groupId === occurrence.groupId);

  await act(async () => root.render(
    <PiiGroupItem
      groupId={occurrence.groupId}
      occurrences={groupOccurrences}
      decision="confirmed"
      groupDecisions={{}}
      occurrenceDecisions={{}}
      appliedGroupDecisions={{}}
      appliedOccurrenceDecisions={{}}
      selectedOccurrenceId={occurrence.id}
      notFoundIds={new Set()}
      manualOccurrenceIds={new Set()}
      onSelect={vi.fn()}
      onConfirm={vi.fn()}
      onReject={vi.fn()}
      onConfirmOccurrence={vi.fn()}
      onRejectOccurrence={vi.fn()}
      onSetGroupType={vi.fn()}
      onSetOccurrenceType={vi.fn()}
      onAddFallbackManual={vi.fn()}
      isEditingDisabled
      isReadOnly
    />,
  ));

  expect(host.textContent).not.toContain("Сменить тип");
  expect(host.querySelector('[aria-label="Тип только для этого вхождения"]')).toBeNull();
});
