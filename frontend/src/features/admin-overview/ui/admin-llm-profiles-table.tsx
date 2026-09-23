import { Bot, Cpu, FlaskConical, MessageCircle, Network, Pencil, Trash2 } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Grid } from "@astryxdesign/core/Grid";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

import type { LLMProfileOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { useActivateLlmProfile, useDeleteLlmProfile } from "../api/admin";
import "./admin-llm-profiles-table.css";

type AdminLlmProfilesTableProps = {
  profiles: LLMProfileOut[];
  onEdit: (profile: LLMProfileOut) => void;
};

const PROVIDER_ICONS: Record<string, typeof Bot> = {
  cassette: FlaskConical,
  fake: FlaskConical,
  gigachat: MessageCircle,
  ollama: Cpu,
  openrouter: Network,
};

function profileIcon(provider: string): typeof Bot {
  return PROVIDER_ICONS[provider.toLowerCase()] ?? Bot;
}

function pricingLabel(profile: LLMProfileOut): string {
  const pricing = profile.pricing;
  if (!pricing) return "Не задан";
  return `${pricing.prompt_per_1k}/${pricing.completion_per_1k} ${pricing.currency ?? "валюта не указана"} за 1К`;
}

function ProfileCard({
  profile,
  onEdit,
  onActivate,
  onDelete,
  isActivating,
  isDeleting,
}: {
  profile: LLMProfileOut;
  onEdit: (profile: LLMProfileOut) => void;
  onActivate: (profile: LLMProfileOut) => void;
  onDelete: (profile: LLMProfileOut) => void;
  isActivating: boolean;
  isDeleting: boolean;
}) {
  return (
    <Card padding={4} className="admin-llm-profile-card">
      <VStack gap={4}>
        <HStack gap={3} vAlign="start" width="100%">
          <HStack
            hAlign="center"
            vAlign="center"
            className="size-10 shrink-0 rounded-xl border border-default bg-muted text-secondary"
            aria-hidden="true"
          >
            <Icon icon={profileIcon(profile.provider)} size="md" />
          </HStack>
          <StackItem size="fill">
            <VStack gap={1} className="min-w-0">
              <Text type="label" weight="semibold" textWrap="pretty" className="admin-llm-profile-value">
                {profile.name}
              </Text>
              <Text type="supporting" color="secondary" textWrap="pretty" className="admin-llm-profile-value">
                {profile.provider} · {profile.model || "Модель не указана"}
              </Text>
            </VStack>
          </StackItem>
          <VStack gap={1} hAlign="end">
            <Token
              size="sm"
              color={profile.is_active ? "green" : "gray"}
              label={profile.is_active ? "Активен" : "Не активен"}
            />
            <Token
              size="sm"
              color={profile.source === "builtin" ? "gray" : "blue"}
              label={profile.source === "builtin" ? "Встроенный" : "Свой"}
            />
          </VStack>
        </HStack>

        <Grid columns={{ minWidth: 100, max: 2, repeat: "fit" }} gap={3}>
          <VStack gap={1} className="min-w-0">
            <Text type="supporting" color="secondary" size="sm">Тариф</Text>
            <Text textWrap="pretty" className="admin-llm-profile-value">{pricingLabel(profile)}</Text>
          </VStack>
          <VStack gap={1} className="min-w-0">
            <Text type="supporting" color="secondary" size="sm">Токен</Text>
            <Text textWrap="pretty" className="admin-llm-profile-value">
              {profile.has_api_key ? "Задан" : "Не задан"}
            </Text>
          </VStack>
        </Grid>

        <HStack gap={2} wrap="wrap" vAlign="center">
          {!profile.is_active ? (
            <Button
              size="sm"
              variant="secondary"
              label="Активировать"
              isLoading={isActivating}
              onClick={() => onActivate(profile)}
            />
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            icon={<Icon icon={Pencil} size="sm" />}
            label="Изменить"
            onClick={() => onEdit(profile)}
          />
          {profile.source === "custom" && profile.id ? (
            <IconButton
              size="sm"
              variant="ghost"
              icon={<Icon icon={Trash2} size="sm" />}
              label={`Удалить профиль «${profile.name}»`}
              isDisabled={profile.is_active}
              isLoading={isDeleting}
              onClick={() => onDelete(profile)}
            />
          ) : null}
        </HStack>
      </VStack>
    </Card>
  );
}

/** Карточки профилей LLM: встроенные и пользовательские настройки — вкладка «Модели». */
export function AdminLlmProfilesTable({ profiles, onEdit }: AdminLlmProfilesTableProps) {
  const activate = useActivateLlmProfile();
  const remove = useDeleteLlmProfile();

  if (profiles.length === 0) {
    return (
      <Section padding={4}>
        <EmptyState title="Профилей пока нет" description="Встроенный профиль появится после обновления списка." />
      </Section>
    );
  }

  return (
    <Grid columns={{ minWidth: 240, max: 3, repeat: "fit" }} gap={4}>
      {profiles.map((profile) => (
        <ProfileCard
          key={`${profile.source}:${profile.name}`}
          profile={profile}
          onEdit={onEdit}
          onActivate={(target) => activate.mutate({ source: target.source, name: target.name })}
          onDelete={(target) => { if (target.id) remove.mutate(target.id); }}
          isActivating={activate.isPending}
          isDeleting={remove.isPending}
        />
      ))}
    </Grid>
  );
}
