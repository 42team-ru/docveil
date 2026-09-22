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
  { value: "ollama", label: "Ollama (локальный сервер)" },
  { value: "fake", label: "Fake (без реальных вызовов, для теста)" },
  { value: "cassette", label: "Cassette (записанные ответы, для теста)" },
];

const DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434";

/** Создать или отредактировать профиль LLM; встроенный можно сохранить как
 * пользовательское переопределение под тем же именем.
 *
 * Токен можно вставить прямо в форму или прочитать из переменной окружения
 * backend. Тариф необязателен — без него
 * стоимость просто не попадёт в отчёт по прогонам на этом профиле.
 */
export function LlmProfileDialog({ isOpen, onOpenChange, editingProfile }: LlmProfileDialogProps) {
  const isEditing = editingProfile !== null;
  const [name, setName] = useState("");
  const [provider, setProvider] = useState<LLMProfileCreateProvider>("openrouter");
  const [model, setModel] = useState("");
  const [apiKeyEnv, setApiKeyEnv] = useState("OPENROUTER_API_KEY");
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState(DEFAULT_OLLAMA_BASE_URL);
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
      const providerConfig = editingProfile.provider_config as { ollama_base_url?: string };
      setOllamaBaseUrl(
        editingProfile.provider === "ollama"
          ? providerConfig.ollama_base_url ?? DEFAULT_OLLAMA_BASE_URL
          : DEFAULT_OLLAMA_BASE_URL,
      );
      setHasPricing(editingProfile.pricing !== null);
      setPromptPer1k(editingProfile.pricing?.prompt_per_1k ?? null);
      setCompletionPer1k(editingProfile.pricing?.completion_per_1k ?? null);
    } else {
      setName("");
      setProvider("openrouter");
      setModel("");
      setApiKeyEnv("OPENROUTER_API_KEY");
      setOllamaBaseUrl(DEFAULT_OLLAMA_BASE_URL);
      setHasPricing(false);
      setPromptPer1k(null);
      setCompletionPer1k(null);
    }
    setApiKey("");
    setClearApiKey(false);
    setErrorMessage(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- editingProfile.id, не сам объект: не пере-заполнять форму на каждый рефетч списка.
  }, [isOpen, editingProfile?.id]);

  const canSubmit =
    name.trim() !== "" &&
    (provider === "ollama"
      ? model.trim() !== "" && ollamaBaseUrl.trim() !== ""
      : apiKeyEnv.trim() !== "") &&
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
          payload: {
            provider,
            model: model.trim(),
            api_key_env: apiKeyEnv.trim(),
            api_key:
              provider === "ollama" ? undefined : clearApiKey ? null : apiKey.trim() || undefined,
            provider_config:
              provider === "ollama"
                ? { ollama_base_url: ollamaBaseUrl.trim() }
                : provider === editingProfile.provider
                  ? editingProfile.provider_config
                  : {},
            pricing,
          },
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
      {
        name: name.trim(),
        provider,
        model: model.trim(),
        api_key_env: apiKeyEnv.trim(),
        api_key: provider === "ollama" ? undefined : apiKey.trim() || undefined,
        provider_config:
          provider === "ollama"
            ? { ollama_base_url: ollamaBaseUrl.trim() }
            : isEditing && provider === editingProfile.provider
              ? editingProfile.provider_config
              : {},
        pricing,
      },
      {
        onSuccess: () => {
          showToast({ body: isEditing ? "Профиль сохранён" : "Профиль создан", type: "info" });
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
                description={
                  provider === "ollama"
                    ? "Имя модели, установленной в Ollama, например qwen3:8b"
                    : "Как в API провайдера, например deepseek/deepseek-chat"
                }
                value={model}
                onChange={setModel}
              />
              {provider === "ollama" ? (
                <TextInput
                  label="Адрес Ollama"
                  description="Для Ollama на этом компьютере оставьте этот адрес. Он доступен backend из Docker."
                  value={ollamaBaseUrl}
                  onChange={setOllamaBaseUrl}
                />
              ) : (
                <>
                  <TextInput
                    label="API-токен"
                    type="password"
                    placeholder={
                      isEditing && editingProfile.has_api_key
                        ? "Токен сохранён — введите новый, чтобы заменить"
                        : "Вставьте токен провайдера"
                    }
                    value={apiKey}
                    onChange={(value) => {
                      setApiKey(value);
                      if (value) setClearApiKey(false);
                    }}
                  />
                  {isEditing && editingProfile.has_api_key ? (
                    <CheckboxInput
                      label="Удалить сохранённый токен"
                      value={clearApiKey}
                      onChange={(value) => {
                        setClearApiKey(value);
                        if (value) setApiKey("");
                      }}
                    />
                  ) : null}
                  <TextInput
                    label="Или переменная окружения backend"
                    description="Используется, если токен выше не указан"
                    value={apiKeyEnv}
                    onChange={setApiKeyEnv}
                  />
                </>
              )}
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
