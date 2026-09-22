import { useEffect, useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useToast } from "@astryxdesign/core/Toast";

import type {
  LLMProfileCreateProvider,
  LLMProfileOut,
} from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { useCreateLlmProfile, useUpdateLlmProfile } from "../api/admin";

type LlmProfileDialogProps = {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  /** `null` — создание нового профиля; профиль — правка существующего
   * (имя тогда неизменно, см. `LLMProfileUpdate` на бэкенде). */
  editingProfile: LLMProfileOut | null;
};

const PROVIDER_OPTIONS: { value: LLMProfileCreateProvider; label: string }[] = [
  { value: "openrouter", label: "OpenRouter" },
  { value: "gigachat", label: "GigaChat" },
  { value: "fake", label: "Fake (без реальных вызовов, для теста)" },
  { value: "cassette", label: "Cassette (записанные ответы, для теста)" },
];

/** Создать или отредактировать свой профиль LLM (встроенные из
 * `masker.yaml` — не через этот диалог, они только для просмотра).
 *
 * `api_key_env` — имя переменной окружения с ключом, не сам ключ: тот же
 * принцип, что и в `masker.yaml` (секреты живут в окружении процесса,
 * профиль только называет, где их искать). Тариф необязателен — без него
 * стоимость просто не попадёт в отчёт по прогонам на этом профиле.
 */
export function LlmProfileDialog({ isOpen, onOpenChange, editingProfile }: LlmProfileDialogProps) {
  const isEditing = editingProfile !== null;
  const [name, setName] = useState("");
  const [provider, setProvider] = useState<LLMProfileCreateProvider>("openrouter");
  const [model, setModel] = useState("");
  const [apiKeyEnv, setApiKeyEnv] = useState("OPENROUTER_API_KEY");
  const [hasPricing, setHasPricing] = useState(false);
  const [promptPer1k, setPromptPer1k] = useState<number | null>(null);
  const [completionPer1k, setCompletionPer1k] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const createProfile = useCreateLlmProfile();
  const updateProfile = useUpdateLlmProfile();
  const showToast = useToast();
  const isPending = createProfile.isPending || updateProfile.isPending;

  // Форма заполняется из редактируемого профиля при каждом открытии диалога
  // на новом профиле — не при каждом рендере, иначе не даст стереть поле.
  useEffect(() => {
    if (!isOpen) return;
    if (editingProfile) {
      setName(editingProfile.name);
      setProvider(editingProfile.provider as LLMProfileCreateProvider);
      setModel(editingProfile.model);
      setApiKeyEnv(editingProfile.api_key_env);
      setHasPricing(editingProfile.pricing !== null);
      setPromptPer1k(editingProfile.pricing?.prompt_per_1k ?? null);
      setCompletionPer1k(editingProfile.pricing?.completion_per_1k ?? null);
    } else {
      setName("");
      setProvider("openrouter");
      setModel("");
      setApiKeyEnv("OPENROUTER_API_KEY");
      setHasPricing(false);
      setPromptPer1k(null);
      setCompletionPer1k(null);
    }
    setErrorMessage(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- editingProfile.id, не сам объект: не пере-заполнять форму на каждый рефетч списка.
  }, [isOpen, editingProfile?.id]);

  const canSubmit =
    name.trim() !== "" &&
    apiKeyEnv.trim() !== "" &&
    (!hasPricing || (promptPer1k !== null && completionPer1k !== null));

  function handleClose() {
    setErrorMessage(null);
    onOpenChange(false);
  }

  function handleSubmit() {
    setErrorMessage(null);
    const pricing =
      hasPricing && promptPer1k !== null && completionPer1k !== null
        ? { prompt_per_1k: promptPer1k, completion_per_1k: completionPer1k, currency: "RUB" }
        : undefined;

    const onError = (error: unknown) => {
      const status = (error as { status?: number }).status;
      setErrorMessage(
        status === 409 ? "Профиль с таким именем уже существует" : "Не удалось сохранить профиль",
      );
    };

    if (isEditing && editingProfile.id) {
      updateProfile.mutate(
        {
          profileId: editingProfile.id,
          payload: { provider, model: model.trim(), api_key_env: apiKeyEnv.trim(), pricing },
        },
        {
          onSuccess: () => {
            showToast({ body: "Профиль сохранён", type: "info" });
            handleClose();
          },
          onError,
        },
      );
      return;
    }

    createProfile.mutate(
      { name: name.trim(), provider, model: model.trim(), api_key_env: apiKeyEnv.trim(), pricing },
      {
        onSuccess: () => {
          showToast({ body: "Профиль создан", type: "info" });
          handleClose();
        },
        onError,
      },
    );
  }

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={(open) => (open ? onOpenChange(true) : handleClose())}
      purpose="form"
      width={480}
    >
      <Layout
        header={
          <DialogHeader
            title={isEditing ? `Профиль «${editingProfile.name}»` : "Новый профиль LLM"}
            onOpenChange={handleClose}
          />
        }
        content={
          <LayoutContent>
            <VStack gap={4}>
              {errorMessage ? (
                <Banner
                  status="error"
                  collapsible={false}
                  title="Не удалось сохранить профиль"
                  description={errorMessage}
                />
              ) : null}
              <TextInput
                label="Название"
                description={
                  isEditing
                    ? "Не меняется после создания — на это имя ссылается активный профиль"
                    : "Только для этого списка — не влияет на сам вызов модели"
                }
                value={name}
                onChange={setName}
                isDisabled={isEditing}
              />
              <Selector
                label="Провайдер"
                options={PROVIDER_OPTIONS}
                value={provider}
                onChange={(value) => setProvider(value as LLMProfileCreateProvider)}
              />
              <TextInput
                label="Модель"
                description="Как в API провайдера, например deepseek/deepseek-chat"
                value={model}
                onChange={setModel}
              />
              <TextInput
                label="Переменная окружения с ключом"
                description="Имя переменной, не сам ключ — сам ключ должен уже быть в окружении сервера"
                value={apiKeyEnv}
                onChange={setApiKeyEnv}
              />
              <VStack gap={2}>
                <CheckboxInput
                  label="Указать тариф (для отчёта по стоимости прогонов)"
                  value={hasPricing}
                  onChange={setHasPricing}
                />
                {hasPricing ? (
                  <HStack gap={2}>
                    <NumberInput
                      label="₽ за 1К токенов ввода"
                      value={promptPer1k ?? undefined}
                      onChange={setPromptPer1k}
                      min={0}
                    />
                    <NumberInput
                      label="₽ за 1К токенов вывода"
                      value={completionPer1k ?? undefined}
                      onChange={setCompletionPer1k}
                      min={0}
                    />
                  </HStack>
                ) : null}
              </VStack>
              {!isEditing ? (
                <Text type="supporting" size="sm" color="secondary">
                  Профиль появится в списке, но не станет активным сам —
                  нажмите «Активировать» на нужной строке после создания.
                </Text>
              ) : null}
            </VStack>
          </LayoutContent>
        }
        footer={
          <LayoutFooter hasDivider>
            <Button label="Отмена" variant="ghost" size="sm" onClick={handleClose} />
            <Button
              label={isEditing ? "Сохранить" : "Создать"}
              variant="primary"
              size="sm"
              isDisabled={!canSubmit}
              isLoading={isPending}
              onClick={handleSubmit}
            />
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
