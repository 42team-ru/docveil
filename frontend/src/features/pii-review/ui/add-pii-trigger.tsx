import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Plus } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";

import type { PiiType } from "../../../entity/pii/model/types";
import type { SelectionCapture } from "../../document-viewer/lib/read-selection";
import { AddPiiDialog } from "./add-pii-dialog";

type AddPiiTriggerProps = {
  capture: SelectionCapture | null;
  onAdd: (input: { type: PiiType; text: string }) => void;
  onDismiss: () => void;
};

const TRIGGER_OFFSET = 8;
const AUTO_DISMISS_MS = 6000;

/**
 * Кнопка «Добавить как ПДн», всплывающая рядом с выделенным текстом (не в
 * тулбаре, как раньше): позиция берётся из `capture.rect`, захваченного
 * `read-selection.ts` в момент выделения. Портал в `document.body` — сама
 * позиция вычисляется из геометрии выделения в вьюпорте, поэтому кнопке
 * нужен `position: fixed` без искажений от `overflow`/`transform` листа
 * документа; это единственное оправданное исключение из «без инлайн-стилей»
 * в проекте — координаты не выбираются произвольно, а считаются из
 * `getBoundingClientRect()` на каждое новое выделение.
 *
 * Клик по кнопке не добавляет тип напрямую (как в прежнем `AddPiiPopover`),
 * а открывает `AddPiiDialog` с поиском по справочнику типов.
 *
 * Кнопка сбрасывается при: скролле превью, клике мимо кнопки, и автоматически
 * через AUTO_DISMISS_MS мс — чтобы не висеть поверх документа бесконечно.
 */
export function AddPiiTrigger({ capture, onAdd, onDismiss }: AddPiiTriggerProps) {
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const buttonRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!capture || isDialogOpen) return;

    const timer = setTimeout(onDismiss, AUTO_DISMISS_MS);

    function handleScroll() {
      onDismiss();
    }

    function handleMouseDown(event: MouseEvent) {
      if (buttonRef.current && !buttonRef.current.contains(event.target as Node)) {
        onDismiss();
      }
    }

    window.addEventListener("scroll", handleScroll, { capture: true, passive: true });
    document.addEventListener("mousedown", handleMouseDown);

    return () => {
      clearTimeout(timer);
      window.removeEventListener("scroll", handleScroll, { capture: true });
      document.removeEventListener("mousedown", handleMouseDown);
    };
  }, [capture, isDialogOpen, onDismiss]);

  if (!capture) return null;

  const { rect } = capture;
  const top = Math.max(rect.top - 40, TRIGGER_OFFSET);
  const left = Math.min(
    Math.max(rect.left, TRIGGER_OFFSET),
    window.innerWidth - 200,
  );

  return (
    <>
      {createPortal(
        <div ref={buttonRef} style={{ position: "fixed", top, left, zIndex: 30 }}>
          <Button
            size="sm"
            variant="primary"
            label="Добавить как ПДн"
            icon={<Icon icon={Plus} size="sm" />}
            onClick={() => setIsDialogOpen(true)}
          />
        </div>,
        document.body,
      )}
      <AddPiiDialog
        isOpen={isDialogOpen}
        capture={capture}
        onAdd={(input) => {
          setIsDialogOpen(false);
          onAdd(input);
        }}
        onOpenChange={(open) => {
          setIsDialogOpen(open);
          if (!open) onDismiss();
        }}
      />
    </>
  );
}
