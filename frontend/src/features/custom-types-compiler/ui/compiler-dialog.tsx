import { useState } from "react";
import { Plus } from "lucide-react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Icon } from "@astryxdesign/core/Icon";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Section } from "@astryxdesign/core/Section";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Token } from "@astryxdesign/core/Token";

import type { CompileQuestionOut, CompileResponse, CompiledTypeOut } from "../api/custom-types";
import { answerCompilerQuestions, compileType } from "../api/custom-types";
import { useCustomTypesStore } from "../model/store";

type Step = "describe" | "questions" | "preview";

type Props = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  /** MinIO object_name. Если null — файл ещё не загружен, кнопка заблокирована. */
  objectName: string | null;
};

/**
 * Трёхшаговый диалог компилятора кастомных типов (И3).
 * Шаг 1: описание → POST /custom_types/compile
 * Шаг 2: вопросы компилятора (если status="waiting") → POST .../answers
 * Шаг 3: превью результата → добавить в прогон
 */
export function CustomTypesCompilerDialog({ isOpen, onOpenChange, objectName }: Props) {
  const addType = useCustomTypesStore((state) => state.addType);

  const [description, setDescription] = useState("");
  const [step, setStep] = useState<Step>("describe");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [threadId, setThreadId] = useState<string | null>(null);
  const [questions, setQuestions] = useState<CompileQuestionOut[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<CompileResponse | null>(null);

  function resetDialog() {
    setDescription("");
    setStep("describe");
    setIsLoading(false);
    setError(null);
    setThreadId(null);
    setQuestions([]);
    setAnswers({});
    setResult(null);
  }

  function handleClose() {
    resetDialog();
    onOpenChange(false);
  }

  async function handleCompile() {
    if (!objectName || !description.trim()) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await compileType(objectName, description.trim());
      applyResponse(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка компиляции");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleAnswers() {
    if (!threadId) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await answerCompilerQuestions(threadId, answers);
      applyResponse(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка отправки ответов");
    } finally {
      setIsLoading(false);
    }
  }

  function applyResponse(response: CompileResponse) {
    setThreadId(response.thread_id);
    if (response.status === "waiting" && response.questions && response.questions.length > 0) {
      setQuestions(response.questions);
      const defaultAnswers: Record<string, string> = {};
      for (const q of response.questions) {
        if (q.options && q.options.length > 0) defaultAnswers[q.id] = q.options[0];
      }
      setAnswers(defaultAnswers);
      setStep("questions");
    } else {
      setResult(response);
      setStep("preview");
    }
  }

  function handleAddToRun(compiled: CompiledTypeOut) {
    addType(compiled);
    handleClose();
  }

  const descriptionTooShort = description.trim().length > 0 && description.trim().length < 8;

  return (
    <Dialog isOpen={isOpen} onOpenChange={handleClose} purpose="form" width={520}>
      <Layout
        header={
          <DialogHeader
            title={
              step === "describe"
                ? "Добавить свой тип данных"
                : step === "questions"
                  ? "Уточните описание"
                  : "Результат компиляции"
            }
            onOpenChange={handleClose}
          />
        }
        content={
          <LayoutContent isScrollable>
            <VStack gap={4}>
              {error && (
                <Banner
                  status="error"
                  title="Ошибка"
                  description={error}
                  collapsible={false}
                />
              )}

              {step === "describe" && (
                <VStack gap={3}>
                  <Text color="secondary">
                    Опишите тип данных так, как бы вы объяснили коллеге: что это такое, как выглядит, где встречается.
                    Компилятор сам определит шаблон поиска.
                  </Text>
                  <TextArea
                    label="Описание типа данных"
                    value={description}
                    onChange={setDescription}
                    placeholder="Например: номер спецификации к договору в формате «Сп-2024/001»"
                    rows={4}
                    maxLength={1000}
                    status={
                      descriptionTooShort
                        ? { type: "error", message: "Минимум 8 символов" }
                        : undefined
                    }
                  />
                  {objectName === null && (
                    <Banner
                      status="info"
                      title="Нет загруженного файла"
                      description="Добавьте файл в очередь — компилятор ищет примеры в документе."
                      collapsible={false}
                    />
                  )}
                </VStack>
              )}

              {step === "questions" && (
                <VStack gap={4}>
                  <Text color="secondary">
                    Компилятор задаёт уточняющие вопросы, чтобы точнее настроить детектор.
                  </Text>
                  {questions.map((question) => (
                    <QuestionField
                      key={question.id}
                      question={question}
                      value={answers[question.id] ?? ""}
                      onChange={(value) => setAnswers((prev) => ({ ...prev, [question.id]: value }))}
                    />
                  ))}
                </VStack>
              )}

              {step === "preview" && result && (
                <PreviewStep result={result} onAdd={handleAddToRun} />
              )}
            </VStack>
          </LayoutContent>
        }
        footer={
          step !== "preview" ? (
            <LayoutFooter hasDivider>
              <HStack gap={2} hAlign="end">
                <Button label="Отмена" variant="ghost" onClick={handleClose} isDisabled={isLoading} />
                {step === "describe" && (
                  <Button
                    label="Скомпилировать"
                    variant="primary"
                    isDisabled={!objectName || !description.trim() || descriptionTooShort}
                    isLoading={isLoading}
                    onClick={() => void handleCompile()}
                  />
                )}
                {step === "questions" && (
                  <Button
                    label="Отправить ответы"
                    variant="primary"
                    isDisabled={questions.some((q) => !answers[q.id])}
                    isLoading={isLoading}
                    onClick={() => void handleAnswers()}
                  />
                )}
              </HStack>
            </LayoutFooter>
          ) : undefined
        }
      />
    </Dialog>
  );
}

function QuestionField({
  question,
  value,
  onChange,
}: {
  question: CompileQuestionOut;
  value: string;
  onChange: (value: string) => void;
}) {
  if (question.options && question.options.length > 0) {
    return (
      <RadioList label={question.text} value={value} onChange={onChange}>
        {question.options.map((opt) => (
          <RadioListItem key={opt} value={opt} label={opt} />
        ))}
      </RadioList>
    );
  }
  return (
    <TextArea
      label={question.text}
      value={value}
      onChange={onChange}
      rows={2}
    />
  );
}

function PreviewStep({
  result,
  onAdd,
}: {
  result: CompileResponse;
  onAdd: (compiled: CompiledTypeOut) => void;
}) {
  const compiledList = result.compiled ?? [];
  const failedList = result.failed ?? [];

  return (
    <VStack gap={4}>
      {failedList.length > 0 && (
        <Banner
          status="warning"
          title={`${failedList.length} тип не удалось скомпилировать`}
          description={failedList.map((f) => f.reason).join("; ")}
          collapsible={false}
        />
      )}

      {compiledList.length === 0 && (
        <Text color="secondary">Компилятор не смог собрать тип по этому описанию.</Text>
      )}

      {compiledList.map((compiled, index) => (
        <CompiledTypeCard key={index} compiled={compiled} onAdd={() => onAdd(compiled)} />
      ))}
    </VStack>
  );
}

function CompiledTypeCard({
  compiled,
  onAdd,
}: {
  compiled: CompiledTypeOut;
  onAdd: () => void;
}) {
  const previewCount = compiled.preview?.total_matches ?? 0;
  const isBuiltin = compiled.outcome === "use_builtin";

  return (
    <Section padding={3}>
      <VStack gap={3}>
        <HStack gap={2} vAlign="center">
          <HStack gap={2} vAlign="center">
            <Heading level={6}>
              {isBuiltin
                ? `Встроенный тип: ${compiled.type_id ?? "—"}`
                : (compiled.spec?.title ?? "Новый тип")}
            </Heading>
            {isBuiltin && <Token label="встроенный" />}
          </HStack>
        </HStack>

        {previewCount > 0 ? (
          <Text type="supporting" color="secondary">
            {`Найдено совпадений в документе: ${previewCount}`}
          </Text>
        ) : compiled.preview !== undefined && compiled.preview !== null ? (
          <Text type="supporting" color="secondary">
            В документе совпадений не найдено — тип всё равно будет активен при обезличивании.
          </Text>
        ) : null}

        <Button
          label="Добавить в прогон"
          variant="primary"
          icon={<Icon icon={Plus} size="sm" />}
          onClick={onAdd}
        />
      </VStack>
    </Section>
  );
}
