import { useState } from "react";
import { Check, Copy, Trash2 } from "lucide-react";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Button } from "@astryxdesign/core/Button";
import { FileInput } from "@astryxdesign/core/FileInput";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { useToast } from "@astryxdesign/core/Toast";

import { ROLE_LABEL } from "../../../entity/user/model/roles";
import type { UserPublic } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { useAvatarUrl, useDeleteAvatar, useUploadAvatar } from "../api/use-account";

type AccountIdentityProps = {
  user: UserPublic;
};

/** Шапка профиля: аватар (со сменой файла), email с копированием, роль и
 * статус аккаунта. */
export function AccountIdentity({ user }: AccountIdentityProps) {
  const avatarUrl = useAvatarUrl(user.has_avatar ?? false);
  const uploadAvatar = useUploadAvatar();
  const deleteAvatar = useDeleteAvatar();
  const showToast = useToast();
  const [isCopied, setIsCopied] = useState(false);

  function handleCopyEmail() {
    if (navigator.clipboard) void navigator.clipboard.writeText(user.email);
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), 1500);
  }

  function handleAvatarChange(file: File | File[] | null) {
    if (!file || Array.isArray(file)) return;
    uploadAvatar.mutate(file, {
      onError: () => showToast({ body: "Не удалось загрузить аватар", type: "error" }),
    });
  }

  function handleDeleteAvatar() {
    deleteAvatar.mutate(undefined, {
      onSuccess: () => showToast({ body: "Аватар удалён", type: "info" }),
      onError: () => showToast({ body: "Не удалось удалить аватар", type: "error" }),
    });
  }

  return (
    <HStack gap={4} vAlign="center">
      <VStack gap={1} hAlign="center">
        <Avatar name={user.full_name} src={avatarUrl} size="xl" tooltip={false} />
        <FileInput
          label="Сменить фото"
          isLabelHidden
          placeholder="Сменить фото"
          mode="input"
          accept="image/*"
          value={null}
          onChange={handleAvatarChange}
          isLoading={uploadAvatar.isPending}
          isDisabled={deleteAvatar.isPending}
          width={140}
        />
        {user.has_avatar ? (
          <Button
            size="sm"
            variant="ghost"
            label="Удалить фото"
            icon={<Icon icon={Trash2} size="sm" />}
            isDisabled={uploadAvatar.isPending}
            isLoading={deleteAvatar.isPending}
            onClick={handleDeleteAvatar}
          />
        ) : null}
      </VStack>

      <VStack gap={2} className="min-w-0">
        <Text type="large" weight="semibold" maxLines={1}>
          {user.full_name}
        </Text>
        <HStack gap={1.5} vAlign="center">
          <Text weight="medium" maxLines={1}>
            {user.email}
          </Text>
          <IconButton
            size="sm"
            variant="ghost"
            label="Скопировать email"
            icon={<Icon icon={isCopied ? Check : Copy} size="sm" />}
            onClick={handleCopyEmail}
          />
        </HStack>
        <HStack gap={2} vAlign="center">
          {user.roles.map((role) => (
            <Token key={role} label={ROLE_LABEL[role] ?? role} />
          ))}
          <HStack gap={1.5} vAlign="center">
            <StatusDot variant="success" label="Активен" />
            <Text type="supporting" color="secondary">
              Активен
            </Text>
          </HStack>
        </HStack>
      </VStack>
    </HStack>
  );
}
