import { Check, Plus, X } from "lucide-react";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Code } from "@astryxdesign/core/Code";
import { Grid } from "@astryxdesign/core/Grid";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { SelectableCard } from "@astryxdesign/core/SelectableCard";
import { Section } from "@astryxdesign/core/Section";
import { Token } from "@astryxdesign/core/Token";

import { piiTypeOptions } from "../../../entity/pii/model/pii-type-dict";
import {
  hasAnyTypeSelected,
  toggleAllTypes,
  updateTypeSelection,
} from "../lib/masking-type-selection";
import { useCustomTypesStore } from "../../custom-types-compiler/model/store";
import type { HighlightColor } from "../../../entity/rule-profile/model/rule-profile-store";
import { useRuleProfileStore } from "../../../entity/rule-profile/model/rule-profile-store";
import type { MaskStyle } from "../../../entity/rule-profile/model/types";
import { pluralRu } from "../../../shared/lib/plural-ru";

/**
 * Курируемая палитра, а не произвольный color-picker: бухгалтеру проще
 * выбрать из шести узнаваемых цветов маркера, чем подбирать hex руками.
 * Значения — реальные `#RRGGBB`, которые уйдут в документ как есть
 * (`RunCreateRequest.highlight_background`) — это данные результата, а не
 * тема интерфейса, поэтому квадраты ниже красятся инлайн-стилем по тому же
 * прецеденту, что и в `docx-viewer.tsx` (см. его комментарий).
 */
const HIGHLIGHT_COLOR_OPTIONS: Array<{ value: HighlightColor; label: string }> = [
  { value: "#FFDE66", label: "Жёлтый" },
  { value: "#A8E6A1", label: "Зелёный" },
  { value: "#A8D4FF", label: "Голубой" },
  { value: "#FFB3D9", label: "Розовый" },
  { value: "#FFC680", label: "Оранжевый" },
  { value: "#D0D0D0", label: "Серый" },
];

const ALL_TYPE_OPTIONS = piiTypeOptions();
/** Сколько типов ПДн знает движок. */
const REGISTRY_TYPE_COUNT = ALL_TYPE_OPTIONS.length;

/**
 * Превью показывает то, что реально попадёт в документ — не исходное
 * значение с подсветкой поверх (так было раньше, и это была неправда):
 * "Маркер" стирает исходный текст и пишет вместо него `[ТИП]`, "Заливка"
 * стирает его вообще без следа — как сплошная чёрная плашка поверх строки
 * в самом документе, а не текст из символов `█`.
 */
const PREVIEW_ORG = { marker: "[ОРГАНИЗАЦИЯ]" } as const;
const PREVIEW_INN = { marker: "[ИНН]" } as const;

/** Ширина плашки под примерную длину скрытого значения — не про пиксели темы, а про то, как реально выглядит "Заливка" в документе. */
function BlackboxBar({ width }: { width: number }) {
  return (
    <span
      aria-label="скрыто"
      style={{
        display: "inline-block",
        width,
        height: "0.9em",
        verticalAlign: "middle",
        backgroundColor: "#000000",
        borderRadius: 2,
      }}
    />
  );
}

/** Подписи стилей маски — переиспользуются в подтверждении запуска на `UploadPage`. */
export const MASK_STYLE_OPTIONS: Array<{
  id: MaskStyle;
  name: string;
  description: string;
}> = [
  {
    id: "marker",
    name: "Маркер (рекомендуется)",
    description:
      "Текст заменяется читаемой пометкой вроде [ИНН] — видно, что именно и где скрыто.",
  },
  {
    id: "blackbox",
    name: "Заливка",
    description:
      "Текст закрывается сплошным чёрным прямоугольником — не видно вообще ничего, даже какого поле типа.",
  },
];

type MaskStylePickerProps = {
  /** Вызывается при клике «+ Добавить свой тип» — открытие диалога компилятора. */
  onAddCustomType?: () => void;
  /** Идёт загрузка файла для компилятора. */
  isAddingCustomType?: boolean;
};

/** Как выглядит маска в выходном документе — независимо от того, что удаляется. */
export function MaskStylePicker({
  onAddCustomType,
  isAddingCustomType = false,
}: MaskStylePickerProps) {
  const isNarrow = useMediaQuery("(max-width: 600px)", false);
  const maskStyle = useRuleProfileStore((state) => state.maskStyle);
  const setMaskStyle = useRuleProfileStore((state) => state.setMaskStyle);
  const highlightColor = useRuleProfileStore((state) => state.highlightColor);
  const setHighlightColor = useRuleProfileStore(
    (state) => state.setHighlightColor,
  );
  const enabledTypes = useRuleProfileStore((state) => state.enabledTypes);
  const setEnabledTypes = useRuleProfileStore((state) => state.setEnabledTypes);
  const customTypes = useCustomTypesStore((state) => state.types);
  const removeCustomType = useCustomTypesStore((state) => state.removeType);

  // null = все выбраны; пустой список теперь означает, что не выбран никто.
  const allSelected = enabledTypes === null;
  const selectAllValue = allSelected
    ? true
    : (enabledTypes?.length ?? 0) > 0
      ? "indeterminate"
      : false;

  function handleSelectAll() {
    setEnabledTypes(toggleAllTypes(enabledTypes));
  }

  const canStartWithSelection = hasAnyTypeSelected(enabledTypes, customTypes.length);

  return (
    <Section padding={0}>
      <VStack gap={3} paddingBlock={4} paddingInline={4}>
        <VStack gap={1}>
          <Heading level={4}>Чем закрывать найденное</Heading>
          <Text type="supporting" size="sm" color="secondary">
            Превью ниже — то, что реально окажется в документе, не исходный текст с подсветкой.
          </Text>
        </VStack>
        <Grid columns={{ minWidth: 280, max: 2, repeat: "fit" }} gap={4} align="start">
          {MASK_STYLE_OPTIONS.map((option) => {
            const isSelected = maskStyle === option.id;
            // Блоки для "Заливки" уже сами по себе тёмные символы — фон не
            // нужен. У "Маркера" фон — реально выбранный цвет, а не токен
            // темы (см. комментарий у HIGHLIGHT_COLOR_OPTIONS).
            const previewStyle =
              option.id === "marker" ? { backgroundColor: highlightColor } : undefined;
            return (
              <SelectableCard
                key={option.id}
                label={option.name}
                padding={3}
                isSelected={isSelected}
                variant={isSelected ? "blue" : "default"}
                onChange={() => setMaskStyle(option.id)}
              >
                <VStack gap={3}>
                  <HStack gap={4} vAlign="center" wrap={isNarrow ? "wrap" : "nowrap"}>
                    <StackItem size="fill" className={isNarrow ? "min-w-0 w-full" : "min-w-0"}>
                      <VStack gap={2}>
                        <Text weight="medium">{option.name}</Text>
                        <Text type="supporting" size="sm" color="secondary">
                          {option.description}
                        </Text>
                      </VStack>
                    </StackItem>

                    <Section
                      variant="transparent"
                      padding={3}
                      width="fit-content"
                      maxWidth={isNarrow ? "100%" : "60%"}
                      className="my-auto shrink-0 bg-surface rounded-lg border border-border"
                    >
                      <VStack gap={1}>
                        <Text type="code" size="sm" color="secondary">
                          {"Поставщик: ООО «"}
                          {option.id === "blackbox" ? (
                            <BlackboxBar width={84} />
                          ) : (
                            <Code className="text-primary" style={previewStyle}>
                              {PREVIEW_ORG.marker}
                            </Code>
                          )}
                          {"»"}
                        </Text>
                        <Text type="code" size="sm" color="secondary">
                          {"ИНН: "}
                          {option.id === "blackbox" ? (
                            <BlackboxBar width={64} />
                          ) : (
                            <Code className="text-primary" style={previewStyle}>
                              {PREVIEW_INN.marker}
                            </Code>
                          )}
                        </Text>
                      </VStack>
                    </Section>
                  </HStack>

                  {option.id === "marker" && isSelected ? (
                    <VStack
                      gap={2}
                      paddingBlockStart={2}
                      className="border-t border-border"
                    >
                      <Text type="label" weight="medium">
                        Цвет маркера
                      </Text>
                      <HStack
                        gap={2}
                        wrap="wrap"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {HIGHLIGHT_COLOR_OPTIONS.map((colorOption) => {
                          const isColorSelected = highlightColor === colorOption.value;
                          return (
                            <SelectableCard
                              key={colorOption.value}
                              label={colorOption.label}
                              isSelected={isColorSelected}
                              padding={1}
                              width={36}
                              height={36}
                              onChange={() => setHighlightColor(colorOption.value)}
                            >
                              {/* `variant` красит фон самой карточки, а не кольцо выбора —
                                  на маленьком квадрате inset-рамка `isSelected` слишком
                                  незаметна на разных цветах. Галочка внутри — однозначный
                                  индикатор независимо от фонового цвета. */}
                              <VStack
                                width="100%"
                                height="100%"
                                hAlign="center"
                                vAlign="center"
                                style={{ backgroundColor: colorOption.value, borderRadius: 4 }}
                              >
                                {isColorSelected ? (
                                  <Icon icon={Check} size="sm" color="primary" />
                                ) : null}
                              </VStack>
                            </SelectableCard>
                          );
                        })}
                      </HStack>
                    </VStack>
                  ) : null}
                </VStack>
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
                : `Выбрано ${enabledTypes?.length ?? 0} из ${REGISTRY_TYPE_COUNT}`}
            </Text>
          </VStack>
          <HStack gap={2} vAlign="center">
            <CheckboxInput
              label="Все типы"
              value={selectAllValue}
              onChange={handleSelectAll}
            />
            <Button
              size="sm"
              variant="ghost"
              label="Убрать все"
              isDisabled={enabledTypes !== null && enabledTypes.length === 0}
              onClick={() => setEnabledTypes([])}
            />
          </HStack>
          {!allSelected && (
            <VStack gap={2}>
              <Grid columns={{ minWidth: 150, max: 4, repeat: "fit" }} gap={2}>
                {ALL_TYPE_OPTIONS.map((opt) => (
                  <CheckboxInput
                    key={opt.value}
                    label={opt.label}
                    value={enabledTypes?.includes(opt.value) ?? false}
                    onChange={(checked) => {
                      setEnabledTypes(
                        updateTypeSelection(
                          enabledTypes,
                          opt.value,
                          checked,
                          ALL_TYPE_OPTIONS.map((option) => option.value),
                        ),
                      );
                    }}
                  />
                ))}
              </Grid>
              {!canStartWithSelection ? (
                <Text type="supporting" size="sm" color="secondary">
                  Выберите хотя бы один тип или добавьте свой, чтобы начать обработку.
                </Text>
              ) : null}
            </VStack>
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
              Добавьте тип данных на русском — компилятор составит детектор
              автоматически.
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
    </Section>
  );
}
