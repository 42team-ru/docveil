import { useState } from "react";
import { Settings } from "lucide-react";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
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

import { useRuleProfileStore } from "../../../entity/rule-profile/model/rule-profile-store";
import type { MaskStyle } from "../../../entity/rule-profile/model/types";

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

const MASK_STYLE_OPTIONS: Array<{
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

/** Как выглядит маска в выходном документе — независимо от того, что удаляется. */
export function MaskStylePicker() {
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

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const selectedOption = MASK_STYLE_OPTIONS.find(
    (option) => option.id === maskStyle,
  );

  return (
    <Section padding={0}>
      <VStack gap={3} paddingBlock={4} paddingInline={4}>
        <Heading level={4}>Как выглядит маска</Heading>
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
