import type {
  Role,
  UserPublic,
} from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";

/** Русская подпись роли — общая для чипа в профиле (`account-identity.tsx`)
 * и таблицы пользователей в админке. */
export const ROLE_LABEL: Record<Role, string> = {
  admin: "Администратор",
  user: "Пользователь",
};

/**
 * Единственное место, где решается «этот пользователь — админ или нет».
 * И меню (`masker-layout.tsx`), и guard роута (`routes/masker/admin.tsx`)
 * читают роль отсюда — а не изобретают собственную проверку `roles.includes`.
 *
 * Проверка чисто клиентская, для UX (показать/скрыть пункт меню, отбить
 * прямой заход раньше, чем уйдёт запрос). Настоящая защита — `require_admin`
 * на бэкенде (`backend/src/api/core/deps.py`); второй копии той же проверки
 * здесь быть не должно.
 */
export function isAdmin(user: UserPublic | null | undefined): boolean {
  return user?.roles.includes("admin") ?? false;
}
