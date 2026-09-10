import { Moon, Sun } from "lucide-react";
import { Icon } from "@astryxdesign/core/Icon";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@astryxdesign/core/SegmentedControl";
import { VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";

import { useThemeStore } from "../../../shared/model/theme-store";

type Theme = "light" | "dark";

/** Раздел «Оформление» — тот же переключатель темы, что раньше жил в
 * `ProfilePopover` (`panel-shell.tsx`), просто перенесённый в диалог. */
export function AccountAppearanceSection() {
  const mode = useThemeStore((state) => state.mode);
  const setMode = useThemeStore((state) => state.setMode);

  return (
    <VStack gap={4}>
      <Heading level={4}>Оформление</Heading>
      <VStack gap={1.5}>
        <Text type="supporting" color="secondary">
          Тема интерфейса
        </Text>
        <SegmentedControl
          label="Тема"
          value={mode === "system" ? "light" : mode}
          onChange={(v) => setMode(v as Theme)}
          size="sm"
        >
          <SegmentedControlItem
            value="light"
            label="Светлая"
            icon={<Icon icon={Sun} size="xsm" />}
          />
          <SegmentedControlItem
            value="dark"
            label="Тёмная"
            icon={<Icon icon={Moon} size="xsm" />}
          />
        </SegmentedControl>
      </VStack>
    </VStack>
  );
}
