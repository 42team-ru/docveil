import type {
  AgentConfigRow,
  AgentTrace,
  LlmProvider,
  PartyRole,
  PipelineStep,
} from "./types";

export const pipelineSteps: PipelineStep[] = [
  {
    id: "p1",
    name: "Разбор файла",
    agent: "parser.pdf",
    state: "done",
    detail: "Извлечено 14 стр., 6 таблиц. Слой текста найден на 11 стр.",
    time: "00:03",
  },
  {
    id: "p2",
    name: "OCR сканов",
    agent: "ocr.tesseract-rus",
    state: "done",
    detail: "Стр. 12–14 — изображения. Распознано 3 стр., ср. уверенность 0.94.",
    time: "00:09",
  },
  {
    id: "p3",
    name: "Структура и таблицы",
    agent: "layout.builder",
    state: "done",
    detail: "Сохранены 6 таблиц, 2 приложения, порядок абзацев.",
    time: "00:04",
  },
  {
    id: "p4",
    name: "Роли сторон",
    agent: "roles.resolver",
    state: "run",
    detail:
      "Поставщик определён. Покупатель — низкая уверенность, будет уточнение.",
    time: "00:06",
    progress: 62,
  },
  {
    id: "p5",
    name: "Поиск и маскирование",
    agent: "ner.mask",
    state: "wait",
    detail: "Ожидает ответа на уточнение перед нумерацией маркеров.",
    time: "—",
  },
  {
    id: "p6",
    name: "Сборка и отчёт",
    agent: "writer.pdf",
    state: "wait",
    detail: "Вернёт PDF с подсветкой и перечень замен.",
    time: "—",
  },
];

/** Индекс выполняющегося шага для `Stepper`. */
export const activePipelineStep = pipelineSteps.findIndex(
  (step) => step.state === "run",
);

export const processingSummary = {
  document: "Договор_поставки_2026-114.pdf",
  progress: "шаг 4 из 6 · 00:22",
};

/** Строки «трассы вызовов» — как они уходят в локальный журнал. */
export const callTrace = [
  "parser.pdf            pages=14 tables=6 text_layer=11/14",
  "ocr.tesseract-rus     p12 conf=0.95  p13 conf=0.93  p14 conf=0.94",
  "layout.builder        tables preserved=6  merged_cells=14",
  "llm.local             qwen2.5-7b-q4  ctx=8192  t=612ms",
  'roles.resolver        supplier="ООО «ГрандСтройМонтаж»" conf=0.96',
  "roles.resolver        buyer=? conf=0.41 -> ask_user",
  "ner.mask              candidates=28 types=9",
  "ner.mask              blocked: awaiting clarification #1",
  "audit                 run=2 user=a.orlova",
  "peak_rss=1.8GB  no network calls",
].join("\n");

export const partyRoles: PartyRole[] = [
  {
    role: "ПОСТАВЩИК",
    value: "ООО «ГрандСтройМонтаж»",
    confidence: 0.96,
    isResolved: true,
  },
  {
    role: "ПОКУПАТЕЛЬ",
    value: "не определён",
    confidence: 0.41,
    isResolved: false,
  },
];

export const partyRolesNote =
  "В преамбуле нет явного указания. Агент задаст уточняющий вопрос на этапе проверки.";

export const agentTraces: AgentTrace[] = [
  {
    id: "a1",
    name: "Разбор файла",
    state: "done",
    io: "in: pdf 14p · out: blocks[212], tables[6]",
    time: "00:03",
  },
  {
    id: "a2",
    name: "OCR",
    state: "done",
    io: "in: img p12–14 · out: text+bbox, conf 0.94",
    time: "00:09",
  },
  {
    id: "a3",
    name: "Роли сторон",
    state: "done",
    io: "llm.extract(schema=parties) · conf 0.96 / 0.41",
    time: "00:06",
  },
  {
    id: "a4",
    name: "Поиск сущностей",
    state: "run",
    io: "regex+llm · 28 фрагментов, 9 типов",
    time: "00:11",
  },
  {
    id: "a5",
    name: "Сборка документа",
    state: "wait",
    io: "out: pdf + highlights + report.csv",
    time: "—",
  },
];

export const agentTracesNote =
  "Вызовы модели идут через единый слой. Смена GigaChat → локальная модель не меняет логику агентов.";

export const llmProviders: LlmProvider[] = [
  {
    id: "local",
    name: "Локальная модель",
    tag: "активна",
    description:
      "qwen2.5-7b-instruct-q4 через llama.cpp. Работает без сети, вся обработка на машине оператора.",
    speed: "~640 мс/запрос",
    memory: "1.8 ГБ RAM",
  },
  {
    id: "giga",
    name: "GigaChat API",
    tag: "настроено",
    description:
      "Облачный провайдер. Быстрее на длинных документах, но данные покидают контур — заблокировано строгим офлайном.",
    speed: "~310 мс/запрос",
    memory: "0.1 ГБ RAM",
  },
];

export const agentConfigRows: AgentConfigRow[] = [
  {
    id: "c1",
    name: "Разбор файла",
    agentId: "parser.*",
    description: "pdfplumber / python-docx / openpyxl. Без модели.",
    engine: "правила",
  },
  {
    id: "c2",
    name: "OCR",
    agentId: "ocr.tesseract",
    description: "Распознавание сканов, слой текста с координатами.",
    engine: "tesseract",
  },
  {
    id: "c3",
    name: "Роли сторон",
    agentId: "roles.resolver",
    description: "Определяет поставщика и покупателя по преамбуле и реквизитам.",
    engine: "модель",
  },
  {
    id: "c4",
    name: "Поиск сущностей",
    agentId: "ner.mask",
    description: "Регулярки для ИНН/счетов, модель для ФИО и организаций.",
    engine: "гибрид",
  },
  {
    id: "c5",
    name: "Контроль полноты",
    agentId: "audit.check",
    description: "Ищет пропуски и формулирует уточняющие вопросы.",
    engine: "модель",
  },
  {
    id: "c6",
    name: "Сборка",
    agentId: "writer.*",
    description: "Возвращает файл в исходном формате с подсветкой и отчёт.",
    engine: "правила",
  },
];

/** Контракт слоя вызова ИИ — то, что не меняется при смене провайдера. */
export const llmLayerContract = [
  "LLMProvider.complete(prompt) -> str",
  "LLMProvider.extract(schema)  -> json",
  "",
  "gigachat · llama.cpp · ollama · vllm",
].join("\n");
