import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { CircleCheck } from "lucide-react";

import {
  buildAnswerEnvelope,
  isForcedQuestion,
  unansweredQuestions,
} from "../../../entity/pii/model/answers";
import { useReviewStore } from "../../../entity/pii/model/review-store";
import type {
  AnswerOption,
  AskEnvelope,
  PolicyQuestion,
} from "../../../entity/pii/model/types";
import { useSubmitAnswers } from "../../masking-run/api/masking-run";

type ClarificationTabProps = {
  ask: AskEnvelope | null;
  /** Прогон, который стоит на этих вопросах; `null` — отправлять некуда. */
  runId: string | null;
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
 * Ответы уходят на `POST /api/runs/{id}/answers` тем же конвертом, который
 * движок ждёт при возобновлении графа (`Command(resume=...)`): ни одного
 * варианта сверх списка вопроса интерфейс не изобретает.
 */
export function ClarificationTab({ ask, runId }: ClarificationTabProps) {
  const answers = useReviewStore((state) => state.questionAnswers);
  const answerQuestion = useReviewStore((state) => state.answerQuestion);
  const submit = useSubmitAnswers(runId);

  if (!ask || ask.questions.length === 0) {
    return (
      <VStack height="100%" hAlign="center" vAlign="center">
        <EmptyState
          isCompact
          icon={<Icon icon={CircleCheck} size="lg" />}
          title="Вопросов нет"
          description="Движок прошёл документ, не останавливаясь на уточнениях."
        />
      </VStack>
    );
  }

  const answered = ask.questions.filter(
    (question) => answers[question.id] !== undefined,
  ).length;
  const unanswered = unansweredQuestions(ask.questions, answers).length;

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
        <VStack gap={3}>
          <Button
            variant="primary"
            width="100%"
            label="Продолжить обезличивание"
            isDisabled={runId === null || submit.isPending}
            isLoading={submit.isPending}
            onClick={() =>
              submit.mutate(buildAnswerEnvelope(ask.questions, answers))
            }
          />
          {unanswered > 0 ? (
            <Text type="supporting" color="secondary" textWrap="pretty">
              {`Без ответа ${unanswered} — движок решит их сам, по умолчанию «маскировать».`}
            </Text>
          ) : null}
          {submit.isError ? (
            <Banner
              status="error"
              container="section"
              collapsible={false}
              title="Ответы не приняты"
              description="Прогон уже не ждёт ответов — обновите страницу, чтобы увидеть его состояние."
            />
          ) : null}
        </VStack>
      </Section>
    </VStack>
  );
}
