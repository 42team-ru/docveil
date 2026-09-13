import { useState } from "react";
import { Plus, Settings, X } from "lucide-react";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { CheckboxList, CheckboxListItem } from "@astryxdesign/core/CheckboxList";
import { Code } from "@astryxdesign/core/Code";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Grid } from "@astryxdesign/core/Grid";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { SelectableCard } from "@astryxdesign/core/SelectableCard";
import { Section } from "@astryxdesign/core/Section";
import { Token } from "@astryxdesign/core/Token";

import { piiTypeOptions } from "../../../entity/pii/model/pii-type-dict";
import { useCustomTypesStore } from "../../custom-types-compiler/model/store";
import { useRuleProfileStore } from "../../../entity/rule-profile/model/rule-profile-store";
import type { MaskStyle } from "../../../entity/rule-profile/model/types";
import { pluralRu } from "../../../shared/lib/plural-ru";

const ALL_TYPE_OPTIONS = piiTypeOptions();
/** Сколько типов ПДн знает движок. */
const REGISTRY_TYPE_COUNT = ALL_TYPE_OPTIONS.length;

/**
 * Как «Поставщик»/«ИНН» из примера выглядят в превью каждого стиля маски.
 * Не `bg-accent`/`text-accent`: в этой теме accent — нейтральный чёрно-белый
 * бренд-токен (`neutralTheme.ts`), а не синий, поэтому подсветка маркера на
 * нём не читалась. Синий берём из отдельной hue-палитры (`bg-blue-subtle`/
 * `text-blue-vivid`), которая accent-ом не переопределяется.
 */
const HIGHLIGHT_CLASS: Record<MaskStyle, string> = {
  marker: "bg-blue-subtle text-blue-vivid",
  blackbox: "bg-primary text-transparent",
};

/** Подписи стилей маски — переиспользуются в подтверждении запуска на `UploadPage`. */
export const MASK_STYLE_OPTIONS: Array<{
  id: MaskStyle;
  name: string;
  description: string;
}> = [
  {
    id: "marker",
    name: "Маркер",
    description: "Маркер с подсветкой — видно, что и на что заменено.",
  },
  {
    id: "blackbox",
    name: "Заливка",
    description: "Сплошная заливка — исходное значение закрыто целиком.",
  },
];

type MaskStylePickerProps = {
  /** Вызывается при клике «+ Добавить свой тип» — открытие диалога компилятора. */
  onAddCustomType?: () => void;
  /** Идёт загрузка файла для компилятора. */
  isAddingCustomType?: boolean;
};

/** Как выглядит маска в выходном документе — независимо от того, что удаляется. */
export function MaskStylePicker({ onAddCustomType, isAddingCustomType = false }: MaskStylePickerProps) {
  const maskStyle = useRuleProfileStore((state) => state.maskStyle);
  const setMaskStyle = useRuleProfileStore((state) => state.setMaskStyle);

  const highlightChanges = useRuleProfileStore(
    (state) => state.highlightChanges,
  );
  const setHighlightChanges = useRuleProfileStore(
    (state) => state.setHighlightChanges,
  );
  const keepTables = useRuleProfileStore((state) => state.keepTables);
  const setKeepTables = useRuleProfileStore((state) => state.setKeepTables);
  const stableMarkers = useRuleProfileStore((state) => state.stableMarkers);
  const setStableMarkers = useRuleProfileStore(
    (state) => state.setStableMarkers,
  );
  const enabledTypes = useRuleProfileStore((state) => state.enabledTypes);
  const setEnabledTypes = useRuleProfileStore((state) => state.setEnabledTypes);
  const customTypes = useCustomTypesStore((state) => state.types);
  const removeCustomType = useCustomTypesStore((state) => state.removeType);

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const selectedOption = MASK_STYLE_OPTIONS.find(
    (option) => option.id === maskStyle,
  );

  // [] = все выбраны (поведение бэкенда), иначе — подмножество
  const allSelected = enabledTypes.length === 0;
  const someSelected = !allSelected && enabledTypes.length > 0;
  const selectAllValue = allSelected
    ? true
    : someSelected
      ? "indeterminate"
      : false;

  function handleSelectAll() {
    setEnabledTypes(allSelected ? ALL_TYPE_OPTIONS.map((o) => o.value) : []);
  }

  return (
    <Section padding={0}>
      <VStack gap={3} paddingBlock={4} paddingInline={4}>
        <VStack gap={1}>
          <Heading level={4}>Как выглядит маска</Heading>
        </VStack>
        <Grid columns={2} gap={4} align="start">
          {MASK_STYLE_OPTIONS.map((option) => {
            const isSelected = maskStyle === option.id;
            const highlight = HIGHLIGHT_CLASS[option.id];
            return (
              <SelectableCard
                key={option.id}
                label={option.name}
                padding={3}
                isSelected={isSelected}
                variant={isSelected ? "blue" : "default"}
                onChange={() => setMaskStyle(option.id)}
              >
                <HStack gap={4} vAlign="center">
                  <StackItem size="fill" className="min-w-0">
                    <VStack gap={2}>
                      <HStack gap={2} vAlign="center">
                        <Text weight="medium">{option.name}</Text>
                        {isSelected ? (
                          <IconButton
                            size="sm"
                            variant="primary"
                            icon={<Icon icon={Settings} size="sm" />}
                            label={`Настройки режима «${option.name}»`}
                            onClick={(event) => {
                              event.stopPropagation();
                              setIsSettingsOpen(true);
                            }}
                          />
                        ) : null}
                      </HStack>
                      <Text type="supporting" size="sm" color="secondary">
                        {option.description}
                      </Text>
                    </VStack>
                  </StackItem>

                  <Section
                    variant="transparent"
                    padding={3}
                    width="fit-content"
                    maxWidth="60%"
                    className="mr-4 my-auto shrink-0 bg-surface rounded-lg border border-border"
                  >
                    <VStack gap={1}>
                      <Text type="code" size="sm" color="secondary">
                        {"Поставщик: ООО «"}
                        <Code className={highlight}>Ромашка</Code>
                        {"»"}
                      </Text>
                      <Text type="code" size="sm" color="secondary">
                        {"ИНН: "}
                        <Code className={highlight}>7712345678</Code>
                      </Text>
                    </VStack>
                  </Section>
                </HStack>
              </SelectableCard>
            );
          })}
        </Grid>
      </VStack>

      <Section variant="transparent" padding={0} dividers={["top"]}>
        <VStack gap={3} paddingBlock={4} paddingInline={4}>
          <VStack gap={1}>
            <Heading level={4}>Типы персональных данных</Heading>
            <Text type="supporting" size="sm" color="secondary">
              {allSelected
                ? `Маскируются все ${REGISTRY_TYPE_COUNT} ${pluralRu(REGISTRY_TYPE_COUNT, ["тип", "типа", "типов"])} — снимите флажок, чтобы выбрать конкретные`
                : `Выбрано ${enabledTypes.length} из ${REGISTRY_TYPE_COUNT}`}
            </Text>
          </VStack>
          <CheckboxInput
            label="Все типы"
            value={selectAllValue}
            onChange={handleSelectAll}
          />
          {!allSelected && (
            <CheckboxList
              label="Типы ПДн"
              isLabelHidden
              value={enabledTypes}
              onChange={setEnabledTypes}
              density="compact"
            >
              {ALL_TYPE_OPTIONS.map((opt) => (
                <CheckboxListItem key={opt.value} value={opt.value} label={opt.label} />
              ))}
            </CheckboxList>
          )}
        </VStack>
      </Section>

      <Section variant="transparent" padding={0} dividers={["top"]}>
        <VStack gap={3} paddingBlock={4} paddingInline={4}>
          <HStack gap={2} vAlign="center">
            <Heading level={4}>Свои типы данных</Heading>
            <StackItem size="fill" />
            {onAddCustomType && (
              <IconButton
                size="sm"
                variant="secondary"
                icon={<Icon icon={Plus} size="sm" />}
                label="Добавить свой тип"
                isDisabled={isAddingCustomType}
                onClick={onAddCustomType}
              />
            )}
          </HStack>
          {customTypes.length === 0 ? (
            <Text type="supporting" size="sm" color="secondary">
              Добавьте тип данных на русском — компилятор составит детектор автоматически.
            </Text>
          ) : (
            <VStack gap={2}>
              {customTypes.map((t, index) => {
                const name =
                  t.outcome === "use_builtin"
                    ? (t.type_id ?? "встроенный")
                    : (t.spec?.title ?? `Тип ${index + 1}`);
                return (
                  <HStack key={index} gap={2} vAlign="center">
                    <Token label={name} />
                    <IconButton
                      size="sm"
                      variant="ghost"
                      icon={<Icon icon={X} size="sm" />}
                      label={`Удалить тип «${name}»`}
                      onClick={() => removeCustomType(index)}
                    />
                  </HStack>
                );
              })}
            </VStack>
          )}
        </VStack>
      </Section>

      <Dialog
        isOpen={isSettingsOpen}
        onOpenChange={setIsSettingsOpen}
        purpose="form"
        width={420}
      >
        <Layout
          header={
            <DialogHeader
              title={`Настройки режима «${selectedOption?.name}»`}
              onOpenChange={setIsSettingsOpen}
            />
          }
          content={
            <LayoutContent>
              <VStack gap={2}>
                {maskStyle === "marker" ? (
                  <>
                    <CheckboxInput
                      label="Подсвечивать изменённые фрагменты"
                      value={highlightChanges}
                      onChange={() => setHighlightChanges(!highlightChanges)}
                    />
                    <CheckboxInput
                      label="Стабильные номера маркеров между запусками"
                      value={stableMarkers}
                      onChange={() => setStableMarkers(!stableMarkers)}
                    />
                  </>
                ) : (
                  <CheckboxInput
                    label="Сохранять структуру таблиц"
                    value={keepTables}
                    onChange={() => setKeepTables(!keepTables)}
                  />
                )}
              </VStack>
            </LayoutContent>
          }
        />
      </Dialog>
    </Section>
  );
}
