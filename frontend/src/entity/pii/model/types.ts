/** Формат документа, из которого извлечены ПДн. */
export type PiiDocFormat = "docx" | "pdf" | "xlsx";

/** Категория персональных данных, которую распознаёт бэкенд. */
export type PiiType =
  | "org_name"
  | "person_name"
  | "address"
  | "bank_account"
  | "inn"
  | "kpp"
  | "email"
  | "website"
  | "phone"
  | "money"
  | "date"
  | "contract_no";

/** Источник обнаружения: модель именованных сущностей или правило. */
export type PiiSource = "ner" | "rule";

/** Адресация фрагмента в объектную модель документа. */
export type PiiAnchor = {
  format: PiiDocFormat;
  /** Человекочитаемая метка для отладки и отчётов, напр. «абзац 19». */
  label: string;
  /** Путь до узла документа. Для docx: ["body", N] — N-й абзац в порядке документа. */
  locator: (string | number)[];
};

/** Одно найденное вхождение ПДн внутри чанка. */
export type PiiOccurrence = {
  /** Ссылка на сущность в рамках документа, напр. "E1". */
  ref: string;
  /** Группа: все вхождения одной и той же сущности по документу. */
  groupId: string;
  /** Маркер, уже вписанный в маскированный документ, напр. "[ФИО-1]". */
  marker: string;
  type: PiiType;
  /**
   * Исходный текст ПДн до маскирования. В промаскированном docx его больше нет —
   * это чисто справочное поле из JSON для отображения оператору в панели.
   */
  text: string;
  normalized: string;
  confidence: number;
  source: PiiSource;
  segmentOrder: number;
  /** Смещения в пределах chunk.text — только для отчётности, не для поиска в DOM. */
  chunkStart: number;
  chunkEnd: number;
};

/** Абзац (или иной узел) документа с одним или несколькими вхождениями ПДн. */
export type PiiChunk = {
  id: string;
  text: string;
  anchor: PiiAnchor;
  segmentOrder: number;
  pii: PiiOccurrence[];
};

/** Результат разбора документа бэкендом — вся выдача для экрана проверки. */
export type PiiExtraction = {
  chunkCount: number;
  chunks: PiiChunk[];
};

/** Решение оператора по одному вхождению или по целой группе. */
export type PiiDecisionKind = "pending" | "confirmed" | "rejected";

export type PiiDecision = {
  kind: PiiDecisionKind;
  /** Переопределение типа — применяется только когда решение адресное, не групповое. */
  typeOverride?: PiiType;
};

/** Вхождение, добавленное оператором вручную поверх выделения в документе. */
export type ManualPiiOccurrence = {
  id: string;
  type: PiiType;
  /** Текст, который оператор выделил в документе. */
  text: string;
  anchor: PiiAnchor;
};
