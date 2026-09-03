/** Состояние шага конвейера или агента. */
export type AgentState = "done" | "run" | "wait";

export type PipelineStep = {
  id: string;
  name: string;
  /** Идентификатор агента, который выполняет шаг. */
  agent: string;
  state: AgentState;
  detail: string;
  /** Затраченное время либо «—», если шаг ещё не стартовал. */
  time: string;
  /** Прогресс выполняющегося шага, 0…100. */
  progress?: number;
};

export type AgentTrace = {
  id: string;
  name: string;
  state: AgentState;
  /** Что агент получил на вход и что вернул. */
  io: string;
  time: string;
};

export type PartyRole = {
  role: string;
  value: string;
  confidence: number;
  isResolved: boolean;
};

export type LlmProvider = {
  id: string;
  name: string;
  tag: string;
  description: string;
  speed: string;
  memory: string;
};

export type AgentConfigRow = {
  id: string;
  name: string;
  agentId: string;
  description: string;
  /** Чем работает агент: правилами, моделью, OCR или гибридом. */
  engine: "правила" | "модель" | "гибрид" | "tesseract";
};
