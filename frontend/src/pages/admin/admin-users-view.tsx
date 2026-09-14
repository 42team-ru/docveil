import { useState } from "react";
import { UserPlus } from "lucide-react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Section } from "@astryxdesign/core/Section";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { HStack, VStack } from "@astryxdesign/core/Stack";

import { useAdminUsers } from "../../features/admin-overview/api/admin";
import { AdminUsersTable } from "../../features/admin-overview/ui/admin-users-table";
import { CreateUserDialog } from "../../features/admin-overview/ui/create-user-dialog";

/** Вкладка «Пользователи»: список всех аккаунтов системы + форма заведения
 * нового (`POST /api/users`, уже под `require_admin`). */
export function AdminUsersView() {
  const users = useAdminUsers();
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  return (
    <VStack gap={4}>
      <HStack hAlign="end">
        <Button
          size="sm"
          variant="primary"
          label="Добавить пользователя"
          icon={<Icon icon={UserPlus} size="sm" />}
          onClick={() => setIsCreateOpen(true)}
        />
      </HStack>

      {users.isLoading ? (
        <Section padding={4}>
          <Skeleton height={320} width="100%" />
        </Section>
      ) : users.isError || !users.data ? (
        <Banner
          status="error"
          container="card"
          collapsible={false}
          title="Список пользователей недоступен"
          endContent={
            <Button size="sm" variant="secondary" label="Повторить" onClick={() => void users.refetch()} />
          }
        />
      ) : (
        <AdminUsersTable users={users.data} />
      )}

      <CreateUserDialog isOpen={isCreateOpen} onOpenChange={setIsCreateOpen} />
    </VStack>
  );
}
