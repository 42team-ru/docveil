import { useEffect, useRef } from "react";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Banner } from "@astryxdesign/core/Banner";
import { Step, Stepper } from "@astryxdesign/core/Stepper";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { buildAnswerEnvelope } from "../../../entity/pii/model/answers";
import { useReviewStore } from "../../../entity/pii/model/review-store";
import { withTypeSelectionDefaults } from "../../../entity/pii/model/type-selection";
import type { AskEnvelope } from "../../../entity/pii/model/types";
import { useSubmitAnswers } from "../../masking-run/api/masking-run";
import type { RunProgress } from "../../masking-run/api/masking-run";

type Props = {
  runId: string;
  ask: AskEnvelope | null;
  isSelecting: boolean;
  isProcessing: boolean;
  error: string | null;
  progress?: RunProgress[];
  isProgressUnavailable?: boolean;
  onSelected: () => void;
  onLeave: () => void;
};

/** Шаги конвейера в порядке выполнения. */
const PIPELINE_STEPS: Array<{ id: string; label: string }> = [
  { id: "extract", label: "Извлечение текста" },
  { id: "detect", label: "Детекция данных" },
  { id: "profile", label: "Профилирование сторон" },
  { id: "judge", label: "Оценка уверенности" },
  { id: "plan", label: "Формирование плана" },
  { id: "render", label: "Применение масок" },
  { id: "report", label: "Сборка отчёта" },
];

/** Имя узла графа → индекс шага конвейера. */
function nodeToStepIndex(node: string): number {
  const normalized = node.replace(/_node$/, "").replace("ask_human", "judge");
  const index = PIPELINE_STEPS.findIndex((s) => normalized.startsWith(s.id));
  return index === -1 ? 0 : index;
}

/**
 * Ожидание обработки поверх рабочего стола документа.
 *
 * Типовые вопросы не повторяют выбор пользователя: они подтверждаются
 * безопасным значением по умолчанию, а оператор видит только неоднозначные
 * сущности и профили.
 */
export function MaskingSetupDialog({ runId, ask, isSelecting, isProcessing, error, progress = [], isProgressUnavailable = false, onSelected, onLeave }: Props) {
  const answers = useReviewStore((state) => state.questionAnswers);
  const answerQuestion = useReviewStore((state) => state.answerQuestion);
  const submit = useSubmitAnswers(runId);
  const types = ask?.questions.filter((question) => question.kind === "type") ?? [];
  const hasClarifications = ask?.questions.some((question) => question.kind !== "type") ?? false;
  const handledEnvelope = useRef<string | null>(null);

  useEffect(() => {
    if (!isSelecting || !ask || submit.isPending) return;
    const envelopeKey = `${ask.threadId}:${ask.schemaVersion}`;
    if (handledEnvelope.current === envelopeKey) return;
    handledEnvelope.current = envelopeKey;
    const selected = withTypeSelectionDefaults(ask.questions, answers);
    for (const question of types) answerQuestion(question.id, selected[question.id]);
    if (hasClarifications) {
      onSelected();
      return;
    }
    submit.mutate(buildAnswerEnvelope(ask.questions, selected, ask.schemaVersion));
  }, [answerQuestion, answers, ask, hasClarifications, isSelecting, onSelected, submit, types]);

  const lastEvent = progress[progress.length - 1];
  const activeStep = lastEvent ? nodeToStepIndex(lastEvent.node) : 0;
  const lastMessage = lastEvent
    ? (typeof lastEvent.content.message === "string" ? lastEvent.content.message : null)
    : null;

  return (
    <Dialog isOpen={isSelecting || isProcessing || error !== null} purpose="required" width={560} onOpenChange={() => {}}>
      <Layout
        header={<DialogHeader title={error ? "Не удалось обработать документ" : "Обезличиваем документ"} />}
        content={
          <LayoutContent isScrollable>
            <VStack gap={5}>
              {error ? (
                <Banner status="error" title="Прогон завершился с ошибкой" description={error} collapsible={false} />
              ) : (
                <>
                  <HStack gap={3} vAlign="center">
                    <Spinner size="md" label="Обработка документа…" />
                    <Text color="secondary" size="sm">
                      {lastMessage ?? "Начинаю разбор документа…"}
                    </Text>
                  </HStack>

                  <Stepper
                    activeStep={activeStep}
                    orientation="vertical"
                    density="compact"
                    label="Ход обработки документа"
                  >
                    {PIPELINE_STEPS.map((step, index) => (
                      <Step
                        key={step.id}
                        step={index}
                        label={step.label}
                        status={index === activeStep ? "accent" : undefined}
                        indicator={index === activeStep ? <Spinner size="sm" label="" /> : "auto"}
                      />
                    ))}
                  </Stepper>

                  {isProgressUnavailable ? (
                    <Text type="supporting" color="secondary">
                      Лента разбора временно недоступна; ожидаем результат прогона.
                    </Text>
                  ) : null}
                </>
              )}
              {!error ? (
                <Text type="supporting" color="secondary">
                  Это может занять несколько минут. Результат появится здесь автоматически.
                </Text>
              ) : null}
              {submit.isError ? <Text>Не удалось отправить выбор. Попробуйте ещё раз.</Text> : null}
            </VStack>
          </LayoutContent>
        }
        footer={
          <LayoutFooter hasDivider>
            <HStack gap={2} hAlign="end" wrap="wrap">
              <Button label="К документам" variant="ghost" onClick={onLeave} />
            </HStack>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
