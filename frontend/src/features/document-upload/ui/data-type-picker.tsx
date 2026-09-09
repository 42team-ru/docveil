import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Grid } from "@astryxdesign/core/Grid";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { SelectableCard } from "@astryxdesign/core/SelectableCard";
import { Section } from "@astryxdesign/core/Section";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";

import {
  piiTypeLabel,
  piiTypeMarkerPrefix,
  piiTypeOptions,
} from "../../../entity/pii/model/pii-type-dict";
import { defaultEnabledTypes, rulePresets } from "../../../entity/rule-profile/model/fixtures";
import { useRuleProfileStore } from "../../../entity/rule-profile/model/rule-profile-store";
import type { DataType } from "../../../entity/rule-profile/model/types";

/**
 * Список категорий строится из общего словаря типов, а не из собственного
 * перечисления: идентификаторы обязаны совпадать с `EntityType` движка, иначе
 * оператор включает тип, которого бэкенд не знает. Показываются все типы
 * реестра, включая `money` и `bank_name` — они объявлены в реестре, хотя
 * детектора у них пока нет.
 */
const dataTypes: DataType[] = piiTypeOptions().map(({ value }) => ({
  id: value,
  name: piiTypeLabel(value),
  marker: `[${piiTypeMarkerPrefix(value)}]`,
}));

const ALL_TYPE_IDS = dataTypes.map((type) => type.id);

/**
 * Список типов на пресет: раньше клик по карточке пресета менял только
 * подсветку (`preset` в сторе), а `enabledTypes` — то, что реально уходит
 * в `POST /api/runs` — никогда не трогал. Из трёх пресетов только «Тендерная
 * документация» случайно совпадал с начальным значением стора; «Максимальное
 * обезличивание» и «Финансовый отчёт» были декоративными.
 *
 * `full` — весь реестр (`ALL_TYPE_IDS`), как и заявлено в описании пресета.
 * `fin` — весь реестр без `org_name`/`person`: описание оставляет только
 * «названия сторон», а счета/суммы/сроки — не единственное, что упомянуто
 * в реестре из финансово-значимого; при неопределённости recall важнее
 * precision (AGENTS.md), поэтому лучше замаскировать лишнее, чем пропустить
 * критичный тип вроде ИНН или паспорта.
 */
const PRESET_TYPES: Record<string, string[]> = {
  tender: defaultEnabledTypes,
  full: ALL_TYPE_IDS,
  fin: ALL_TYPE_IDS.filter((id) => id !== "org_name" && id !== "person"),
};

export function DataTypePicker() {
  const selectionMode = useRuleProfileStore((state) => state.selectionMode);
  const setSelectionMode = useRuleProfileStore((state) => state.setSelectionMode);

  const presetId = useRuleProfileStore((state) => state.preset);
  const setPreset = useRuleProfileStore((state) => state.setPreset);

  const enabledTypes = useRuleProfileStore((state) => state.enabledTypes);
  const toggleType = useRuleProfileStore((state) => state.toggleType);
  const selectAllTypes = useRuleProfileStore((state) => state.selectAllTypes);

  return (
    <Section padding={0}>
      <VStack gap={5} paddingBlock={4}>
        <HStack gap={4} vAlign="center" paddingInline={4} wrap="wrap">
          <Heading level={4}>Что удалять</Heading>
          <StackItem size="fill" />
          <SegmentedControl
            label="Режим выбора правил"
            value={selectionMode}
            onChange={(val) => {
              const mode = val as "preset" | "manual";
              setSelectionMode(mode);
              // Возврат в «Профиль» после ручных правок обязан вернуть
              // enabledTypes к списку уже выбранного пресета, иначе подсвеченная
              // карточка врёт про то, что реально уйдёт в POST /api/runs.
              if (mode === "preset") {
                selectAllTypes(PRESET_TYPES[presetId] ?? []);
              }
            }}
          >
            <SegmentedControlItem value="preset" label="Профиль" />
            <SegmentedControlItem value="manual" label="Вручную" />
          </SegmentedControl>
        </HStack>

        <VStack gap={3} paddingInline={4}>
          <Grid columns={{ minWidth: 200, max: 3, repeat: "fit" }} gap={2}>
            {rulePresets.map((preset) => {
              const isSelected = selectionMode === "preset" && presetId === preset.id;
              return (
                <SelectableCard
                  key={preset.id}
                  label={preset.name}
                  padding={3}
                  isSelected={isSelected}
                  isDisabled={selectionMode !== "preset"}
                  variant={isSelected ? "blue" : "default"}
                  onChange={() => {
                    setSelectionMode("preset");
                    setPreset(preset.id);
                    selectAllTypes(PRESET_TYPES[preset.id] ?? []);
                  }}
                >
                  <VStack gap={0.5}>
                    <Text weight="medium">{preset.name}</Text>
                    <Text type="supporting" size="sm" color="secondary">
                      {preset.description}
                    </Text>
                  </VStack>
                </SelectableCard>
              );
            })}
          </Grid>
        </VStack>

        <VStack gap={3} paddingInline={4}>
          <HStack gap={2} vAlign="center" wrap="wrap">
            <Text type="supporting" weight="medium">
              Отдельные категории данных
            </Text>
            {selectionMode === "manual" ? (
              <Badge
                variant="neutral"
                className="bg-surface border border-border"
                label={`выбрано ${enabledTypes.length} из ${dataTypes.length}`}
              />
            ) : null}
            <StackItem size="fill" />
            <Button
              size="sm"
              variant="ghost"
              label="Выбрать все"
              isDisabled={selectionMode !== "manual" || enabledTypes.length === dataTypes.length}
              onClick={() => {
                setSelectionMode("manual");
                selectAllTypes(ALL_TYPE_IDS);
              }}
            />
          </HStack>
          <Grid columns={{ minWidth: 200, max: 3, repeat: "fit" }} gap={2}>
            {dataTypes.map((type) => {
              return (
                <CheckboxInput
                  key={type.id}
                  label={type.name}
                  description={type.marker}
                  value={enabledTypes.includes(type.id)}
                  isDisabled={selectionMode !== "manual"}
                  onChange={() => {
                    toggleType(type.id);
                  }}
                />
              );
            })}
          </Grid>
        </VStack>
      </VStack>
    </Section>
  );
}
