import type { ReactNode } from "react";
import { Heading } from "@astryxdesign/core/Text";
import { HStack } from "@astryxdesign/core/Stack";
import {
  Layout,
  LayoutContent,
  LayoutHeader,
} from "@astryxdesign/core/Layout";
import { Toolbar } from "@astryxdesign/core/Toolbar";

type SpacingStep = 0 | 0.5 | 1 | 1.5 | 2 | 3 | 4 | 5 | 6 | 8 | 10;

type ScreenLayoutProps = {
  /**
   * Заголовок экрана. Рендерится как h4 с aria-level=1 — это h1 страницы.
   * Без заголовка Heading не рендерится вовсе — экран остаётся без h1.
   */
  title?: string;
  /** Короткий контекст справа от заголовка: счётчики, шаг, имя файла. */
  meta?: ReactNode;
  /** Содержимое перед заголовком: чип формата, иконка. */
  startContent?: ReactNode;
  /**
   * Переключатель вкладок экрана (`TabList`) — с большим отступом от действий,
   * в самом правом углу шапки. Так проверка и отчёт документа делят одну
   * шапку и переключаются без смены страницы, а таб не путается с кнопками.
   */
  tabs?: ReactNode;
  /** Кнопки в правой части шапки, левее вкладок. */
  actions?: ReactNode;
  /** Правая панель экрана (`LayoutPanel`). */
  panel?: ReactNode;
  /**
   * `id` тела экрана — цель `aria-controls` у `tabs`, когда `TabList` там
   * работает в паттерне `role="tablist"`, а не как навигация.
   */
  contentId?: string;
  contentPadding?: SpacingStep;
  isContentScrollable?: boolean;
  children: ReactNode;
};

/**
 * Единая рамка для всех экранов панели: закреплённая шапка, прокручиваемое тело
 * и необязательная правая панель. Держит шапки экранов на одной контентной линии.
 */
export function ScreenLayout({
  title,
  meta,
  startContent,
  tabs,
  actions,
  panel,
  contentId,
  contentPadding = 6,
  isContentScrollable = true,
  children,
}: ScreenLayoutProps) {
  const hasHeader =
    title !== undefined ||
    meta !== undefined ||
    startContent !== undefined ||
    tabs !== undefined ||
    actions !== undefined;

  return (
    <Layout
      height="fill"
      header={hasHeader ? (
        <LayoutHeader hasDivider>
          <Toolbar
            label={title ?? "Экран"}
            size="sm"
            startContent={
              <HStack gap={2} vAlign="center">
                {startContent}
                {title !== undefined && (
                  <Heading level={4} accessibilityLevel={1}>
                    {title}
                  </Heading>
                )}
                {meta}
              </HStack>
            }
            endContent={
              tabs !== undefined ? (
                <HStack gap={8} vAlign="center">
                  {actions}
                  {tabs}
                </HStack>
              ) : (
                actions
              )
            }
          />
        </LayoutHeader>
      ) : undefined}
      content={
        <LayoutContent
          id={contentId}
          padding={contentPadding}
          isScrollable={isContentScrollable}
        >
          {children}
        </LayoutContent>
      }
      end={panel}
    />
  );
}
