import { QueryClient } from "@tanstack/react-query";

/**
 * Один клиент на приложение. `retry: false` — потому что ошибки этого API
 * осмысленные (404 «отчёта ещё нет», 409 «ответы сейчас не принимаются»), и
 * повторять их трижды значит только задержать сообщение оператору.
 * Опрос состояния прогона задаётся точечно, через `refetchInterval` в самом
 * хуке, а не глобально.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
        staleTime: 5_000,
      },
      mutations: { retry: false },
    },
  });
}
