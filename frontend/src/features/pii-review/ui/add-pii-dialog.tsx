import { useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import {
  Layout,
  LayoutContent,
  LayoutFooter,
} from "@astryxdesign/core/Layout";
import { Selector } from "@astryxdesign/core/Selector";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";

import { piiTypeOptions } from "../../../entity/pii/model/pii-type-dict";
import type { PiiType } from "../../../entity/pii/model/types";
import type { SelectionCapture } from "../../document-viewer/lib/read-selection";

type AddPiiDialogProps = {
  isOpen: boolean;
  capture: SelectionCapture | null;
  onAdd: (input: { type: PiiType; text: string }) => void;
  onOpenChange: (isOpen: boolean) => void;
};

/**
 * Диалог добавления пропущенного ПДн: выбор типа из того же справочника, что
 * и остальная проверка (`piiTypeOptions()`). Поиск в `Selector` — иначе ~21
 * тип пришлось бы листать плоским списком, как в прежнем `AddPiiPopover`.
 *
 * Текст значения — по виду выделения: у `kind: "text"` (docx/xlsx) это
 * цитата из документа, только для показа; у `kind: "region"` (pdf/картинка,
 * рамка на превью) текстового слоя под рамкой может не быть вовсе (скан),
 * поэтому оператор печатает значение сам — бэкенд требует `text` вместе с
 * `region` (`ManualEntityIn.region`, инвариант «текст этот, находится ровно
 * здесь»).
 */
export function AddPiiDialog({
  isOpen,
  capture,
  onAdd,
  onOpenChange,
}: AddPiiDialogProps) {
  const [type, setType] = useState<PiiType | null>(null);
  const [manualText, setManualText] = useState("");

  const isRegion = capture?.kind === "region";
  const text = isRegion ? manualText.trim() : (capture?.text ?? "");
  const canSubmit = type !== null && text.length > 0;

  function reset() {
    setType(null);
    setManualText("");
  }

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={(open) => {
        onOpenChange(open);
        if (!open) reset();
      }}
      purpose="form"
      width={380}
    >
      <Layout
        header={
          <DialogHeader
            title="Добавить персональную данную"
            onOpenChange={() => onOpenChange(false)}
          />
        }
        content={
          <LayoutContent>
            <VStack gap={4}>
              {isRegion ? (
                <TextInput
                  label="Значение"
                  type="text"
                  placeholder="Что здесь написано"
                  value={manualText}
                  onChange={setManualText}
                />
              ) : (
                <Text weight="medium" maxLines={3}>
                  «{capture?.text ?? ""}»
                </Text>
              )}
              <Selector
                label="Тип"
                hasSearch
                placeholder="Выберите тип"
                searchPlaceholder="Поиск типа..."
                options={piiTypeOptions().map((option) => ({
                  value: option.value,
                  label: option.label,
                }))}
                value={type ?? undefined}
                onChange={(value) => setType(value as PiiType)}
              />
            </VStack>
          </LayoutContent>
        }
        footer={
          <LayoutFooter hasDivider>
            <HStack gap={2} hAlign="end" width="100%">
              <Button
                variant="ghost"
                label="Отмена"
                onClick={() => onOpenChange(false)}
              />
              <Button
                variant="primary"
                label="Добавить"
                isDisabled={!canSubmit}
                onClick={() => {
                  if (type === null || text.length === 0) return;
                  onAdd({ type, text });
                  reset();
                }}
              />
            </HStack>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
