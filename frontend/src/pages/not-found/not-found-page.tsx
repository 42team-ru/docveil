import { Compass } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Center } from "@astryxdesign/core/Center";
import { Icon } from "@astryxdesign/core/Icon";
import { MotionEmptyState, pageEntryMotion } from "../../shared/ui/motion/motion-astryx";

/** Экран 404: адрес не соответствует ни одному роуту приложения. */
export function NotFoundPage() {
  return (
    <Center axis="both" padding={6} height="100dvh">
      <MotionEmptyState
        {...pageEntryMotion}
        headingLevel={1}
        icon={<Icon icon={Compass} size="lg" color="secondary" />}
        title="Страница не найдена"
        description="Такой страницы в панели нет. Возможно, ссылка устарела или адрес введён с ошибкой."
        actions={<Button variant="primary" label="На главную" href="/" />}
      />
    </Center>
  );
}
