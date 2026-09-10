import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Spinner } from "@astryxdesign/core/Spinner";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { buildAnswerEnvelope } from "../../../entity/pii/model/answers";
import { useReviewStore } from "../../../entity/pii/model/review-store";
import { typeSelectionAnswer, withTypeSelectionDefaults } from "../../../entity/pii/model/type-selection";
import { MASK_OPTION, type AskEnvelope } from "../../../entity/pii/model/types";
import { useSubmitAnswers } from "../../masking-run/api/masking-run";

type Props = {
  runId: string;
  ask: AskEnvelope | null;
  isSelecting: boolean;
  isProcessing: boolean;
  error: string | null;
  onSelected: () => void;
  onLeave: () => void;
};

/** Выбор типов и ожидание обработки поверх рабочего стола документа. */
export function MaskingSetupDialog({ runId, ask, isSelecting, isProcessing, error, onSelected, onLeave }: Props) {
  const answers = useReviewStore((state) => state.questionAnswers);
  const answerQuestion = useReviewStore((state) => state.answerQuestion);
  const submit = useSubmitAnswers(runId);
  const types = ask?.questions.filter((question) => question.kind === "type") ?? [];
  const hasClarifications = ask?.questions.some((question) => question.kind !== "type") ?? false;

  function handleContinue() {
    if (!ask || submit.isPending) return;
    const selected = withTypeSelectionDefaults(ask.questions, answers);
    for (const question of types) answerQuestion(question.id, selected[question.id]);
    if (hasClarifications) onSelected();
    else submit.mutate(buildAnswerEnvelope(ask.questions, selected, ask.schemaVersion));
  }

  return (
    <Dialog isOpen={isSelecting || isProcessing || error !== null} purpose="required" width={560} onOpenChange={() => {}}>
      <Layout
        header={<DialogHeader title={error ? "Не удалось обработать документ" : isSelecting ? "Что обезличить?" : "Обезличиваем документ"}
          subtitle={isSelecting ? "Отметьте типы данных, которые нужно заменить в документе." : undefined} />}
        content={
          <LayoutContent isScrollable>
            <VStack gap={4}>
              {error ? <Text>{error}</Text> : isSelecting ? types.map((question) => (
                <CheckboxInput key={question.id} label={`${question.title} · ${question.found}`}
                  description={question.options.length === 1 ? "Обязательное маскирование" : question.samples.slice(0, 2).join(", ") || undefined}
                  value={(answers[question.id] ?? question.default) === MASK_OPTION}
                  isDisabled={question.options.length === 1 || submit.isPending}
                  onChange={(checked) => answerQuestion(question.id, typeSelectionAnswer(question, checked))} />
              )) : <Spinner size="xl" label="Обработка документа…" />}
              {!error && !isSelecting ? <Text color="secondary">Это может занять несколько минут. Результат появится здесь автоматически.</Text> : null}
              {submit.isError ? <Text>Не удалось отправить выбор. Попробуйте ещё раз.</Text> : null}
            </VStack>
          </LayoutContent>
        }
        footer={
          <LayoutFooter hasDivider>
            <HStack gap={2} hAlign="end" wrap="wrap">
              <Button label="К документам" variant="ghost" onClick={onLeave} />
              {isSelecting && !error ? <Button label={hasClarifications ? "Продолжить к уточнениям" : "Обезличить выбранное"}
                variant="primary" isLoading={submit.isPending} onClick={handleContinue} /> : null}
            </HStack>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
