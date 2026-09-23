import type { ReactNode } from "react";
import { Search } from "lucide-react";
import { Selector } from "@astryxdesign/core/Selector";
import { HStack } from "@astryxdesign/core/Stack";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Toolbar } from "@astryxdesign/core/Toolbar";

import { STATUS_LABEL } from "../../../entity/document/ui/run-status-token";
import type { RunStatus } from "../../masking-run/api/masking-run";
import {
  useHistoryFilterStore,
  type HistoryStatusFilter,
} from "../model/history-filter-store";

/**
 * Порядок статусов в фильтре — от «в работе» к «завершено», как идёт прогон
 * по графу. `leaked` обязан быть здесь наравне с `failed`: это не «ошибка
 * сервера», а находка валидатора, и оператору нужно уметь отобрать именно её
 * (см. `run-status-token.tsx`).
 */
const STATUS_ORDER: RunStatus[] = [
  "queued",
  "running",
  "awaiting_answers",
  "awaiting_review",
  "done",
  "leaked",
  "failed",
];

const STATUS_OPTIONS = [
  { value: "all", label: "Все статусы" },
  ...STATUS_ORDER.map((status) => ({ value: status, label: STATUS_LABEL[status] })),
];

type HistoryFiltersProps = {
  /** Действия справа от фильтров — например, кнопка «Новая задача». */
  actions?: ReactNode;
};

/**
 * Фильтры журнала: поиск по имени документа и состояние прогона.
 *
 * Статус — выпадающий список, а не `SegmentedControl`: семь состояний
 * прогона плюс «Все» — восемь вариантов, больше, чем можно держать в
 * рабочей памяти одним взглядом (working-memory rule, ≤4). Раньше контрол
 * показывал только 4 из 7 — `queued`/`running`/`leaked` были недостижимы
 * через фильтр вовсе.
 */
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
        <HStack gap={3} vAlign="center" wrap="wrap" width="100%">
          <TextInput
            size="lg"
            label="Поиск по имени документа"
            isLabelHidden
            placeholder="Поиск по имени документа…"
            startIcon={Search}
            width="min(420px, 100%)"
            hasClear
            value={query}
            onChange={setQuery}
          />
          <Selector
            size="lg"
            label="Состояние прогона"
            isLabelHidden
            width={220}
            options={STATUS_OPTIONS}
            value={status}
            onChange={(value) => setStatus(value as HistoryStatusFilter)}
          />
          {actions}
        </HStack>
      }
    />
  );
}
