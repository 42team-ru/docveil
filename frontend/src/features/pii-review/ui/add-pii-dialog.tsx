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

import { piiTypeOptions } from "../../../entity/pii/model/pii-type-dict";
import type { PiiType } from "../../../entity/pii/model/types";
import type { SelectionCapture } from "../../document-viewer/lib/read-selection";

type AddPiiDialogProps = {
  isOpen: boolean;
  capture: SelectionCapture | null;
  onAdd: (type: PiiType) => void;
  onOpenChange: (isOpen: boolean) => void;
};

/**
 * Диалог добавления пропущенного ПДн: цитата выделенного текста и выбор типа
 * из того же справочника, что и остальная проверка (`piiTypeOptions()`).
 * Поиск в `Selector` — иначе ~21 тип пришлось бы листать плоским списком, как
 * в прежнем `AddPiiPopover`.
 */
export function AddPiiDialog({
  isOpen,
  capture,
  onAdd,
  onOpenChange,
}: AddPiiDialogProps) {
  const [type, setType] = useState<PiiType | null>(null);

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={(open) => {
        onOpenChange(open);
        if (!open) setType(null);
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
              <Text weight="medium" maxLines={3}>
                «{capture?.text ?? ""}»
              </Text>
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
                isDisabled={type === null}
                onClick={() => {
                  if (type === null) return;
                  onAdd(type);
                  setType(null);
                }}
              />
            </HStack>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
