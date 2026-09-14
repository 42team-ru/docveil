import { useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxList, CheckboxListItem } from "@astryxdesign/core/CheckboxList";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useToast } from "@astryxdesign/core/Toast";

import { ROLE_LABEL } from "../../../entity/user/model/roles";
import type { Role } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { evaluatePasswordStrength } from "../../account/lib/password-strength";
import { useCreateUser } from "../api/admin";

type CreateUserDialogProps = {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
};

const ALL_ROLES: Role[] = ["user", "admin"];

/** `POST /api/users` уже существует и уже под `require_admin` на бэкенде —
 * диалог только собирает форму и вызывает готовую мутацию (`api/admin.ts`). */
export function CreateUserDialog({ isOpen, onOpenChange }: CreateUserDialogProps) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [roles, setRoles] = useState<Role[]>(["user"]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const createUser = useCreateUser();
  const showToast = useToast();

  const strength = evaluatePasswordStrength(password);
  const canSubmit =
    email.trim() !== "" && fullName.trim() !== "" && password.length >= 8 && roles.length > 0;

  function resetAndClose() {
    setEmail("");
    setFullName("");
    setPassword("");
    setRoles(["user"]);
    setErrorMessage(null);
    onOpenChange(false);
  }

  function handleSubmit() {
    setErrorMessage(null);
    createUser.mutate(
      { email: email.trim(), full_name: fullName.trim(), password, roles },
      {
        onSuccess: () => {
          showToast({ body: "Пользователь создан", type: "info" });
          resetAndClose();
        },
        onError: (error: unknown) => {
          const status = (error as { status?: number }).status;
          setErrorMessage(
            status === 409
              ? "Пользователь с таким email уже существует"
              : "Не удалось создать пользователя",
          );
        },
      },
    );
  }

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={(open) => (open ? onOpenChange(true) : resetAndClose())}
      purpose="form"
      width={480}
    >
      <Layout
        header={<DialogHeader title="Добавить пользователя" onOpenChange={() => resetAndClose()} />}
        content={
          <LayoutContent>
            <VStack gap={4}>
              {errorMessage ? (
                <Banner
                  status="error"
                  collapsible={false}
                  title="Не удалось создать пользователя"
                  description={errorMessage}
                />
              ) : null}
              <TextInput
                label="Email"
                type="email"
                value={email}
                onChange={setEmail}
              />
              <TextInput label="Имя" value={fullName} onChange={setFullName} />
              <VStack gap={1}>
                <TextInput
                  label="Пароль"
                  type="password"
                  value={password}
                  onChange={setPassword}
                  description="Минимум 8 символов"
                />
                {password ? (
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
              </VStack>
              <CheckboxList
                label="Роли"
                value={roles}
                onChange={(values) => setRoles(values as Role[])}
              >
                {ALL_ROLES.map((role) => (
                  <CheckboxListItem key={role} value={role} label={ROLE_LABEL[role]} />
                ))}
              </CheckboxList>
            </VStack>
          </LayoutContent>
        }
        footer={
          <LayoutFooter hasDivider>
            <Button label="Отмена" variant="ghost" size="sm" onClick={resetAndClose} />
            <Button
              label="Добавить"
              variant="primary"
              size="sm"
              isDisabled={!canSubmit}
              isLoading={createUser.isPending}
              onClick={handleSubmit}
            />
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
