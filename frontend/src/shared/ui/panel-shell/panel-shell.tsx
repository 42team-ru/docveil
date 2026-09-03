import { type ReactNode } from "react";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Divider } from "@astryxdesign/core/Divider";
import { Icon, type IconType } from "@astryxdesign/core/Icon";
import { NavIcon } from "@astryxdesign/core/NavIcon";
import { Popover } from "@astryxdesign/core/Popover";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@astryxdesign/core/SegmentedControl";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { TopNav, TopNavHeading, TopNavItem } from "@astryxdesign/core/TopNav";
import { LogOut, Moon, Sun } from "lucide-react";

import { RouterLink } from "../router-link/router-link";

export type PanelNavItem = {
  to: string;
  label: string;
  icon: IconType;
  badge?: number;
};

export type PanelNavGroup = {
  title: string;
  items: PanelNavItem[];
};

type PanelShellProps = {
  /** Название продукта в шапке. */
  heading: string;
  subheading?: string;
  headingIcon?: ReactNode;
  groups: PanelNavGroup[];
  /** Текущий путь — по нему подсвечивается активный пункт. */
  currentPath: string;
  /** Доп. содержимое в правой части шапки — перед меню профиля. */
  navEndContent?: ReactNode;
  children: ReactNode;
};

import { useThemeStore } from "../../model/theme-store";

type Theme = "light" | "dark";

/** Всплывающее меню пользователя: смена темы и выход. */
function ProfilePopover() {
  const mode = useThemeStore((state) => state.mode);
  const setMode = useThemeStore((state) => state.setMode);

  return (
    <Popover
      placement="below"
      alignment="end"
      width={220}
      label="Меню пользователя"
      content={
        <VStack gap={3} padding={3}>
          {/* Пользователь */}
          <VStack gap={0}>
            <Text type="label" weight="medium">
              Иванов И.И.
            </Text>
            <Text type="supporting" color="secondary">
              ivanov@corp.triema.ru
            </Text>
          </VStack>

          <Divider />

          {/* Тема */}
          <VStack gap={1.5}>
            <Text type="supporting" color="secondary">
              Тема интерфейса
            </Text>
            <SegmentedControl
              label="Тема"
              value={mode === "system" ? "light" : mode}
              onChange={(v) => setMode(v as Theme)}
              size="sm"
              layout="fill"
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

          <Divider />

          {/* Выход */}
          <Button
            label="Выйти"
            variant="ghost"
            size="sm"
            icon={<Icon icon={LogOut} size="sm" />}
            href="/login"
          />
        </VStack>
      }
    >
      <Avatar
        name="Иванов И.И."
        src="https://i.pravatar.cc/80"
        size="md"
        tooltip={false}
        onClick={() => {}}
      />
    </Popover>
  );
}

/**
 * Оболочка приложения: горизontальное меню сверху + область контента.
 */
export function PanelShell({
  heading,
  subheading,
  headingIcon,
  groups,
  currentPath,
  navEndContent,
  children,
}: PanelShellProps) {
  const items = groups.flatMap((group) => group.items);

  return (
    <AppShell
      contentPadding={0}
      variant="section"
      topNav={
        <TopNav
          label="Основная навигация"
          heading={
            <TopNavHeading
              heading={heading}
              subheading={subheading}
              logo={headingIcon ? <NavIcon icon={headingIcon} /> : undefined}
              headingHref="/"
            />
          }
          startContent={
            <>
              {items.map((item) => (
                <TopNavItem
                  key={item.to}
                  as={RouterLink}
                  href={item.to}
                  label={item.label}
                  icon={<Icon icon={item.icon} size="sm" />}
                  isSelected={currentPath === item.to}
                >
                  {item.badge ? (
                    <HStack gap={1.5} vAlign="center">
                      <Text type="label" weight="medium">
                        {item.label}
                      </Text>
                      <Badge variant="info" label={item.badge} />
                    </HStack>
                  ) : undefined}
                </TopNavItem>
              ))}
            </>
          }
          endContent={
            <HStack gap={2} vAlign="center">
              {navEndContent}
              <ProfilePopover />
            </HStack>
          }
        />
      }
    >
      {children}
    </AppShell>
  );
}
