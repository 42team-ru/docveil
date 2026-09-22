/**
 * Формат документа, из которого извлечены ПДн.
 *
 * Картиночные форматы (`jpg`/`jpeg`/`png`/`tif`/`tiff`) — сканы, которые
 * движок разбирает через OCR (`masker.ingest.SUPPORTED_SUFFIXES`); внутри
 * графа документ живёт как одностраничный PDF, поэтому `report.format` для
 * них всегда `"pdf"` — этот тип описывает формат исходного/артефактного
 * файла, а не внутреннее представление движка.
 */
export type PiiDocFormat =
  | "docx"
  | "pdf"
  | "xlsx"
  | "jpg"
  | "jpeg"
  | "png"
  | "tif"
  | "tiff";

/**
 * Категория данных, которую распознаёт движок.
 *
 * Идентификаторы обязаны совпадать с `EntityType` бэкенда
 * (`backend/src/masker/model.py`) буква в букву: по ним же движок собирает
 * маркер, который вписан в документ, поэтому расхождение видно не в типах, а
 * в файле у оператора.
 *
 * `money` и `bank_name` объявлены в реестре бэкенда, но детектора у них пока
 * нет — тип известен, замен по нему не будет.
 */
export type PiiType =
  | "org_name"
  | "person"
  | "inn"
  | "kpp"
  | "ogrn"
  | "snils"
  | "bank_account"
  | "bik"
  | "bank_name"
  | "address"
  | "phone"
  | "email"
  | "passport"
  | "contract_number"
  | "money"
  | "date"
  | "birth_date"
  | "site"
  | "federal_law"
  | "contract_amount"
  | "delivery_period"
  | "payment_terms"
  | "signature";

/**
 * Слой детекции, выдавший сущность (`Source` в `model.py`).
 *
 * `llm` — арбитр, `user` — пользовательский детектор из custom types, `block` —
 * структурный признак (блок реквизитов или подписной, план Р6). Схлопывать их в
 * `rule` нельзя: оператор перестаёт отличать правило с контрольной суммой от
 * решения модели.
 */
export type PiiSource = "rule" | "ner" | "llm" | "user" | "block" | "cv" | "ml";

/** Решение движка по сущности (`Action` в `model.py`). */
export type EntityAction = "mask" | "keep" | "ask";

/**
 * Уровень уверенности детекции (`ConfidenceLevel` в `model.py`, план Р8).
 *
 * `confirmed` — контрольная сумма реквизита либо ≥2 независимых сигналов;
 * `probable` — один сигнал (морфология, структура, локальная NER);
 * `possible` — заглавное имя собственное вне белого списка, без
 * подтверждения — именно эти группы попадают в `report.review_possible`,
 * чтобы оператор мог снять с них маску одним кликом.
 */
export type ConfidenceLevel = "confirmed" | "probable" | "possible";

/**
 * Кто принял решение (`DecisionSource` в `model.py`), от самого частного к
 * самому общему. `critical_guard` стоит над всем остальным.
 */
export type DecisionSource =
  | "critical_guard"
  | "entity"
  | "profile"
  | "type"
  | "judge"
  | "default";

/** Адресация фрагмента в объектную модель документа. */
export type PiiAnchor = {
  format: PiiDocFormat;
  /** Человекочитаемая метка для отладки и отчётов, напр. «абзац 19». */
  label: string;
  /**
   * Путь до узла документа. Формы задаёт ingest бэкенда:
   * docx — `["body", N]` либо `["table", tbl, row, cell, para]`,
   * xlsx — `["sheet", имя, row, col]`,
   * pdf (текстовый слой) — `["page", N, charStart, charEnd]`,
   * pdf (скан/картинка, OCR-сегмент) — `["page", N, "ocr", x0, y0, x1, y1]`,
   * pdf (bbox-правка оператора) — `["page", N, "user", x0, y0, x1, y1]`
   * (координаты в pt×100 — `masker.ingest.scan_ingest`/`masker.graph.nodes`).
   * Разбирают его резолверы привязки, не эта модель.
   */
  locator: (string | number)[];
};

/**
 * Прямоугольная область сущности на странице готового PDF-артефакта,
 * координаты нормализованы 0..1 (`masker.highlights`, план
 * feat/highlight-coords-edits). Работает и для картинки: `render/
 * image_export.py::pdf_to_image` рендерит страницу целиком без полей и
 * обрезки, значит те же координаты ложатся на итоговый JPEG/PNG один в один.
 */
export type PiiRegion = {
  /** 0-based. */
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
};

/** Размеры одной страницы готового артефакта в pt — `report.pages[]`. */
export type PiiPage = {
  page: number;
  widthPt: number;
  heightPt: number;
};

/** Одно найденное вхождение ПДн внутри чанка. */
export type PiiOccurrence = {
  /** Ссылка на сущность в рамках документа, напр. "E1". */
  ref: string;
  /** Группа: все вхождения одной и той же сущности по документу. */
  groupId: string;
  /** Маркер, уже вписанный в маскированный документ, напр. "[ФИО-1]". */
  marker: string;
  /** Решение, уже применённое в опубликованном результате. */
  action: EntityAction | null;
  type: PiiType;
  /**
   * Исходный текст ПДн до маскирования. В промаскированном docx его больше нет —
   * это чисто справочное поле из JSON для отображения оператору в панели.
   */
  text: string;
  normalized: string;
  confidence: number;
  /** Категориальный уровень уверенности — см. `ConfidenceLevel`. */
  level: ConfidenceLevel;
  source: PiiSource;
  segmentOrder: number;
  /** Смещения в пределах chunk.text — только для отчётности, не для поиска в DOM. */
  chunkStart: number;
  chunkEnd: number;
  /**
   * Bbox-координаты на странице готового артефакта — пусто для docx/xlsx
   * (там нет PDF-рендера) и для форматов без плана замен. Одна сущность на
   * одной странице — один регион; перенос через страницу даёт две записи.
   */
  regions: PiiRegion[];
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

/** Решение оператора — в отличие от `EntityAction`, это правка человека, не движка. */
export type OperatorDecision = {
  kind: PiiDecisionKind;
  /** Переопределение типа — применяется только когда решение адресное, не групповое. */
  typeOverride?: PiiType;
};

/** Вхождение, добавленное оператором вручную поверх выделения в документе. */
/**
 * Ровно одно из `anchor`/`region` заполнено — по тому, как оператор указал
 * место: выделением текста (docx/xlsx) или рамкой на превью (pdf/картинка).
 * С `region` сервер не ищет текст на странице — на сканах OCR может
 * распознать не то, что видит человек (`ManualEntityIn.region` бэкенда).
 */
export type ManualPiiOccurrence = {
  id: string;
  type: PiiType;
  /** Текст значения: цитата выделения либо то, что оператор напечатал сам. */
  text: string;
  anchor?: PiiAnchor;
  region?: PiiRegion;
};

/* ------------------------------------------------------------------ *
 * Полный отчёт движка (`report.json`, `report_version: 3`).
 *
 * Формы ниже сняты с настоящей выдачи `masker.cli`, поле в поле; источник —
 * `backend/src/masker/report/payload.py` и `backend/src/masker/graph/serde.py`.
 * До этого фронт разбирал только `chunk_count` + `chunks`, а всё остальное
 * подделывал фикстурами по экранам — отсюда и расхождение цифр между панелью
 * проверки и отчётом.
 * ------------------------------------------------------------------ */

/** Сводка по документу — `report.summary`. */
export type ReportSummary = {
  entitiesTotal: number;
  /** Сколько найдено по каждому типу; ключ — `PiiType`. */
  byType: Record<string, number>;
  /** Сколько найдено каждым слоем детекции; ключ — `PiiSource`. */
  bySource: Record<string, number>;
  /** Сколько сущностей на каждом уровне уверенности; ключ — `ConfidenceLevel`. */
  byLevel: Record<string, number>;
  /** Самая низкая уверенность по документу; `null`, когда сущностей нет. */
  minimumConfidence: number | null;
};

/**
 * Группа замен — `report.plan.groups[]`. Это настоящий источник группы и
 * маркера: одна сущность во всём документе получает один `marker`, собранный
 * от профиля и роли (`[ЗАКАЗЧИК-ИНН]`), а не от одного лишь типа.
 */
export type MaskGroupRecord = {
  id: string;
  marker: string;
  type: PiiType;
  /** Русская подпись типа от движка: «Организация», «Банковский счёт». */
  typeTitle: string;
  /** Профиль-владелец группы; пустая строка — сущность вне профилей. */
  profileId: string;
  refCount: number;
  /** Одно значение из группы, чтобы показать оператору, о чём речь. */
  sample: string;
  /**
   * Р8 — лучший (самый уверенный) уровень среди ссылок группы; пустая
   * строка — ни для одной ссылки уровень не известен report'у.
   */
  level: ConfidenceLevel | "";
};

/** Пропущенные ссылки — `report.plan.skipped`. */
export type MaskPlanSkipped = {
  count: number;
  /** Причина → сколько: `type_not_requested`, `kept`, `no_anchor`. */
  byReason: Record<string, number>;
};

/** План замен — `report.plan`. */
export type MaskPlanRecord = {
  requestedTypes: PiiType[];
  groups: MaskGroupRecord[];
  skipped: MaskPlanSkipped;
};

/** Член профиля — `report.profile_judge.profiles[].members[]`. */
export type PartyProfileMember = {
  ref: string;
  type: PiiType;
  text: string;
  normalized: string;
  confidence: number;
  source: PiiSource;
  anchor: PiiAnchor;
};

/**
 * Профиль стороны — `report.profile_judge.profiles[]`. Роли открытые: в
 * `roleTitle` попадает формулировка из документа («Заказчик», «Исполнитель»),
 * а не значение закрытого перечисления.
 */
export type PartyProfile = {
  id: string;
  /** Роль как в документе; пустая строка — роль не распознана. */
  roleTitle: string;
  roleId: string;
  /** Роль в маркере: `ЗАКАЗЧИК`, либо `СТОРОНА-N` для нераспознанной. */
  markerLabel: string;
  confidence: number;
  roleConfidence: number;
  source: PiiSource;
  /** Чем подтверждена роль — «метка: заказчик». */
  evidence: string[];
  members: PartyProfileMember[];
};

/** Сторона в карточке договора — `report.contract_summary.customer` / `.supplier`. */
export type ContractParty = {
  name: string | null;
  roleTitle: string | null;
  inn: string | null;
  ogrn: string | null;
};

/**
 * Карточка договора — `report.contract_summary`. Движок собирает её
 * детерминированно из уже найденных сущностей и профилей, без вызова LLM.
 */
export type ContractSummary = {
  customer: ContractParty | null;
  supplier: ContractParty | null;
  federalLaw: string[];
  contractAmount: string | null;
  deliveryPeriods: string[];
  paymentTerms: string | null;
  contractNumber: string | null;
  generatedAt: string;
  llmCalls: number;
  briefSummary: string | null;
  documentKind: {
    status: "contract" | "non_contract" | "unknown";
    genre: string | null;
  };
};

export type Telemetry = {
  events: { sequence: number; node: string; message: string }[];
  llm: {
    calls: number;
    promptTokens: number;
    completionTokens: number;
    status: string;
    message: string;
    cost: Record<string, unknown> | null;
    byNode: { node: string; calls: number; promptTokens: number; completionTokens: number }[];
    /** Тариф активного на момент прогона профиля — `{prompt_per_1k, completion_per_1k, currency, verified_at}`,
     * `null` если не задан. Форма — `LLMPricing.as_dict()` бэкенда. */
    pricing: Record<string, unknown> | null;
  };
  runtime: { available: boolean; note: string };
};

/** Решение движка по одной ссылке — `report.decisions.by_ref[]`. */
export type RefDecision = {
  ref: string;
  action: EntityAction;
  decidedBy: DecisionSource;
  questionId: string;
  reason: string;
};

/** Снятие маски с критичного типа — `report.decisions.critical_unmasked[]`. */
export type CriticalUnmasked = {
  questionId: string;
  kind: string;
  target: string;
  count: number;
};

/**
 * Решения движка — `report.decisions`. `mode` показывает, спрашивали ли
 * человека: `non_interactive` значит, что все ответы взяты по умолчанию.
 */
export type ReportDecisions = {
  mode: "interactive" | "non_interactive" | "unknown";
  threadId: string;
  byRef: RefDecision[];
  /** Пусто — ни одна маска с критичного типа не снята. */
  criticalUnmasked: CriticalUnmasked[];
  diagnostics: string[];
};

/** Один пункт сертификата обезличивания — `certificate.checks[]` (план М3). */
export type CertificateCheck = {
  name: string;
  ok: boolean;
  detail: string;
};

/**
 * Сертификат обезличивания — `report.certificate` / `report.validation.certificate`
 * (тот же объект продублирован на верхнем уровне report.json, план М3).
 */
export type Certificate = {
  ok: boolean;
  checks: CertificateCheck[];
};

/** Итог проверки на утечки — `report.validation`. */
export type ValidationSummary = {
  status: string;
  ok: boolean;
  leakedCount: number;
  residualCount: number;
  checkedArtifacts: string[];
  certificate: Certificate | null;
};

/** Строка легенды сокращений маркера — `report.marker_legend[]` (план М1, правило 6). */
export type MarkerLegendItem = {
  shownLabel: string;
  canonicalLabel: string;
  pages: number[];
};

/** Какие запрошенные типы движок искать не умеет — `report.detection_coverage`. */
export type DetectionCoverage = {
  requestedTypes: PiiType[];
  activeDetectorTypes: PiiType[];
  /** Запрошено, но детектора нет: сейчас это `bank_name` и `money`. */
  requestedWithoutDetector: PiiType[];
};

/** Весь `report.json` в форме, которой пользуется интерфейс. */
export type MaskingReport = {
  reportVersion: number;
  /** Имя исходного файла — `contract_08_roles.docx`. */
  input: string;
  format: PiiDocFormat;
  selectedTypes: PiiType[];
  entityCount: number;
  extraction: PiiExtraction;
  summary: ReportSummary;
  plan: MaskPlanRecord | null;
  /** Р8, «снять одним кликом» — группы уровня `possible`; пусто без плана. */
  reviewPossible: MaskGroupRecord[];
  profiles: PartyProfile[];
  contractSummary: ContractSummary | null;
  decisions: ReportDecisions | null;
  validation: ValidationSummary | null;
  /** Дубль `validation.certificate` на верхнем уровне report.json (план М3). */
  certificate: Certificate | null;
  telemetry: Telemetry | null;
  markerLegend: MarkerLegendItem[];
  detectionCoverage: DetectionCoverage;
  /** Чего движок заведомо не покрывает — показывается оператору дословно. */
  limitations: string[];
  /**
   * `report.document_coverage` проходит без разбора: его форма зависит от
   * формата (у PDF нет ключа `tables`), а интерфейсу пока нужен только факт
   * наличия. Придумать здесь общую структуру — значит соврать про один из
   * форматов.
   */
  documentCoverage: Record<string, unknown>;
  /**
   * Размеры страниц готового PDF-артефакта — пусто для docx/xlsx. Вьюер
   * сопоставляет `page` здесь с `page` в `PiiOccurrence.regions`, больше
   * никакого маппинга ему не нужно.
   */
  pages: PiiPage[];
};

/* ------------------------------------------------------------------ *
 * Вопросы оператору — конверт паузы графа (`questions.json`).
 * Источник: `backend/src/masker/graph/questions.py`. Это отдельный артефакт,
 * не часть `report.json`: он появляется, когда прогон встал на `ask_human`.
 * ------------------------------------------------------------------ */

/**
 * Варианты ответа. Движок принимает ровно эти строки
 * (`backend/src/masker/model.py:177-181`); любая другая молча заменяется на
 * `default`, то есть на «маскировать».
 */
export const MASK_OPTION = "маскировать";
export const KEEP_OPTION = "оставить";
/** Снятие маски с критичного типа — отдельный вариант, а не обычное «оставить». */
export const KEEP_CRITICAL_OPTION = "оставить (осознанное решение)";

export type AnswerOption =
  | typeof MASK_OPTION
  | typeof KEEP_OPTION
  | typeof KEEP_CRITICAL_OPTION;

/**
 * Вопрос оператору. `kind` задаёт уровень решения: `type` — весь класс
 * («маскировать все телефоны?»), `profile` — реквизиты одной стороны,
 * `entity` — конкретная сущность, в которой сомневается судья.
 */
export type PolicyQuestion = {
  id: string;
  kind: "type" | "profile" | "entity";
  /** Адресат вопроса: идентификатор типа (`inn`) или профиля (`P1`). */
  target: string;
  title: string;
  prompt: string;
  /**
   * Что разрешено ответить. У критичного типа без флага прогона
   * `--unmask-critical` здесь остаётся единственный вариант «маскировать» —
   * это и есть двойное подтверждение со стороны движка.
   */
  options: AnswerOption[];
  default: AnswerOption;
  critical: boolean;
  /** Сколько сущностей затрагивает ответ. */
  found: number;
  samples: string[];
  /** Метки мест в документе — строки вида «абзац 5», а не объекты-якоря. */
  anchors: string[];
};

/** Конверт паузы целиком. */
export type AskEnvelope = {
  schemaVersion: number;
  threadId: string;
  document: { name: string; format: PiiDocFormat };
  questions: PolicyQuestion[];
};

/**
 * Конверт ответа — то, что движок ждёт обратно при `--resume`. Ключи в
 * snake_case намеренно: он уходит наружу как есть, а не живёт внутри UI.
 */
export type AnswerEnvelope = {
  schema_version: number;
  answers: Record<string, AnswerOption>;
};
