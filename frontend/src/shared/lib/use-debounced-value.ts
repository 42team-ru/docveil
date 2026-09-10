import { useEffect, useState } from "react";

/**
 * Отложенное значение: обновляется через `delayMs` после того, как `value`
 * перестал меняться. Поле ввода остаётся мгновенным (биндится на исходное
 * значение), а сетевой запрос уходит по отложенному — не на каждое нажатие
 * клавиши.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
