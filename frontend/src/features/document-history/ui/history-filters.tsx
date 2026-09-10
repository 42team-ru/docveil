import type { ReactNode } from "react";
import { Search } from "lucide-react";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@astryxdesign/core/SegmentedControl";
import { HStack } from "@astryxdesign/core/Stack";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Toolbar } from "@astryxdesign/core/Toolbar";

import {
  useHistoryFilterStore,
  type HistoryStatusFilter,
} from "../model/history-filter-store";

/** Ширина поля поиска — структурный размер контрола. */
const SEARCH_WIDTH = 420;

type HistoryFiltersProps = {
  /** Действия справа от фильтров — например, кнопка «Новая задача». */
  actions?: ReactNode;
};

/** Фильтры журнала: поиск по имени документа и состояние прогона. */
export function HistoryFilters({ actions }: HistoryFiltersProps) {
  const query = useHistoryFilterStore((state) => state.query);
  const setQuery = useHistoryFilterStore((state) => state.setQuery);
  const status = useHistoryFilterStore((state) => state.status);
  const setStatus = useHistoryFilterStore((state) => state.setStatus);

  return (
    <Toolbar
      className="mt-2"
      label="Фильтры журнала"
      size="lg"
      gap={3}
      startContent={
        <HStack gap={3} vAlign="center" wrap="wrap">
          <TextInput
            size="lg"
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
            size="lg"
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
        </HStack>
      }
      endContent={actions}
    />
  );
}
