import { Check, Pencil, Trash2 } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Section } from "@astryxdesign/core/Section";
import { HStack } from "@astryxdesign/core/Stack";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

import type { LLMProfileOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { useActivateLlmProfile, useDeleteLlmProfile } from "../api/admin";

/** `Table` требует индексную сигнатуру строки — приём из `admin-users-table.tsx`. */
type ProfileRow = LLMProfileOut & Record<string, unknown>;

type AdminLlmProfilesTableProps = {
  profiles: LLMProfileOut[];
  /** Открыть диалог правки — только для своих профилей (`source: "custom"`). */
  onEdit: (profile: LLMProfileOut) => void;
};

/** Список профилей LLM: встроенные (YAML, только просмотр) и свои (БД, можно
 * править и удалить) — вкладка «Модели». */
export function AdminLlmProfilesTable({ profiles, onEdit }: AdminLlmProfilesTableProps) {
  const activate = useActivateLlmProfile();
  const remove = useDeleteLlmProfile();

  if (profiles.length === 0) {
    return (
      <Section padding={4}>
        <EmptyState title="Профилей пока нет" description="Странно — встроенный профиль должен быть всегда." />
      </Section>
    );
  }

  return (
    <Section padding={0}>
      <Table<ProfileRow>
        data={profiles as ProfileRow[]}
        idKey="name"
        density="balanced"
        hasHover
        textOverflow="truncate"
        columns={[
          {
            key: "name",
            header: "Профиль",
            width: proportional(2),
            renderCell: (profile) => (
              <HStack gap={1.5} vAlign="center">
                <Text weight="medium" maxLines={1}>
                  {profile.name}
                </Text>
                <Token
                  size="sm"
                  color={profile.source === "builtin" ? "gray" : "blue"}
                  label={profile.source === "builtin" ? "Встроенный" : "Свой"}
                />
              </HStack>
            ),
          },
          {
            key: "provider",
            header: "Провайдер",
            width: pixel(140),
            renderCell: (profile) => <Text color="secondary">{profile.provider}</Text>,
          },
          {
            key: "model",
            header: "Модель",
            width: pixel(220),
            renderCell: (profile) => (
              <Text color="secondary" maxLines={1}>
                {profile.model || "—"}
              </Text>
            ),
          },
          {
            key: "pricing",
            header: "Тариф",
            width: pixel(180),
            renderCell: (profile) =>
              profile.pricing ? (
                <Text color="secondary">
                  {`${profile.pricing.prompt_per_1k}/${profile.pricing.completion_per_1k} ${profile.pricing.currency} за 1К`}
                </Text>
              ) : (
                <Text color="secondary">не задан</Text>
              ),
          },
          {
            key: "is_active",
            header: "Статус",
            width: pixel(130),
            renderCell: (profile) =>
              profile.is_active ? (
                <StatusDot variant="success" label="Активен" />
              ) : (
                <StatusDot variant="neutral" label="Не активен" />
              ),
          },
          {
            key: "actions",
            header: "",
            width: pixel(200),
            renderCell: (profile) => (
              <HStack gap={1} vAlign="center" hAlign="end" width="100%">
                {!profile.is_active ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    label="Активировать"
                    icon={<Icon icon={Check} size="sm" />}
                    isLoading={activate.isPending}
                    onClick={() =>
                      activate.mutate({ source: profile.source, name: profile.name })
                    }
                  />
                ) : null}
                {profile.source === "custom" ? (
                  <IconButton
                    size="sm"
                    variant="ghost"
                    icon={<Icon icon={Pencil} size="sm" />}
                    label={`Изменить профиль «${profile.name}»`}
                    onClick={() => onEdit(profile)}
                  />
                ) : null}
                {profile.source === "custom" && profile.id ? (
                  <IconButton
                    size="sm"
                    variant="ghost"
                    icon={<Icon icon={Trash2} size="sm" />}
                    label={`Удалить профиль «${profile.name}»`}
                    isDisabled={profile.is_active}
                    isLoading={remove.isPending}
                    onClick={() => remove.mutate(profile.id as string)}
                  />
                ) : null}
              </HStack>
            ),
          },
        ]}
      />
    </Section>
  );
}
