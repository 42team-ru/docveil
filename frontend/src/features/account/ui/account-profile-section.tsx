import { useState } from "react";
import { Check, Eye, EyeOff, Pencil, X } from "lucide-react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Divider } from "@astryxdesign/core/Divider";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { Selector } from "@astryxdesign/core/Selector";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useToast } from "@astryxdesign/core/Toast";

import { formatMoment } from "../../../shared/lib/format-moment";
import type { ErrorType } from "../../../shared/api/mutators/authMutator";
import { evaluatePasswordStrength } from "../lib/password-strength";
import {
  useAccount,
  useChangePassword,
  useUpdateFullName,
  useUpdateTimezone,
} from "../api/use-account";
import { AccountIdentity } from "./account-identity";

const TIMEZONE_OPTIONS = [
  { value: "Europe/Kaliningrad", label: "Калининград (UTC+2)" },
  { value: "Europe/Moscow", label: "Москва (UTC+3)" },
  { value: "Asia/Yekaterinburg", label: "Екатеринбург (UTC+5)" },
  { value: "Asia/Novosibirsk", label: "Новосибирск (UTC+7)" },
  { value: "Asia/Vladivostok", label: "Владивосток (UTC+10)" },
];

/** Раздел «Профиль»: реальные данные `GET /auth/me` вместо заглушки
 * («Пользователь» / «вход не выполнен» в старом `ProfilePopover`), плюс
 * самообслуживаемые действия — аватар, имя, часовой пояс, смена пароля. */
export function AccountProfileSection() {
  const { data: user, isLoading } = useAccount();
  const updateFullName = useUpdateFullName();
  const updateTimezone = useUpdateTimezone();
  const changePassword = useChangePassword();
  const showToast = useToast();

  const [nameDraft, setNameDraft] = useState<string | null>(null);
  const [isEditingName, setIsEditingName] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);

  if (isLoading || !user) {
    return (
      <VStack gap={4}>
        <Skeleton height={64} width={200} />
        <Skeleton height={120} width="100%" />
      </VStack>
    );
  }

  const name = isEditingName ? (nameDraft ?? user.full_name) : user.full_name;
  const isNameDirty = isEditingName && name.trim() !== "" && name !== user.full_name;
  const passwordError = changePassword.error as ErrorType | undefined;
  const strength = evaluatePasswordStrength(newPassword);

  return (
    <VStack gap={5}>
      <AccountIdentity user={user} />

      <MetadataList columns={2}>
        <MetadataListItem label="Зарегистрирован">
          {formatMoment(user.created_at)}
        </MetadataListItem>
        <MetadataListItem label="Последний вход">
          {formatMoment(user.last_login_at)}
        </MetadataListItem>
      </MetadataList>

      <Divider />

      <HStack gap={8} align="start">
        <StackItem size="fill">
          <VStack gap={4}>
            <HStack gap={2} vAlign="end">
              <StackItem size="fill">
                <TextInput
                  label="Имя"
                  value={name}
                  isDisabled={!isEditingName}
                  hasAutoFocus={isEditingName}
                  onChange={setNameDraft}
                />
              </StackItem>
              {isEditingName ? (
                <>
                  <IconButton
                    size="md"
                    variant="ghost"
                    label="Отменить редактирование имени"
                    icon={<Icon icon={X} size="sm" />}
                    onClick={() => {
                      setNameDraft(null);
                      setIsEditingName(false);
                    }}
                  />
                  <IconButton
                    size="md"
                    variant="primary"
                    label="Сохранить имя"
                    icon={<Icon icon={Check} size="sm" />}
                    isDisabled={!isNameDirty}
                    isLoading={updateFullName.isPending}
                    onClick={() => {
                      updateFullName.mutate(name, {
                        onSuccess: () => {
                          setNameDraft(null);
                          setIsEditingName(false);
                          showToast({ body: "Имя сохранено", type: "info" });
                        },
                      });
                    }}
                  />
                </>
              ) : (
                <IconButton
                  size="md"
                  variant="ghost"
                  label="Редактировать имя"
                  icon={<Icon icon={Pencil} size="sm" />}
                  onClick={() => {
                    setNameDraft(user.full_name);
                    setIsEditingName(true);
                  }}
                />
              )}
            </HStack>
            <Selector
              label="Часовой пояс"
              options={TIMEZONE_OPTIONS}
              value={user.timezone ?? undefined}
              placeholder="Не выбран"
              isLoading={updateTimezone.isPending}
              onChange={(value) => updateTimezone.mutate(value)}
            />
          </VStack>
        </StackItem>

        <Divider orientation="vertical" />

        <StackItem size="fill">
          <VStack gap={4}>
            {passwordError ? (
              <Banner
                status="error"
                container="card"
                collapsible={false}
                title={passwordError.detail ?? "Не удалось сменить пароль"}
              />
            ) : null}

            <HStack gap={2} vAlign="end">
              <StackItem size="fill">
                <TextInput
                  label="Текущий пароль"
                  type={showCurrentPassword ? "text" : "password"}
                  value={currentPassword}
                  onChange={setCurrentPassword}
                />
              </StackItem>
              <IconButton
                size="md"
                variant="ghost"
                label={showCurrentPassword ? "Скрыть пароль" : "Показать пароль"}
                icon={<Icon icon={showCurrentPassword ? EyeOff : Eye} size="sm" />}
                onClick={() => setShowCurrentPassword((v) => !v)}
              />
            </HStack>

            <HStack gap={2} vAlign="end">
              <StackItem size="fill">
                <TextInput
                  label="Новый пароль"
                  type={showNewPassword ? "text" : "password"}
                  value={newPassword}
                  onChange={setNewPassword}
                />
              </StackItem>
              <IconButton
                size="md"
                variant="ghost"
                label={showNewPassword ? "Скрыть пароль" : "Показать пароль"}
                icon={<Icon icon={showNewPassword ? EyeOff : Eye} size="sm" />}
                onClick={() => setShowNewPassword((v) => !v)}
              />
            </HStack>

            {newPassword ? (
              <VStack gap={1}>
                <ProgressBar
                  label="Надёжность пароля"
                  isLabelHidden
                  value={strength.score}
                  max={strength.max}
                  variant={strength.variant}
                />
                <Text type="supporting" size="sm" color="secondary">
                  {strength.label}
                </Text>
              </VStack>
            ) : null}

            <HStack hAlign="end">
              <Button
                label="Сменить пароль"
                size="sm"
                variant="secondary"
                isDisabled={currentPassword === "" || newPassword === ""}
                isLoading={changePassword.isPending}
                onClick={() => {
                  changePassword.mutate(
                    { current_password: currentPassword, new_password: newPassword },
                    {
                      onSuccess: () => {
                        setCurrentPassword("");
                        setNewPassword("");
                        setShowCurrentPassword(false);
                        setShowNewPassword(false);
                        showToast({ body: "Пароль изменён", type: "info" });
                      },
                    },
                  );
                }}
              />
            </HStack>
          </VStack>
        </StackItem>
      </HStack>
    </VStack>
  );
}
