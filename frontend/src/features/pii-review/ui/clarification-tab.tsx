import { useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Section } from "@astryxdesign/core/Section";
import { Text } from "@astryxdesign/core/Text";

/**
 * Уточняющие вопросы, которые агент задаёт до нумерации маркеров.
 * Ответы в прототипе только запоминаются на экране.
 */
export function ClarificationTab() {
  const [buyer, setBuyer] = useState("ses");
  const [amounts, setAmounts] = useState<string | null>(null);

  return (
    <VStack gap={4} padding={4}>
      <Banner
        status="warning"
        collapsible={false}
        title="Кто из сторон покупатель?"
        description="В преамбуле роль второй стороны не указана явно. От ответа зависит нумерация маркеров и группировка в отчёте."
      >
        <RadioList
          label="Уточнение 1 из 2"
          isLabelHidden
          value={buyer}
          onChange={setBuyer}
          size="sm"
        >
          <RadioListItem
            value="ses"
            label="АО «Северэнергосбыт»"
            description="упомянуто в п. 1.2 как получатель"
          />
          <RadioListItem value="gsm" label="ООО «ГрандСтройМонтаж»" />
          <RadioListItem
            value="none"
            label="Не определять"
            description="маскировать обе стороны одинаково"
          />
        </RadioList>
      </Banner>

      <Section padding={0}>
        <VStack gap={3}>
          <Text weight="semibold">Суммы в Приложении № 1 маскировать?</Text>
          <Text color="secondary" textWrap="pretty">
            Найдено 46 числовых значений в таблице спецификации. Тип «Суммы и
            цены» включён, но таблица помечена как расчёт объёмов.
          </Text>
          <HStack gap={2} wrap="wrap">
            <Button
              size="sm"
              variant={amounts === "all" ? "primary" : "secondary"}
              label="Да, все 46"
              onClick={() => setAmounts("all")}
            />
            <Button
              size="sm"
              variant={amounts === "totals" ? "primary" : "secondary"}
              label="Только итоги"
              onClick={() => setAmounts("totals")}
            />
            <Button
              size="sm"
              variant={amounts === "skip" ? "primary" : "ghost"}
              label="Пропустить"
              onClick={() => setAmounts("skip")}
            />
          </HStack>
        </VStack>
      </Section>

      <Text type="supporting" textWrap="pretty">
        Ответы сохраняются в профиль правил и не будут запрошены снова для
        похожих документов.
      </Text>
    </VStack>
  );
}
