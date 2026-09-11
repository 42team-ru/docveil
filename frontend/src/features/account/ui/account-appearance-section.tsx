import { Moon, Sun } from "lucide-react";
import { Selector } from "@astryxdesign/core/Selector";
import { VStack } from "@astryxdesign/core/Stack";
import { Heading } from "@astryxdesign/core/Text";

import { useThemeStore } from "../../../shared/model/theme-store";

type Theme = "light" | "dark";

const themeOptions = [
  { value: "light", label: "Светлая", icon: Sun },
  { value: "dark", label: "Тёмная", icon: Moon },
];

/** Раздел «Оформление» — тот же переключатель темы, что раньше жил в
 * `ProfilePopover` (`panel-shell.tsx`), просто перенесённый в диалог. */
export function AccountAppearanceSection() {
  const mode = useThemeStore((state) => state.mode);
  const setMode = useThemeStore((state) => state.setMode);

  return (
    <VStack gap={4}>
      <Heading level={4}>Оформление</Heading>
      <VStack gap={1.5}>
        <Selector
          label="Тема"
          description="Выберите оформление, с которым удобнее работать."
          options={themeOptions}
          value={mode === "system" ? "light" : mode}
          onChange={(value) => setMode(value as Theme)}
          size="lg"
          width="100%"
          startIcon={mode === "dark" ? Moon : Sun}
        />
      </VStack>
    </VStack>
  );
}
