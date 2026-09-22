import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  activateLlmProfileEndpointApiAdminLlmProfilesActivatePost,
  createLlmProfileEndpointApiAdminLlmProfilesPost,
  deleteLlmProfileEndpointApiAdminLlmProfilesProfileIdDelete,
  getOverviewApiAdminOverviewGet,
  getRunsApiAdminRunsGet,
  getUsersApiAdminUsersGet,
  listLlmProfilesEndpointApiAdminLlmProfilesGet,
  updateLlmProfileEndpointApiAdminLlmProfilesProfileIdPatch,
} from "../../../shared/api/generated/core/admin/admin";
import { createUserEndpointApiUsersPost } from "../../../shared/api/generated/core/users/users";
import type {
  AdminOverviewOut,
  AdminRunListResponse,
  AdminUserRowOut,
  GetRunsApiAdminRunsGetParams,
  LLMActivateRequest,
  LLMProfileCreate,
  LLMProfileOut,
  LLMProfileUpdate,
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
  llmProfiles: () => ["admin", "llm-profiles"] as const,
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

/** Профили LLM — встроенные (YAML) и свои (БД) — вкладка «Модели». */
export function useLlmProfiles() {
  return useQuery({
    queryKey: adminKeys.llmProfiles(),
    queryFn: async (): Promise<LLMProfileOut[]> => {
      const response = await listLlmProfilesEndpointApiAdminLlmProfilesGet();
      if (response.status !== 200) {
        throw new Error("Не удалось загрузить список профилей");
      }
      return response.data;
    },
  });
}

/** Завести свой профиль — `POST /admin/llm-profiles`. */
export function useCreateLlmProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: LLMProfileCreate): Promise<LLMProfileOut> => {
      const response = await createLlmProfileEndpointApiAdminLlmProfilesPost(payload);
      if (response.status !== 201) {
        throw new Error("Не удалось создать профиль");
      }
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.llmProfiles() });
    },
  });
}

/** Удалить свой профиль — `DELETE /admin/llm-profiles/{id}` (встроенные не удаляются). */
export function useDeleteLlmProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (profileId: string): Promise<void> => {
      const response = await deleteLlmProfileEndpointApiAdminLlmProfilesProfileIdDelete(profileId);
      if (response.status !== 204) {
        throw new Error("Не удалось удалить профиль");
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.llmProfiles() });
    },
  });
}

/** Переключить активный профиль — `POST /admin/llm-profiles/activate`. */
export function useActivateLlmProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: LLMActivateRequest): Promise<void> => {
      const response = await activateLlmProfileEndpointApiAdminLlmProfilesActivatePost(payload);
      if (response.status !== 204) {
        throw new Error("Не удалось переключить профиль");
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.llmProfiles() });
    },
  });
}

/** Править свой профиль — `PATCH /admin/llm-profiles/{id}` (имя неизменно). */
export function useUpdateLlmProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (args: { profileId: string; payload: LLMProfileUpdate }): Promise<LLMProfileOut> => {
      const response = await updateLlmProfileEndpointApiAdminLlmProfilesProfileIdPatch(
        args.profileId,
        args.payload,
      );
      if (response.status !== 200) {
        throw new Error("Не удалось сохранить профиль");
      }
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.llmProfiles() });
    },
  });
}
