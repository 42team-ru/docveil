import { type ReactNode } from "react";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Badge } from "@astryxdesign/core/Badge";
import { Icon, type IconType } from "@astryxdesign/core/Icon";
import { NavIcon } from "@astryxdesign/core/NavIcon";
import { HStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { TopNav, TopNavHeading, TopNavItem } from "@astryxdesign/core/TopNav";

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
  /** Доп. содержимое в левой части шапки, перед основной навигацией. */
  navStartContent?: ReactNode;
  /** Доп. содержимое в правой части шапки — перед меню аккаунта. */
  navEndContent?: ReactNode;
  /** Аватар/меню аккаунта — `<AccountTrigger />` из `features/account`.
   * Пробрасывается пропом, а не импортируется здесь напрямую: `shared` не
   * должен зависеть от `features` (направление импортов FSD). */
  accountTrigger: ReactNode;
  children: ReactNode;
};

/**
 * Оболочка приложения: горизонтальное меню сверху + область контента.
 */
export function PanelShell({
  heading,
  subheading,
  headingIcon,
  groups,
  currentPath,
  navStartContent,
  navEndContent,
  accountTrigger,
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
              className="font-brand"
              heading={heading}
              subheading={subheading}
              logo={headingIcon ? <NavIcon icon={headingIcon} /> : undefined}
              headingHref="/documents"
            />
          }
          startContent={
            <>
              {navStartContent}
              {items.map((item) => (
                <TopNavItem
                  key={item.to}
                  as={RouterLink}
                  href={item.to}
                  label={item.label}
                  icon={<Icon icon={item.icon} size="sm" />}
                  isSelected={
                    currentPath === item.to ||
                    currentPath.startsWith(`${item.to}/`)
                  }
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
              {accountTrigger}
            </HStack>
          }
        />
      }
    >
      {children}
    </AppShell>
  );
}
