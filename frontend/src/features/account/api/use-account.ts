import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  changeMyPasswordApiAuthMePasswordPost,
  deleteMyAvatarApiAuthMeAvatarDelete,
  getMeApiAuthMeGetQueryKey,
  logoutApiAuthLogoutPost,
  meApiAuthMeGet,
  updateMeApiAuthMePatch,
  uploadMyAvatarApiAuthMeAvatarPost,
} from "../../../shared/api/generated/core/auth/auth";
import type {
  PasswordChangeRequest,
  UserPublic,
} from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { clearAccessToken } from "../../../shared/api/auth-token";
import { clientApiWithAuth } from "../../../shared/api/mutators/authMutator";

/** Общий ключ кэша картинки аватара — один на аккаунт, а не на компонент:
 * и триггер в шапке (`account-trigger.tsx`), и профиль в диалоге показывают
 * один и тот же файл, и оба должны обновиться после загрузки нового. */
const AVATAR_QUERY_KEY = ["auth", "me", "avatar"] as const;

/** Текущий пользователь сессии — `GET /auth/me`. Раньше нигде не вызывался:
 * шапка (`panel-shell.tsx`) показывала статичную заглушку вместо реального
 * имени/email. */
export function useAccount() {
  return useQuery({
    queryKey: getMeApiAuthMeGetQueryKey(),
    queryFn: async (): Promise<UserPublic> => {
      const response = await meApiAuthMeGet();
      if (response.status !== 200) {
        throw new Error("Не удалось получить профиль");
      }
      return response.data;
    },
  });
}

/** Правка своего имени — `PATCH /auth/me`. */
export function useUpdateFullName() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (fullName: string): Promise<UserPublic> => {
      const response = await updateMeApiAuthMePatch({ full_name: fullName });
      if (response.status !== 200) {
        throw new Error("Не удалось сохранить имя");
      }
      return response.data;
    },
    onSuccess: (user) => {
      queryClient.setQueryData(getMeApiAuthMeGetQueryKey(), user);
    },
  });
}

/** Правка часового пояса — `PATCH /auth/me`. Отдельная мутация от имени:
 * применяется сразу по выбору в списке, без кнопки «Сохранить». */
export function useUpdateTimezone() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (timezone: string): Promise<UserPublic> => {
      const response = await updateMeApiAuthMePatch({ timezone });
      if (response.status !== 200) {
        throw new Error("Не удалось сохранить часовой пояс");
      }
      return response.data;
    },
    onSuccess: (user) => {
      queryClient.setQueryData(getMeApiAuthMeGetQueryKey(), user);
    },
  });
}

/** Смена пароля — `POST /auth/me/password`. Неверный текущий пароль приходит
 * обычной ошибкой запроса (401, `error.detail`), не полем ответа. */
export function useChangePassword() {
  return useMutation({
    mutationFn: (payload: PasswordChangeRequest) =>
      changeMyPasswordApiAuthMePasswordPost(payload),
  });
}

/** Загрузка/замена аватара — `POST /auth/me/avatar` (multipart). */
export function useUploadAvatar() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (file: File): Promise<UserPublic> => {
      const response = await uploadMyAvatarApiAuthMeAvatarPost({ file });
      if (response.status !== 200) {
        throw new Error("Не удалось загрузить аватар");
      }
      return response.data;
    },
    onSuccess: (user) => {
      queryClient.setQueryData(getMeApiAuthMeGetQueryKey(), user);
      // Новый файл лежит под тем же object_name или под новым — в обоих
      // случаях старый blob-URL устарел, а `has_avatar` мог остаться `true`
      // (замена, не первая загрузка), так что одного React Query enabled
      // toggle недостаточно: без явной инвалидации кэш отдал бы старую
      // картинку и триггеру в шапке, и профилю в диалоге.
      void queryClient.invalidateQueries({ queryKey: AVATAR_QUERY_KEY });
    },
  });
}

/** Удаление аватара — `DELETE /auth/me/avatar`. */
export function useDeleteAvatar() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (): Promise<UserPublic> => {
      const response = await deleteMyAvatarApiAuthMeAvatarDelete();
      if (response.status !== 200) {
        throw new Error("Не удалось удалить аватар");
      }
      return response.data;
    },
    onSuccess: (user) => {
      queryClient.setQueryData(getMeApiAuthMeGetQueryKey(), user);
      queryClient.setQueryData(AVATAR_QUERY_KEY, undefined);
    },
  });
}

/**
 * Картинка аватара как object URL для `<Avatar src=.../>`. Ключ кэша общий
 * (`AVATAR_QUERY_KEY`) — так загрузка нового файла в одном месте обновляет
 * аватар везде, где он показан. Отдельный авторизованный запрос, а не
 * сгенерированный хук: `GET /auth/me/avatar` отдаёт бинарник, и нужен
 * `responseType: "blob"`, как для артефактов прогона (`useArtifactObjectUrl`
 * в `masking-run.ts`).
 */
export function useAvatarUrl(hasAvatar: boolean): string | undefined {
  const { data } = useQuery({
    queryKey: AVATAR_QUERY_KEY,
    queryFn: async (): Promise<string> => {
      const response = await clientApiWithAuth.get<Blob>("/auth/me/avatar", {
        responseType: "blob",
      });
      return URL.createObjectURL(response.data);
    },
    enabled: hasAvatar,
    staleTime: Infinity,
  });
  return hasAvatar ? data : undefined;
}

/** Выход из аккаунта: отзывает refresh-токен на бэкенде, а не только
 * переходит на `/login` — иначе сессия оставалась бы живой на сервере. */
export function useLogout() {
  return useMutation({
    mutationFn: async () => {
      await logoutApiAuthLogoutPost().catch(() => {
        // Логаут — best-effort: даже если запрос не прошёл, локальный токен
        // всё равно чистим и уводим на вход.
      });
      clearAccessToken();
    },
  });
}
