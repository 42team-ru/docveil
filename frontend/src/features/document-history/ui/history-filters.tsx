import { Search } from "lucide-react";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@astryxdesign/core/SegmentedControl";
import { HStack, StackItem } from "@astryxdesign/core/Stack";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Toolbar } from "@astryxdesign/core/Toolbar";

import {
  useHistoryFilterStore,
  type HistoryStatusFilter,
} from "../model/history-filter-store";

/** Ширина поля поиска — структурный размер контрола. */
const SEARCH_WIDTH = 300;

/** Фильтры журнала: поиск по имени документа и состояние прогона. */
export function HistoryFilters() {
  const query = useHistoryFilterStore((state) => state.query);
  const setQuery = useHistoryFilterStore((state) => state.setQuery);
  const status = useHistoryFilterStore((state) => state.status);
  const setStatus = useHistoryFilterStore((state) => state.setStatus);

  return (
    <Toolbar
      label="Фильтры журнала"
      size="sm"
      gap={3}
      startContent={
        <HStack gap={3} vAlign="center" wrap="wrap">
          <TextInput
            size="sm"
            label="Поиск по журналу"
            isLabelHidden
            placeholder="Поиск по имени документа…"
            startIcon={Search}
            width={SEARCH_WIDTH}
            hasClear
            value={query}
            onChange={setQuery}
          />
          <SegmentedControl
            size="sm"
            label="Состояние прогона"
            value={status}
            onChange={(value) => setStatus(value as HistoryStatusFilter)}
          >
            <SegmentedControlItem value="all" label="Все" />
            <SegmentedControlItem value="awaiting_answers" label="Ждут ответов" />
            <SegmentedControlItem value="awaiting_review" label="На проверке" />
            <SegmentedControlItem value="done" label="Готовы" />
            <SegmentedControlItem value="failed" label="Ошибки" />
          </SegmentedControl>
          <StackItem size="fill" />
        </HStack>
      }
    />
  );
}
