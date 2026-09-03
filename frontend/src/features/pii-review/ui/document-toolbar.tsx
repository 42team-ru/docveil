import { HStack } from "@astryxdesign/core/Stack";
import { Kbd } from "@astryxdesign/core/Kbd";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@astryxdesign/core/SegmentedControl";
import { Text } from "@astryxdesign/core/Text";
import { Toolbar } from "@astryxdesign/core/Toolbar";

import type { DocumentViewMode } from "../../../entity/pii/model/review-store";
import type { SelectionCapture } from "../../document-viewer/lib/read-selection";
import type { PiiType } from "../../../entity/pii/model/types";
import { AddPiiPopover } from "./add-pii-popover";

type DocumentToolbarProps = {
  documentName: string;
  viewMode: DocumentViewMode;
  onViewModeChange: (mode: DocumentViewMode) => void;
  pendingSelection: SelectionCapture | null;
  onAddManual: (type: PiiType) => void;
  onDismissSelection: () => void;
};

/** Полоса над листом документа: имя файла, режим показа и горячие клавиши —
 * j/k/a/r теперь реально перехватываются `use-review-hotkeys.ts`. */
export function DocumentToolbar({
  documentName,
  viewMode,
  onViewModeChange,
  pendingSelection,
  onAddManual,
  onDismissSelection,
}: DocumentToolbarProps) {
  return (
    <Toolbar
      label="Просмотр документа"
      size="sm"
      startContent={
        <HStack gap={3} vAlign="center">
          <Text type="supporting" maxLines={1}>
            {documentName}
          </Text>
          <SegmentedControl
            size="sm"
            label="Режим показа"
            value={viewMode}
            onChange={(value) => onViewModeChange(value as DocumentViewMode)}
          >
            <SegmentedControlItem value="all" label="Все" />
            <SegmentedControlItem value="pending" label="Только замены" />
            <SegmentedControlItem value="original" label="Оригинал" />
          </SegmentedControl>
          <AddPiiPopover
            capture={pendingSelection}
            onAdd={onAddManual}
            onDismiss={onDismissSelection}
          />
        </HStack>
      }
      endContent={
        <HStack gap={3} vAlign="center" wrap="wrap">
          <HStack gap={1} vAlign="center">
            <Kbd keys="j" />
            <Kbd keys="k" />
            <Text type="supporting">навигация</Text>
          </HStack>
          <HStack gap={1} vAlign="center">
            <Kbd keys="a" />
            <Text type="supporting">подтвердить</Text>
          </HStack>
          <HStack gap={1} vAlign="center">
            <Kbd keys="r" />
            <Text type="supporting">вернуть</Text>
          </HStack>
        </HStack>
      }
    />
  );
}
