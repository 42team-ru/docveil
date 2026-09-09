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
  /** Кнопки в правой части шапки. */
  actions?: ReactNode;
  /** Правая панель экрана (`LayoutPanel`). */
  panel?: ReactNode;
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
  actions,
  panel,
  contentPadding = 6,
  isContentScrollable = true,
  children,
}: ScreenLayoutProps) {
  const hasHeader =
    title !== undefined ||
    meta !== undefined ||
    startContent !== undefined ||
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
            endContent={actions}
          />
        </LayoutHeader>
      ) : undefined}
      content={
        <LayoutContent
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
