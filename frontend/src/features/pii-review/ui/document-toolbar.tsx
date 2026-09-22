import { Info } from "lucide-react";
import { Badge } from "@astryxdesign/core/Badge";
import { HStack } from "@astryxdesign/core/Stack";
import { Icon } from "@astryxdesign/core/Icon";
import { Kbd } from "@astryxdesign/core/Kbd";
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
  documentName: string;
  viewMode: DocumentViewMode;
  onViewModeChange: (mode: DocumentViewMode) => void;
  /** Только для pdf/скана с больше чем одной страницей — `bbox-viewer.tsx`. */
  pageInfo?: VisiblePageInfo | null;
};

/** Полоса над листом документа: имя файла, режим показа и горячие клавиши
 * j/k. Кнопка
 * «Добавить как ПДн» больше не здесь — она всплывает рядом с выделением
 * (`add-pii-trigger.tsx`), а не в фиксированной полосе тулбара. */
export function DocumentToolbar({
  documentName,
  viewMode,
  onViewModeChange,
  pageInfo,
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
        <HStack gap={3} vAlign="center" wrap="wrap">
          <Tooltip content={PREVIEW_NOTICE} placement="below">
            <Badge
              variant="warning"
              icon={<Icon icon={Info} size="sm" />}
              label="Предупреждение"
            />
          </Tooltip>
          <HStack gap={1} vAlign="center">
            <Kbd keys="j" />
            <Kbd keys="k" />
            <Text type="supporting">навигация</Text>
          </HStack>
        </HStack>
      }
    />
  );
}
