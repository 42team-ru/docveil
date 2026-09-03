import { Plus } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Popover } from "@astryxdesign/core/Popover";
import { VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { piiTypeOptions } from "../../../entity/pii/model/pii-type-dict";
import type { PiiType } from "../../../entity/pii/model/types";
import type { SelectionCapture } from "../../document-viewer/lib/read-selection";

type AddPiiPopoverProps = {
  capture: SelectionCapture | null;
  onAdd: (type: PiiType) => void;
  onDismiss: () => void;
};

/**
 * Появляется в тулбаре, когда оператор выделил текст в документе мышью.
 * Выбор типа сразу заводит вхождение через `onAdd` — координата уже захвачена
 * `read-selection.ts` в момент выделения.
 */
export function AddPiiPopover({ capture, onAdd, onDismiss }: AddPiiPopoverProps) {
  if (!capture) return null;

  return (
    <Popover
      isOpen
      onOpenChange={(open) => {
        if (!open) onDismiss();
      }}
      label="Добавить пропущенное ПДн"
      width={260}
      content={
        <VStack gap={2} padding={3}>
          <Text weight="medium" maxLines={2}>
            «{capture.text}»
          </Text>
          <Text type="supporting" color="secondary">
            Выберите тип для выделенного текста
          </Text>
          <VStack gap={1}>
            {piiTypeOptions().map((option) => (
              <Button
                key={option.value}
                size="sm"
                variant="ghost"
                label={option.label}
                onClick={() => onAdd(option.value)}
              />
            ))}
          </VStack>
        </VStack>
      }
    >
      <Button
        size="sm"
        variant="primary"
        label="Добавить как ПДн"
        icon={<Icon icon={Plus} size="sm" />}
      />
    </Popover>
  );
}
