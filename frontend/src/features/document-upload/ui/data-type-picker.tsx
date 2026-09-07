import { Button } from "@astryxdesign/core/Button";
import { Grid } from "@astryxdesign/core/Grid";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { SelectableCard } from "@astryxdesign/core/SelectableCard";
import { Section } from "@astryxdesign/core/Section";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";

import {
  piiTypeLabel,
  piiTypeMarkerPrefix,
  piiTypeOptions,
} from "../../../entity/pii/model/pii-type-dict";
import { rulePresets } from "../../../entity/rule-profile/model/fixtures";
import { useRuleProfileStore } from "../../../entity/rule-profile/model/rule-profile-store";
import type { DataType, MaskStyle } from "../../../entity/rule-profile/model/types";

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

export function DataTypePicker() {
  const selectionMode = useRuleProfileStore((state) => state.selectionMode);
  const setSelectionMode = useRuleProfileStore((state) => state.setSelectionMode);

  const presetId = useRuleProfileStore((state) => state.preset);
  const setPreset = useRuleProfileStore((state) => state.setPreset);

  const enabledTypes = useRuleProfileStore((state) => state.enabledTypes);
  const toggleType = useRuleProfileStore((state) => state.toggleType);
  const selectAllTypes = useRuleProfileStore((state) => state.selectAllTypes);

  const maskStyle = useRuleProfileStore((state) => state.maskStyle);
  const setMaskStyle = useRuleProfileStore((state) => state.setMaskStyle);

  return (
    <Section padding={0}>
      <VStack gap={5} paddingBlock={4}>
        <HStack gap={4} vAlign="center" paddingInline={4} wrap="wrap">
          <Heading level={5}>Что удалять</Heading>
          <StackItem size="fill" />
          <SegmentedControl
            label="Режим выбора правил"
            value={selectionMode}
            onChange={(val) => setSelectionMode(val as "preset" | "manual")}
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
          <HStack gap={4} vAlign="center" wrap="wrap">
            <VStack gap={0.5}>
              <Text type="supporting" weight="medium">
                Как выглядит маска
              </Text>
              <Text type="supporting" size="sm" color="secondary">
                {maskStyle === "marker"
                  ? "Маркер с подсветкой — видно, что и на что заменено."
                  : "Сплошная заливка — исходное значение закрыто целиком."}
              </Text>
            </VStack>
            <StackItem size="fill" />
            <SegmentedControl
              size="sm"
              label="Стиль маски"
              value={maskStyle}
              onChange={(value) => setMaskStyle(value as MaskStyle)}
            >
              <SegmentedControlItem value="marker" label="Маркер" />
              <SegmentedControlItem value="blackbox" label="Заливка" />
            </SegmentedControl>
          </HStack>
        </VStack>

        <VStack gap={3} paddingInline={4}>
          <HStack gap={2} vAlign="center" wrap="wrap">
            <Text type="supporting" weight="medium">
              Отдельные категории данных
            </Text>
            <Text type="supporting" hasTabularNumbers color="secondary">
              {`выбрано ${enabledTypes.length} из ${dataTypes.length}`}
            </Text>
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
              const isSelected = selectionMode === "manual" && enabledTypes.includes(type.id);
              return (
                <SelectableCard
                  key={type.id}
                  label={type.name}
                  padding={3}
                  isSelected={isSelected}
                  isDisabled={selectionMode !== "manual"}
                  variant={isSelected ? "blue" : "default"}
                  onChange={() => {
                    setSelectionMode("manual");
                    toggleType(type.id);
                  }}
                >
                  <HStack gap={3} vAlign="center">
                    <StatusDot
                      variant={isSelected ? "accent" : "neutral"}
                      label={isSelected ? "Выбрано" : "Не выбрано"}
                    />
                    <VStack gap={0.5}>
                      <Text weight="medium">{type.name}</Text>
                      <Text type="code" size="sm" color="secondary">
                        {type.marker}
                      </Text>
                    </VStack>
                  </HStack>
                </SelectableCard>
              );
            })}
          </Grid>
        </VStack>
      </VStack>
    </Section>
  );
}
