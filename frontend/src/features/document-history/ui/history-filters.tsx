import { Search } from "lucide-react";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@astryxdesign/core/SegmentedControl";
import { Selector } from "@astryxdesign/core/Selector";
import { HStack, StackItem } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Toolbar } from "@astryxdesign/core/Toolbar";

import { projects } from "../../../entity/document/model/fixtures";
import {
  ALL_PROJECTS,
  useHistoryFilterStore,
  type HistoryStatusFilter,
} from "../model/history-filter-store";

/** Ширина поля поиска — структурный размер контрола. */
const SEARCH_WIDTH = 300;

/** Фильтры истории: поиск, проект и состояние документа. */
export function HistoryFilters() {
  const query = useHistoryFilterStore((state) => state.query);
  const setQuery = useHistoryFilterStore((state) => state.setQuery);
  const project = useHistoryFilterStore((state) => state.project);
  const setProject = useHistoryFilterStore((state) => state.setProject);
  const status = useHistoryFilterStore((state) => state.status);
  const setStatus = useHistoryFilterStore((state) => state.setStatus);

  return (
    <Toolbar
      label="Фильтры истории"
      size="sm"
      gap={3}
      startContent={
        <HStack gap={3} vAlign="center" wrap="wrap">
          <TextInput
            size="sm"
            label="Поиск по истории"
            isLabelHidden
            placeholder="Поиск по имени, ИНН, номеру договора…"
            startIcon={Search}
            width={SEARCH_WIDTH}
            hasClear
            value={query}
            onChange={setQuery}
          />
          <Selector
            size="sm"
            label="Проект"
            isLabelHidden
            value={project}
            onChange={setProject}
            options={[
              { value: ALL_PROJECTS, label: "Все проекты" },
              ...projects.map((name) => ({ value: name, label: name })),
            ]}
          />
          <SegmentedControl
            size="sm"
            label="Состояние документа"
            value={status}
            onChange={(value) => setStatus(value as HistoryStatusFilter)}
          >
            <SegmentedControlItem value="all" label="Все" />
            <SegmentedControlItem value="review" label="На проверке" />
            <SegmentedControlItem value="ok" label="Утверждены" />
          </SegmentedControl>
          <StackItem size="fill" />
        </HStack>
      }
      endContent={
        <Text type="supporting">хранить 90 дней · автоочистка</Text>
      }
    />
  );
}
