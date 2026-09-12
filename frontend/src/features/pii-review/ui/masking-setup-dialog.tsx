import { useEffect, useRef } from "react";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Banner } from "@astryxdesign/core/Banner";
import { List, ListItem } from "@astryxdesign/core/List";
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

  return (
    <Dialog isOpen={isSelecting || isProcessing || error !== null} purpose="required" width={560} onOpenChange={() => {}}>
      <Layout
        header={<DialogHeader title={error ? "Не удалось обработать документ" : "Обезличиваем документ"} />}
        content={
          <LayoutContent isScrollable>
            <VStack gap={4}>
              {error ? <Banner status="error" title="Прогон завершился с ошибкой" description={error} collapsible={false} /> : <>
                <Spinner size="xl" label="Обработка документа…" />
                {progress.length > 0 ? <List density="compact" hasDividers header={<Text weight="semibold">Ход разбора</Text>}>
                  {progress.map((event) => <ListItem key={event.sequence} label={progressMessage(event)} />)}
                </List> : <Text color="secondary">Начинаю разбор документа…</Text>}
                {isProgressUnavailable ? <Text type="supporting" color="secondary">Лента разбора временно недоступна; ожидаем результат прогона.</Text> : null}
              </>}
              {!error ? <Text color="secondary">Это может занять несколько минут. Результат появится здесь автоматически.</Text> : null}
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

function progressMessage(event: RunProgress): string {
  const message = event.content.message;
  return typeof message === "string" ? message : `Выполняю этап «${event.node}».`;
}
