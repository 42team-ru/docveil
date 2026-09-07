import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

import { isForcedQuestion } from "../../../entity/pii/model/answers";
import { useReviewStore } from "../../../entity/pii/model/review-store";
import type {
  AnswerOption,
  AskEnvelope,
  PolicyQuestion,
} from "../../../entity/pii/model/types";

type ClarificationTabProps = {
  ask: AskEnvelope | null;
};

const KIND_LABEL: Record<PolicyQuestion["kind"], string> = {
  type: "тип",
  profile: "сторона",
  entity: "сущность",
};

/** Один вопрос движка с вариантами ровно из его же списка. */
function QuestionItem({
  question,
  answer,
  onAnswer,
}: {
  question: PolicyQuestion;
  answer: AnswerOption | undefined;
  onAnswer: (value: AnswerOption) => void;
}) {
  const forced = isForcedQuestion(question);

  return (
    <Section padding={4} dividers={["top"]}>
      <VStack gap={3}>
        <HStack gap={2} vAlign="center" wrap="wrap">
          <Token size="sm" color="default" label={KIND_LABEL[question.kind]} />
          <Text weight="semibold" textWrap="pretty">
            {question.title}
          </Text>
          <StackItem size="fill" />
          <Badge variant="neutral" label={question.found} />
        </HStack>

        <Text color="secondary" textWrap="pretty">
          {question.prompt}
        </Text>

        {question.samples.length > 0 ? (
          <Text type="supporting" color="secondary" size="sm" textWrap="pretty">
            {`Например: ${question.samples.slice(0, 3).join(", ")}`}
          </Text>
        ) : null}

        {question.anchors.length > 0 ? (
          <Text type="supporting" color="secondary" size="sm" textWrap="pretty">
            {`Где: ${question.anchors.join(", ")}`}
          </Text>
        ) : null}

        {forced ? (
          // Единственный вариант — это не оплошность интерфейса, а защита
          // критичного типа: снятие маски требует и флага прогона
          // (--unmask-critical), и отдельного осознанного ответа.
          <Banner
            status="info"
            container="section"
            collapsible={false}
            title="Снять маску нельзя"
            description="Критичный тип. Движок предлагает единственный вариант — маскировать; снятие требует прогона с явным разрешением."
          />
        ) : (
          <RadioList
            label={question.prompt}
            isLabelHidden
            size="sm"
            value={answer ?? ""}
            onChange={(value) => onAnswer(value as AnswerOption)}
          >
            {question.options.map((option) => (
              <RadioListItem key={option} value={option} label={option} />
            ))}
          </RadioList>
        )}
      </VStack>
    </Section>
  );
}

/**
 * Вопросы, которыми движок остановил прогон (`questions.json`, узел
 * `ask_human`). Варианты ответа берутся из самого вопроса: набор задаёт
 * движок, и любая другая строка на его стороне молча превратится в
 * «маскировать».
 *
 * Ответы живут в сторе проверки и никуда не уходят: эндпоинта возобновления
 * прогона на бэкенде пока нет. Обещать оператору обратное — хуже, чем
 * сказать прямо.
 */
export function ClarificationTab({ ask }: ClarificationTabProps) {
  const answers = useReviewStore((state) => state.questionAnswers);
  const answerQuestion = useReviewStore((state) => state.answerQuestion);

  if (!ask || ask.questions.length === 0) {
    return (
      <EmptyState
        isCompact
        title="Вопросов нет"
        description="Движок прошёл документ, не останавливаясь на уточнениях."
      />
    );
  }

  const answered = ask.questions.filter(
    (question) => answers[question.id] !== undefined,
  ).length;

  return (
    <VStack gap={0} isScrollable height="100%">
      <Section padding={4}>
        <VStack gap={2}>
          <Text type="supporting" weight="medium">
            {`Отвечено ${answered} из ${ask.questions.length}`}
          </Text>
          <Text type="supporting" color="secondary" textWrap="pretty">
            Неотвеченный вопрос движок решает сам — по умолчанию «маскировать».
          </Text>
        </VStack>
      </Section>

      {ask.questions.map((question) => (
        <QuestionItem
          key={question.id}
          question={question}
          answer={answers[question.id]}
          onAnswer={(value) => answerQuestion(question.id, value)}
        />
      ))}

      <Section padding={4} dividers={["top"]}>
        <Text type="supporting" color="secondary" textWrap="pretty">
          Ответы остаются на этом экране: отправлять их пока некуда — движок
          принимает возобновление прогона только из командной строки.
        </Text>
      </Section>
    </VStack>
  );
}
