import { Divider } from "@astryxdesign/core/Divider";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { FileText } from "lucide-react";

import type {
  ContractParty,
  ContractSummary,
} from "../../../entity/pii/model/types";

type ContractSummaryTabProps = {
  summary: ContractSummary | null;
};

/**
 * Одна строка «подпись — значение». Пустое значение показываем прочерком, а не
 * прячем строку: оператору важно видеть, что поле в договоре не нашлось, —
 * пропавшая строка читается как «здесь нечего искать».
 */
function SummaryRow({ label, value }: { label: string; value: string | null }) {
  return (
    <HStack gap={3} vAlign="start" width="100%">
      <Text type="supporting" color="secondary" size="sm">
        {label}
      </Text>
      <StackItem size="fill" />
      <Text type="body" textWrap="pretty">
        {value && value.length > 0 ? value : "—"}
      </Text>
    </HStack>
  );
}

function PartyBlock({
  party,
  fallbackRole,
}: {
  party: ContractParty | null;
  fallbackRole: string;
}) {
  if (!party) {
    return (
      <VStack gap={2}>
        <Token size="sm" color="default" label={fallbackRole} />
        <Text type="supporting" color="secondary">
          Сторона не определена.
        </Text>
      </VStack>
    );
  }

  return (
    <VStack gap={2}>
      <Token size="sm" color="blue" label={party.roleTitle ?? fallbackRole} />
      <VStack gap={1}>
        <SummaryRow label="Наименование" value={party.name} />
        <SummaryRow label="ИНН" value={party.inn} />
        <SummaryRow label="ОГРН" value={party.ogrn} />
      </VStack>
    </VStack>
  );
}

/**
 * Карточка договора — краткое содержание, собранное движком из уже найденных
 * сущностей и профилей сторон (`report.contract_summary`).
 *
 * Показываем и `paymentTerms`: HTML-отчёт бэкенда это поле опускает, хотя в
 * данных оно есть, и оператору условия оплаты нужны наравне со сроками.
 */
export function ContractSummaryTab({ summary }: ContractSummaryTabProps) {
  if (!summary) {
    return (
      <VStack height="100%" hAlign="center" vAlign="center">
        <EmptyState
          isCompact
          icon={<Icon icon={FileText} size="lg" />}
          title="Карточки договора нет"
          description="Движок не вернул краткое содержание для этого документа."
        />
      </VStack>
    );
  }

  return (
    <VStack gap={0} isScrollable height="100%">
      <Section padding={4}>
        <VStack gap={4}>
          <PartyBlock party={summary.customer} fallbackRole="Заказчик" />
          <Divider />
          <PartyBlock party={summary.supplier} fallbackRole="Поставщик" />
        </VStack>
      </Section>

      <Section padding={4} dividers={["top"]}>
        <VStack gap={3}>
          <Heading level={6}>Условия</Heading>
          <VStack gap={1}>
            <SummaryRow label="Номер договора" value={summary.contractNumber} />
            <SummaryRow label="Сумма договора" value={summary.contractAmount} />
            <SummaryRow
              label="Федеральный закон"
              value={summary.federalLaw.join(", ")}
            />
            <SummaryRow
              label="Сроки поставки"
              value={summary.deliveryPeriods.join("; ")}
            />
            <SummaryRow label="Условия оплаты" value={summary.paymentTerms} />
          </VStack>
        </VStack>
      </Section>

      <Section padding={4} dividers={["top"]}>
        <Text type="supporting" color="secondary" size="sm">
          {summary.llmCalls === 0
            ? "Карточка собрана без обращения к языковой модели — только из найденных сущностей."
            : `Обращений к языковой модели: ${summary.llmCalls}.`}
        </Text>
      </Section>
    </VStack>
  );
}
