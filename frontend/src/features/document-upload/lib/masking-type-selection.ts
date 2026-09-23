export type EnabledTypeSelection = string[] | null;

/** `null` — специальное состояние «выбраны все встроенные типы». */
export function areAllTypesSelected(enabledTypes: EnabledTypeSelection): boolean {
  return enabledTypes === null;
}

/** Переключает общий чекбокс: со всех на ноль и с нуля на все. */
export function toggleAllTypes(enabledTypes: EnabledTypeSelection): EnabledTypeSelection {
  return enabledTypes === null ? [] : null;
}

/** Обновляет список чекбоксов; выбор последнего типа сворачивается в `null`. */
export function updateTypeSelection(
  enabledTypes: EnabledTypeSelection,
  typeId: string,
  checked: boolean,
  allTypeIds: readonly string[],
): EnabledTypeSelection {
  const selected = enabledTypes ?? [...allTypeIds];
  const next = checked
    ? selected.includes(typeId) ? selected : [...selected, typeId]
    : selected.filter((type) => type !== typeId);

  return next.length === allTypeIds.length ? null : next;
}

/** Можно запускать, если выбраны встроенные типы либо добавлен хотя бы один свой. */
export function hasAnyTypeSelected(
  enabledTypes: EnabledTypeSelection,
  customTypeCount: number,
): boolean {
  return enabledTypes === null || enabledTypes.length > 0 || customTypeCount > 0;
}
