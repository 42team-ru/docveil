import { Compass } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Center } from "@astryxdesign/core/Center";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";

/** Экран 404: адрес не соответствует ни одному роуту приложения. */
export function NotFoundPage() {
  return (
    <Center axis="both" padding={6} height="100dvh">
      <EmptyState
        headingLevel={1}
        icon={<Icon icon={Compass} size="lg" color="secondary" />}
        title="Страница не найдена"
        description="Такой страницы в панели нет. Возможно, ссылка устарела или адрес введён с ошибкой."
        actions={<Button variant="primary" label="На главную" href="/" />}
      />
    </Center>
  );
}
