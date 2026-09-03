/** Тип персональных данных, который можно включить в маскирование. */
export type DataType = {
  id: string;
  name: string;
  /** Шаблон маркера, который встанет вместо значения. */
  marker: string;
};

/** Готовый профиль правил маскирования. */
export type RulePreset = {
  id: string;
  name: string;
  description: string;
};

/** Как выглядит маска в выходном документе. */
export type MaskStyle = "marker" | "block";
