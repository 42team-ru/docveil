import { Info } from "lucide-react";
import { IconButton } from "@astryxdesign/core/IconButton";
import { HStack } from "@astryxdesign/core/Stack";
import { Icon } from "@astryxdesign/core/Icon";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@astryxdesign/core/SegmentedControl";
import { Text } from "@astryxdesign/core/Text";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import { Tooltip } from "@astryxdesign/core/Tooltip";

import type { DocumentViewMode } from "../../../entity/pii/model/review-store";
import type { VisiblePageInfo } from "../../document-viewer/ui/bbox-viewer";

const PREVIEW_NOTICE =
  "Вёрстка, шрифты и разбиение на страницы — приближение к оригиналу. " +
  "Итоговый файл для скачивания собирается отдельно и может отличаться от этого отображения.";

type DocumentToolbarProps = {
  viewMode: DocumentViewMode;
  onViewModeChange: (mode: DocumentViewMode) => void;
  /** Только для pdf/скана с больше чем одной страницей — `bbox-viewer.tsx`. */
  pageInfo?: VisiblePageInfo | null;
};

/** Полоса над листом документа: режим показа и предупреждение о превью. Кнопка
 * «Добавить как ПДн» больше не здесь — она всплывает рядом с выделением
 * (`add-pii-trigger.tsx`), а не в фиксированной полосе тулбара. */
export function DocumentToolbar({
  viewMode,
  onViewModeChange,
  pageInfo,
}: DocumentToolbarProps) {
  return (
    <Toolbar
      label="Просмотр документа"
      size="sm"
      gap={3}
      startContent={
        <HStack gap={3} vAlign="center" wrap="wrap">
          <SegmentedControl
            size="sm"
            label="Режим показа"
            value={viewMode}
            onChange={(value) => onViewModeChange(value as DocumentViewMode)}
          >
            <SegmentedControlItem value="all" label="Все" />
            <SegmentedControlItem value="original" label="Оригинал" />
          </SegmentedControl>
          {pageInfo ? (
            <Text type="supporting" color="secondary" hasTabularNumbers>
              {`Страница ${pageInfo.current} из ${pageInfo.total}`}
            </Text>
          ) : null}
        </HStack>
      }
      endContent={
        <Tooltip content={PREVIEW_NOTICE} placement="below" touchTrigger="tap">
          <IconButton
            size="sm"
            variant="ghost"
            icon={<Icon icon={Info} size="sm" />}
            label="О предпросмотре"
          />
        </Tooltip>
      }
    />
  );
}
