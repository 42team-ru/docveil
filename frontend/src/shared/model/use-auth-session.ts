import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { getAccessToken, setAccessToken } from "../api/auth-token";
import { clientApi, isGenuineUnauthorized, REFRESH_ENDPOINT } from "../api/mutators/authMutator";

type SessionState = "checking" | "ready" | "anonymous";

/**
 * Сессия защищённой части приложения.
 *
 * Access-токен живёт в памяти вкладки, поэтому после перезагрузки его нет —
 * но refresh-токен остаётся в httpOnly-cookie, и сессия восстанавливается
 * одним запросом. Если восстановить не удалось, пользователь уходит на вход;
 * туда же его отправляет событие `auth:unauthorized`, которое поднимает
 * транспорт, когда обновление токена не помогло.
 */
export function useAuthSession(): SessionState {
  const navigate = useNavigate();
  const [state, setState] = useState<SessionState>(
    getAccessToken() ? "ready" : "checking",
  );

  useEffect(() => {
    const goToLogin = () => {
      setState("anonymous");
      navigate("/login");
    };

    window.addEventListener("auth:unauthorized", goToLogin);

    if (getAccessToken()) {
      setState("ready");
      return () => window.removeEventListener("auth:unauthorized", goToLogin);
    }

    let cancelled = false;
    clientApi
      .post<{ access_token?: string }>(REFRESH_ENDPOINT)
      .then((response) => {
        if (cancelled) return;
        const token = response.data?.access_token;
        if (!token) {
          goToLogin();
          return;
        }
        setAccessToken(token);
        setState("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // 401 на refresh — сессии правда нет, на вход. Любая другая ошибка
        // (500, обрыв сети) не означает разлогин: молча остаёмся в
        // "checking" — экраны под каркасом сами покажут ошибку своих
        // запросов, когда попробуют что-то загрузить с тем же битым
        // соединением, вместо того чтобы прямо сейчас увести на /login
        // человека с действующей сессией.
        if (isGenuineUnauthorized(error)) goToLogin();
      });

    return () => {
      cancelled = true;
      window.removeEventListener("auth:unauthorized", goToLogin);
    };
  }, [navigate]);

  return state;
}
