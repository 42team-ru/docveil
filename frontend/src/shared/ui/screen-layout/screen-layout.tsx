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
  /** Заголовок экрана. Рендерится как h4 с aria-level=1 — это h1 страницы. */
  title: string;
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
  return (
    <Layout
      height="fill"
      header={
        <LayoutHeader hasDivider>
          <Toolbar
            label={title}
            size="sm"
            startContent={
              <HStack gap={2} vAlign="center">
                {startContent}
                <Heading level={4} accessibilityLevel={1}>
                  {title}
                </Heading>
                {meta}
              </HStack>
            }
            endContent={actions}
          />
        </LayoutHeader>
      }
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
