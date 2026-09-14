import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Section } from "@astryxdesign/core/Section";
import { HStack } from "@astryxdesign/core/Stack";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

import { ROLE_LABEL } from "../../../entity/user/model/roles";
import type { AdminUserRowOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { formatMoment } from "../../../shared/lib/format-moment";

/** `Table` требует индексную сигнатуру строки — приём из
 * `document-history/ui/history-table.tsx#RunRow`. */
type UserRow = AdminUserRowOut & Record<string, unknown>;

type AdminUsersTableProps = {
  users: AdminUserRowOut[];
};

/** Все пользователи системы с активностью — вкладка «Пользователи». */
export function AdminUsersTable({ users }: AdminUsersTableProps) {
  if (users.length === 0) {
    return (
      <Section padding={4}>
        <EmptyState title="Пользователей пока нет" description="Заведите первого через «Добавить пользователя»." />
      </Section>
    );
  }

  return (
    <Section padding={0}>
      <Table<UserRow>
        data={users as UserRow[]}
        idKey="id"
        density="balanced"
        hasHover
        textOverflow="truncate"
        columns={[
          {
            key: "full_name",
            header: "Пользователь",
            width: proportional(2),
            renderCell: (user) => (
              <HStack gap={1} vAlign="center">
                <Text weight="medium" maxLines={1}>
                  {user.full_name}
                </Text>
                <Text color="secondary" maxLines={1}>
                  {user.email}
                </Text>
              </HStack>
            ),
          },
          {
            key: "roles",
            header: "Роли",
            width: pixel(160),
            renderCell: (user) => (
              <HStack gap={1.5} wrap="wrap">
                {user.roles.map((role) => (
                  <Token key={role} size="sm" label={ROLE_LABEL[role] ?? role} />
                ))}
              </HStack>
            ),
          },
          {
            key: "is_active",
            header: "Статус",
            width: pixel(120),
            renderCell: (user) =>
              user.is_active ? (
                <StatusDot variant="success" label="Активен" />
              ) : (
                <StatusDot variant="neutral" label="Деактивирован" />
              ),
          },
          {
            key: "runs_total",
            header: "Прогонов",
            width: pixel(140),
            renderCell: (user) => {
              const failed = user.runs_failed ?? 0;
              return (
                <Text color={failed > 0 ? "primary" : "secondary"}>
                  {`${user.runs_total ?? 0} (${failed} с ошибкой)`}
                </Text>
              );
            },
          },
          {
            key: "active_sessions",
            header: "Сессий",
            width: pixel(90),
            renderCell: (user) => <Text>{user.active_sessions}</Text>,
          },
          {
            key: "last_login_at",
            header: "Последний вход",
            width: pixel(150),
            renderCell: (user) => (
              <Text color="secondary">{formatMoment(user.last_login_at)}</Text>
            ),
          },
          {
            key: "created_at",
            header: "Зарегистрирован",
            width: pixel(150),
            renderCell: (user) => (
              <Text color="secondary">{formatMoment(user.created_at)}</Text>
            ),
          },
        ]}
      />
    </Section>
  );
}
