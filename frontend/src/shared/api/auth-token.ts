/**
 * Access-токен живёт в памяти вкладки, а не в `localStorage`.
 *
 * Долгоживущий секрет — это refresh-токен, и он лежит в httpOnly-cookie, куда
 * скрипт страницы не дотянется. Короткий access (15 минут, `settings.
 * access_token_expire_minutes`) держать в хранилище браузера незачем: после
 * перезагрузки вкладки его восстанавливает `POST /api/auth/refresh` по той же
 * cookie — см. `authMutator`.
 */

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function clearAccessToken(): void {
  accessToken = null;
}
