import { useState } from "react";
import { useNavigate } from "react-router";
import { LogOut } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Divider } from "@astryxdesign/core/Divider";
import { Icon } from "@astryxdesign/core/Icon";
import {
  Layout,
  LayoutContent,
  LayoutFooter,
} from "@astryxdesign/core/Layout";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { useLogout } from "../api/use-account";
import { AccountAppearanceSection } from "./account-appearance-section";
import { AccountProfileSection } from "./account-profile-section";

type AccountDialogProps = {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
};

/**
 * Диалог аккаунта: один скроллящийся диалог без sidebar-навигации —
 * «Профиль» и «Оформление» друг под другом. Заменяет прежний
 * `ProfilePopover` (`panel-shell.tsx`), где было только имя/email-заглушка,
 * тема и выход.
 *
 * «Выйти» подтверждается прямо в футере (не отдельным диалогом поверх этого
 * же — два перекрывающихся способа закрытия сбивают фокус) и реально отзывает
 * refresh-токен на бэкенде (`useLogout`), а не просто уводит на `/login`.
 */
export function AccountDialog({ isOpen, onOpenChange }: AccountDialogProps) {
  const navigate = useNavigate();
  const logout = useLogout();
  const [isConfirmingLogout, setIsConfirmingLogout] = useState(false);

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={(open) => {
        onOpenChange(open);
        if (!open) setIsConfirmingLogout(false);
      }}
      purpose="info"
      width={720}
    >
      <Layout
        header={
          <DialogHeader title="Аккаунт" onOpenChange={() => onOpenChange(false)} />
        }
        content={
          <LayoutContent>
            <VStack gap={5}>
              <AccountProfileSection />
              <Divider />
              <AccountAppearanceSection />
            </VStack>
          </LayoutContent>
        }
        footer={
          <LayoutFooter hasDivider>
            {isConfirmingLogout ? (
              <HStack gap={2} hAlign="between" vAlign="center" width="100%">
                <Text type="supporting" color="secondary">
                  Выйти из аккаунта на этом устройстве?
                </Text>
                <HStack gap={2}>
                  <Button
                    label="Отмена"
                    variant="ghost"
                    size="sm"
                    onClick={() => setIsConfirmingLogout(false)}
                  />
                  <Button
                    label="Выйти"
                    variant="destructive"
                    size="sm"
                    isLoading={logout.isPending}
                    onClick={() => {
                      logout.mutate(undefined, {
                        onSuccess: () => navigate("/login", { viewTransition: true }),
                      });
                    }}
                  />
                </HStack>
              </HStack>
            ) : (
              <Button
                label="Выйти"
                variant="ghost"
                size="sm"
                icon={<Icon icon={LogOut} size="sm" />}
                onClick={() => setIsConfirmingLogout(true)}
              />
            )}
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
