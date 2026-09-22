import { useState } from "react";
import { Plus } from "lucide-react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Section } from "@astryxdesign/core/Section";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { useLlmProfiles } from "../../features/admin-overview/api/admin";
import { AdminLlmProfilesTable } from "../../features/admin-overview/ui/admin-llm-profiles-table";
import { LlmProfileDialog } from "../../features/admin-overview/ui/llm-profile-dialog";
import type { LLMProfileOut } from "../../shared/api/generated/core/triemaMaskerAPI.schemas";

/** Вкладка «Модели»: какой профиль LLM сейчас обслуживает прогоны, и
 * переключение между встроенными (`masker.yaml`) и своими профилями.
 * Секреты (ключи API) сюда не попадают — только имя переменной окружения,
 * где сервер их ищет. */
export function AdminLlmSettingsView() {
  const profiles = useLlmProfiles();
  const [dialogProfile, setDialogProfile] = useState<LLMProfileOut | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);

  return (
    <VStack gap={4}>
      <Text type="supporting" color="secondary" size="sm">
        Активный профиль обслуживает все новые прогоны и компиляцию своих
        типов. Переключение не требует перезапуска сервера.
      </Text>

      <HStack hAlign="end">
        <Button
          size="sm"
          variant="primary"
          label="Новый профиль"
          icon={<Icon icon={Plus} size="sm" />}
          onClick={() => {
            setDialogProfile(null);
            setIsDialogOpen(true);
          }}
        />
      </HStack>

      {profiles.isLoading ? (
        <Section padding={4}>
          <Skeleton height={220} width="100%" />
        </Section>
      ) : profiles.isError || !profiles.data ? (
        <Banner
          status="error"
          container="card"
          collapsible={false}
          title="Список профилей недоступен"
          endContent={
            <Button
              size="sm"
              variant="secondary"
              label="Повторить"
              onClick={() => void profiles.refetch()}
            />
          }
        />
      ) : (
        <AdminLlmProfilesTable
          profiles={profiles.data}
          onEdit={(profile) => {
            setDialogProfile(profile);
            setIsDialogOpen(true);
          }}
        />
      )}

      <LlmProfileDialog
        isOpen={isDialogOpen}
        onOpenChange={setIsDialogOpen}
        editingProfile={dialogProfile}
      />
    </VStack>
  );
}
