import {
  isRouteErrorResponse,
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
} from "react-router";

import { useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";

import type { Route } from "./+types/root";
import "./styles/app.css";
import { neutralTheme } from "../themes/neutral/neutralTheme";
import { Button } from "@astryxdesign/core/Button";
import { Center } from "@astryxdesign/core/Center";
import { CodeBlock } from "@astryxdesign/core/CodeBlock";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { LinkProvider } from "@astryxdesign/core/Link";
import { VStack } from "@astryxdesign/core/Stack";
import { Theme } from "@astryxdesign/core/theme";
import { NotFoundPage } from "../pages/not-found/not-found-page";
import { createQueryClient } from "../shared/api/query-client";
import { RouterLink } from "../shared/ui/router-link/router-link";

export const links: Route.LinksFunction = () => [
  { rel: "preconnect", href: "https://fonts.googleapis.com" },
  {
    rel: "preconnect",
    href: "https://fonts.gstatic.com",
    crossOrigin: "anonymous",
  },
  {
    rel: "stylesheet",
    // Тема neutral объявляет Figtree — грузим именно её, иначе тема молча
    // падает на системный шрифт.
    href: "https://fonts.googleapis.com/css2?family=Figtree:ital,wght@0,300..900;1,300..900&display=swap",
  },
  {
    rel: "stylesheet",
    href: "https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&display=swap",
  },
  { rel: "icon", type: "image/png", href: "/logo.png" },
];

export const meta: Route.MetaFunction = () => [{ title: "DocVeil" }];

import { useThemeStore } from "../shared/model/theme-store";

export function Layout({ children }: { children: React.ReactNode }) {
  const mode = useThemeStore((state) => state.mode);

  return (
    <html lang="ru">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <Meta />
        <Links />
      </head>
      <body>
        <Theme theme={neutralTheme} mode={mode}>
          <LinkProvider component={RouterLink}>{children}</LinkProvider>
        </Theme>
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  if (import.meta.env.DEV) {
    import("react-grab");
  }

  // Клиент создаётся один раз на монтирование приложения: на сервере рендера
  // общий клиент утёк бы между запросами разных пользователей.
  const [queryClient] = useState(createQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      {/* reducedMotion="user" — все motion-компоненты сами уважают
          prefers-reduced-motion, без ручных проверок в каждом месте. */}
      <MotionConfig reducedMotion="user">
        <Outlet />
      </MotionConfig>
    </QueryClientProvider>
  );
}

export function ErrorBoundary({ error }: Route.ErrorBoundaryProps) {
  if (isRouteErrorResponse(error) && error.status === 404) {
    return <NotFoundPage />;
  }

  let message = "Что-то пошло не так";
  let details = "Непредвиденная ошибка.";
  let stack: string | undefined;

  if (isRouteErrorResponse(error)) {
    message = "Ошибка";
    details = error.statusText || details;
  } else if (import.meta.env.DEV && error && error instanceof Error) {
    details = error.message;
    stack = error.stack;
  }

  return (
    <Center axis="both" padding={6} height="100dvh">
      <VStack gap={4} maxWidth={720} width="100%">
        <EmptyState
          headingLevel={1}
          title={message}
          description={details}
          actions={<Button variant="primary" label="На главную" href="/" />}
        />
        {stack ? (
          <CodeBlock
            code={stack}
            language="plaintext"
            title="stack trace"
            size="sm"
            width="100%"
            maxHeight={320}
          />
        ) : null}
      </VStack>
    </Center>
  );
}
