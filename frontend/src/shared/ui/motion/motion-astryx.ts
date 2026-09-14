import { motion, type Transition } from "motion/react";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Item } from "@astryxdesign/core/Item";
import { ListItem } from "@astryxdesign/core/List";
import { Section } from "@astryxdesign/core/Section";

/**
 * Правило проекта запрещает голые `<div>` — вместо `motion.div` анимируем
 * сами Astryx-компоненты через `motion.create(...)`, они пробрасывают
 * `ref`/`style`, которые нужны motion для анимации.
 */
export const MotionItem = motion.create(Item);
export const MotionListItem = motion.create(ListItem);
export const MotionSection = motion.create(Section);
export const MotionEmptyState = motion.create(EmptyState);

/** Тайминги приведены к токенам Astryx (--duration-fast/--ease-standard). */
export const fastTransition: Transition = {
  duration: 0.175,
  ease: [0.24, 1, 0.4, 1],
};

export const mediumTransition: Transition = {
  duration: 0.41,
  ease: [0.24, 1, 0.4, 1],
};

/** Появление строки списка/элемента очереди. */
export const listItemMotion = {
  layout: true,
  initial: { opacity: 0, y: -8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, height: 0 },
  transition: fastTransition,
} as const;

/** Плавная замена содержимого (skeleton → контент, смена вкладки). */
export const fadeSwapMotion = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: fastTransition,
} as const;

/** Появление экрана-заглушки (404, ошибка) при монтировании. */
export const pageEntryMotion = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: mediumTransition,
} as const;
