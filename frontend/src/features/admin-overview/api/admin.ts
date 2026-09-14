import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getOverviewApiAdminOverviewGet,
  getRunsApiAdminRunsGet,
  getUsersApiAdminUsersGet,
} from "../../../shared/api/generated/core/admin/admin";
import { createUserEndpointApiUsersPost } from "../../../shared/api/generated/core/users/users";
import type {
  AdminOverviewOut,
  AdminRunListResponse,
  AdminUserRowOut,
  GetRunsApiAdminRunsGetParams,
  UserCreate,
  UserPublic,
} from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";

/**
 * Хуки админки поверх сгенерированного клиента — по образцу
 * `features/masking-run/api/masking-run.ts`: свой `queryKey`, явная проверка
 * кода ответа, русский текст ошибки для тоста/баннера.
 */
export const adminKeys = {
  all: ["admin"] as const,
  overview: (days: number) => ["admin", "overview", days] as const,
  users: () => ["admin", "users"] as const,
  runs: (params?: GetRunsApiAdminRunsGetParams) =>
    ["admin", "runs", params ?? {}] as const,
};

/** Единый ответ вкладки «Обзор» — агрегаты по пользователям, прогонам,
 * опциям, падениям, сессиям и топ-10 самых активных пользователей. */
export function useAdminOverview(days: number) {
  return useQuery({
    queryKey: adminKeys.overview(days),
    queryFn: async (): Promise<AdminOverviewOut> => {
      const response = await getOverviewApiAdminOverviewGet({ days });
      if (response.status !== 200) {
        throw new Error("Не удалось загрузить сводку админки");
      }
      return response.data;
    },
  });
}

/** Все пользователи системы с их активностью — вкладка «Пользователи». */
export function useAdminUsers() {
  return useQuery({
    queryKey: adminKeys.users(),
    queryFn: async (): Promise<AdminUserRowOut[]> => {
      const response = await getUsersApiAdminUsersGet();
      if (response.status !== 200) {
        throw new Error("Не удалось загрузить список пользователей");
      }
      return response.data;
    },
  });
}

/** Журнал прогонов всех пользователей — вкладка «Прогоны». */
export function useAdminRuns(params?: GetRunsApiAdminRunsGetParams) {
  return useQuery({
    queryKey: adminKeys.runs(params),
    queryFn: async (): Promise<AdminRunListResponse> => {
      const response = await getRunsApiAdminRunsGet(params);
      if (response.status !== 200) {
        throw new Error("Не удалось загрузить журнал прогонов");
      }
      return response.data;
    },
  });
}

/** Завести пользователя — `POST /users` (уже под `require_admin` на бэкенде,
 * второго эндпоинта под админку заводить не нужно). */
export function useCreateUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: UserCreate): Promise<UserPublic> => {
      const response = await createUserEndpointApiUsersPost(payload);
      if (response.status !== 201) {
        throw new Error("Не удалось создать пользователя");
      }
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.users() });
      void queryClient.invalidateQueries({ queryKey: adminKeys.all });
    },
  });
}
