import axios, { AxiosError } from "axios";
import type { AxiosRequestConfig, AxiosResponse, Method, ResponseType } from "axios";

import { clearAccessToken, getAccessToken, setAccessToken } from "../auth-token";

// Порт бэкенда — 8000 везде: `make api`, Dockerfile и docker-compose.
const LOCAL_BACKEND_ORIGIN = "http://localhost:8000";
const REMOTE_BACKEND_ORIGIN = "https://42team.ru";
// `/api` — единственное место, где префикс приклеивается к хосту. Схема,
// которую отдаёт `custom_openapi` (`api/main.py`), путей с `/api` не содержит
// — значит, и сгенерированный Orval-клиент их не содержит; без этого
// префикс задваивался бы или терялся в зависимости от того, где его забыли.
const API_PATH = "/api";
const GENERATED_BACKEND_PREFIXES = [
  `${LOCAL_BACKEND_ORIGIN}${API_PATH}`,
  `${REMOTE_BACKEND_ORIGIN}${API_PATH}`,
] as const;

const trimTrailingSlash = (value: string) => value.replace(/\/+$/, "");

const getBackendOrigin = () => {
  const mode = import.meta.env.MODE;

  if (mode === "production" || mode === "remote") {
    return import.meta.env.VITE_BACKEND_PROD_URL || REMOTE_BACKEND_ORIGIN;
  }

  return import.meta.env.VITE_BACKEND_DEV_URL || LOCAL_BACKEND_ORIGIN;
};

export const baseURL = `${trimTrailingSlash(getBackendOrigin())}${API_PATH}`;
export const REFRESH_ENDPOINT = "/auth/refresh";
const MAX_REFRESH_RETRIES = 1;

type ExtendedAxiosRequestConfig = AxiosRequestConfig & {
  _retryCount?: number;
};

type MutatorConfig = {
  method?: Method;
  params?: AxiosRequestConfig["params"];
  data?: unknown;
  headers?: HeadersInit;
  responseType?: ResponseType;
  signal?: AbortSignal | null;
  body?: BodyInit | null;
};

type ValidationErrorItem = {
  type: string;
  loc: (string | number)[];
  msg: string;
  input: unknown;
};

type ApiErrorPayload = {
  detail?: string | ValidationErrorItem[];
  message?: string;
};

export type ErrorType<TError = ApiErrorPayload> = AxiosError<TError> & {
  detail?: string;
  status?: number;
};

const normalizeHeaders = (
  headers?: HeadersInit,
): AxiosRequestConfig["headers"] => {
  if (!headers) {
    return undefined;
  }

  if (typeof Headers !== "undefined" && headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }

  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }

  return { ...(headers as Record<string, string>) };
};

const PUBLIC_AUTH_PATHS = [
  "/auth/login",
  "/auth/register",
  "/auth/check/username",
  "/auth/check/email",
  "/auth/users/check/username",
  "/auth/users/check/email",
];

const normalizeBackendUrl = (url: string): string => {
  const normalizedPrefixes = [
    trimTrailingSlash(baseURL),
    ...GENERATED_BACKEND_PREFIXES.map(trimTrailingSlash),
  ];

  for (const prefix of normalizedPrefixes) {
    if (url === prefix) {
      return "/";
    }

    if (url.startsWith(`${prefix}/`)) {
      return url.slice(prefix.length);
    }
  }

  return url;
};

const isPublicAuthEndpoint = (url: string): boolean => {
  try {
    const normalizedPath = new URL(url, baseURL).pathname;
    return PUBLIC_AUTH_PATHS.some((path) => normalizedPath.endsWith(path));
  } catch {
    return PUBLIC_AUTH_PATHS.some((path) => url.endsWith(path));
  }
};

const normalizeAxiosError = (error: AxiosError<ApiErrorPayload>) => {
  const normalizedError = error as ErrorType<ApiErrorPayload>;
  const detail = error.response?.data?.detail;
  normalizedError.detail =
    (Array.isArray(detail) ? detail.map((e) => e.msg).join(", ") : detail) ||
    error.response?.data?.message ||
    error.message;
  normalizedError.status = error.response?.status;
  return normalizedError;
};

const dispatchUnauthorized = () => {
  clearAccessToken();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("auth:unauthorized"));
  }
};

export const clientApi = axios.create({
  baseURL,
  withCredentials: true,
});

export const clientApiWithAuth = axios.create({
  baseURL,
  withCredentials: true,
});

// Bearer на каждый запрос: бэкенд читает access-токен только из заголовка
// (`HTTPBearer` в `api/core/deps.py`), cookie у него — исключительно refresh.
clientApiWithAuth.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

let refreshPromise: Promise<void> | null = null;

/** Single refresh call; concurrent 401s share one in-flight request via refreshPromise. */
const refreshAccessTokenOnce = async (): Promise<void> => {
  if (!refreshPromise) {
    refreshPromise = clientApi
      .post<{ access_token?: string }>(REFRESH_ENDPOINT)
      .then((response) => {
        // Ответ несёт новый access — без этого повтор запроса уйдёт со старым
        // просроченным токеном и снова получит 401.
        setAccessToken(response.data?.access_token ?? null);
      })
      .finally(() => {
        refreshPromise = null;
      });
  }

  return refreshPromise;
};

clientApiWithAuth.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError<ApiErrorPayload>) => {
    const originalRequest = error.config as
      | ExtendedAxiosRequestConfig
      | undefined;

    if (!originalRequest) {
      return Promise.reject(normalizeAxiosError(error));
    }

    const isUnauthorized = error.response?.status === 401;
    const isRefreshCall = originalRequest.url?.includes(REFRESH_ENDPOINT);

    if (!isUnauthorized || isRefreshCall) {
      return Promise.reject(normalizeAxiosError(error));
    }

    originalRequest._retryCount = originalRequest._retryCount ?? 0;

    if (originalRequest._retryCount >= MAX_REFRESH_RETRIES) {
      dispatchUnauthorized();
      return Promise.reject(normalizeAxiosError(error));
    }

    originalRequest._retryCount += 1;

    try {
      await refreshAccessTokenOnce();

      return clientApiWithAuth(originalRequest);
    } catch (refreshError) {
      dispatchUnauthorized();

      if (axios.isAxiosError<ApiErrorPayload>(refreshError)) {
        return Promise.reject(normalizeAxiosError(refreshError));
      }

      return Promise.reject(refreshError);
    }
  },
);

export const authMutator = async <T>(
  url: string,
  options?: RequestInit & MutatorConfig,
): Promise<T> => {
  const method = (options?.method as Method | undefined) ?? "GET";
  const requestUrl = normalizeBackendUrl(url);

  // Orval can pass payload either as fetch-style body or axios-style data.
  const data = options?.data ?? options?.body;

  const requestConfig: AxiosRequestConfig = {
    url: requestUrl,
    method,
    params: options?.params,
    data,
    responseType: options?.responseType,
    signal: options?.signal ?? undefined,
    headers: normalizeHeaders(options?.headers),
  };

  const apiClient = isPublicAuthEndpoint(requestUrl)
    ? clientApi
    : clientApiWithAuth;

  const response = await apiClient
    .request<unknown>(requestConfig)
    .catch((error) => {
      if (axios.isAxiosError<ApiErrorPayload>(error)) {
        throw normalizeAxiosError(error);
      }
      throw error;
    });

  const wrappedResponse = {
    data: response.data,
    status: response.status,
    headers: new Headers(response.headers as HeadersInit),
  };

  return wrappedResponse as T;
};
