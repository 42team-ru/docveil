/**
 * Русское склонение числительного: `[форма для 1, форма для 2–4, форма для
 * остальных]` — «документ/документа/документов», «прогон/прогона/прогонов».
 * Стандартное правило: 11–14 всегда «остальные», иначе смотрим на последнюю
 * цифру.
 */
export function pluralRu(count: number, forms: readonly [string, string, string]): string {
  const [one, few, many] = forms;
  const mod10 = Math.abs(count) % 10;
  const mod100 = Math.abs(count) % 100;

  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}
