"""Граф компиляции пользовательских типов (план T1.13, шаг 11).

`extract_sample → compile → (ask_types при исходе ask) → preview → END`.
Отдельный граф со своим чекпойнтером и своим `thread_id` — не узел основного
графа маскировки (план, раздел «Отвергнутые альтернативы»: `thread_id`
прогона маскировки иначе пришлось бы считать до того, как известны влияющие
на результат спеки).

`interrupt()` — ровно один на раунд, одним конвертом на все типы сразу,
которым в этом раунде нужен ответ (инвариант «вопросы одной пачкой»,
`AGENTS.md`). Чекпойнтер приходит снаружи, как в `graph/build.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

from masker.customtypes.compiler import (
    AskOutcome,
    CompileOutcome,
    CompilerOutcome,
    UseBuiltinOutcome,
    available_executors,
    compile_type,
)
from masker.customtypes.preview import preview
from masker.entity_types import EntityTypeRegistry
from masker.ingest.docx_ingest import ingest_docx
from masker.ingest.pdf_ingest import ingest_pdf
from masker.llm import LLMProvider
from masker.model import Anchor, Document, Segment
from masker.typeconfig import load_type_config

#: Версия конверта вопросов/ответов этого графа — независима от
#: `masker.graph.questions.SCHEMA_VERSION` (тот же приём, другое прерывание).
SCHEMA_VERSION = 1

CheckpointerFactory = Callable[[], AbstractContextManager[BaseCheckpointSaver[str]]]

__all__ = [
    "SCHEMA_VERSION",
    "CheckpointerFactory",
    "CompileAlreadyFinishedError",
    "CompileDeps",
    "CompileRunOutcome",
    "CompileState",
    "UnknownCompileThreadError",
    "build_graph",
    "compile_graph",
    "resume_compile",
    "start_compile",
]


class CompileState(TypedDict, total=False):
    """JSON-совместимое состояние графа компиляции — единственное, что живёт
    в чекпойнтере (никаких `re.Pattern`/датаклассов, та же причина, что у
    `RunOptions.custom_types`)."""

    #: Путь к локальному файлу документа — заполняет вызывающий (сервис
    #: скачивает объект из MinIO во временный файл перед стартом).
    path: str
    #: Описания типов словами, по одному на элемент — вход сессии.
    descriptions: list[str]
    #: Сегменты документа в формате `graph.nodes._document` — заполняет
    #: `extract_sample_node`.
    segments: list[dict[str, Any]]
    #: Номер текущего раунда уточнения, общий на всю сессию (design notes,
    #: вопрос 4): растёт только когда хотя бы один тип спросил `ask`.
    round: int
    #: Рабочее состояние на каждое описание — см. докстринг `_apply_outcome`.
    items: list[dict[str, Any]]
    #: Ответы последнего раунда — для отладки и для `answers` в исходе.
    answers: dict[str, str]


@dataclass(frozen=True, slots=True)
class CompileDeps:
    """Внешние зависимости узлов графа компиляции — провайдер LLM и его id
    для ключа кэша (`compiler.compile_type`)."""

    llm: LLMProvider
    model_id: str = ""


class UnknownCompileThreadError(Exception):
    """Тред компиляции с таким `thread_id` не существует в чекпойнтере."""


class CompileAlreadyFinishedError(Exception):
    """Компиляция уже завершена; повторные ответы не приняты."""


@dataclass(frozen=True, slots=True)
class CompileRunOutcome:
    """Единый результат `start_compile`/`resume_compile`."""

    status: Literal["waiting", "done"]
    thread_id: str
    payload: dict[str, Any] | None
    state: dict[str, Any] = field(default_factory=dict)


def _document(state: CompileState) -> Document:
    return Document(
        path=state.get("path", ""),
        fmt="docx",
        segments=[
            Segment(
                str(item["text"]),
                Anchor(
                    str(item["anchor"]["fmt"]),
                    tuple(item["anchor"]["locator"]),
                    str(item["anchor"].get("label", "")),
                ),
                int(item["order"]),
            )
            for item in state.get("segments", [])
        ],
    )


def extract_sample_node(state: CompileState) -> dict[str, object]:
    """Разобрать документ и завести рабочий элемент на каждое описание."""
    path = Path(state["path"])
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        document = ingest_docx(path)
    elif suffix == ".pdf":
        document = ingest_pdf(path)
    else:
        raise ValueError(f"неподдерживаемый формат файла: {path.name}")

    segments = [
        {
            "text": segment.text,
            "anchor": {
                "fmt": segment.anchor.fmt,
                "locator": list(segment.anchor.locator),
                "label": segment.anchor.label,
            },
            "order": segment.order,
        }
        for segment in document.segments
    ]
    items = [
        {"index": index, "description": description, "status": "pending", "feedback": ""}
        for index, description in enumerate(state.get("descriptions", []))
    ]
    return {"segments": segments, "items": items, "round": 1}


def _apply_outcome(item: dict[str, Any], outcome: CompilerOutcome) -> None:
    """Записать исход компилятора в рабочий элемент — поля зависят от вида исхода:

    - `use_builtin`: `outcome_kind`, `type_id`, `marker_override`;
    - `compile`: `outcome_kind`, `spec` (сырой JSON для `load_type_config`);
    - `ask`: `question`, `options`, `target`, статус `"asking"`;
    - `cannot_compile`: `reason`, статус `"failed"`.
    """
    if isinstance(outcome, UseBuiltinOutcome):
        item["status"] = "compiled"
        item["outcome_kind"] = "use_builtin"
        item["type_id"] = outcome.type_id
        item["marker_override"] = outcome.marker_override
    elif isinstance(outcome, CompileOutcome):
        item["status"] = "compiled"
        item["outcome_kind"] = "compile"
        item["spec"] = outcome.spec
    elif isinstance(outcome, AskOutcome):
        item["status"] = "asking"
        item["question"] = outcome.question
        item["options"] = outcome.options
        item["target"] = outcome.target
    else:
        item["status"] = "failed"
        item["reason"] = outcome.reason


def make_compile_node(deps: CompileDeps) -> Callable[[CompileState], dict[str, object]]:
    def compile_node(state: CompileState) -> dict[str, object]:
        registry = EntityTypeRegistry.builtin()
        executors = available_executors()
        round_index = state.get("round", 1)
        items = [dict(item) for item in state.get("items", [])]
        for item in items:
            if item["status"] != "pending":
                continue
            outcome = compile_type(
                str(item["description"]),
                llm=deps.llm,
                registry=registry,
                executors=executors,
                feedback=str(item.get("feedback", "")),
                round_index=round_index,
                model_id=deps.model_id,
            )
            _apply_outcome(item, outcome)
        return {"items": items}

    return compile_node


def needs_ask(state: CompileState) -> str:
    """Пойти на `ask_types`, только если хотя бы один тип реально спрашивает."""
    if any(item.get("status") == "asking" for item in state.get("items", [])):
        return "ask_types"
    return "preview"


def _question_id(item: dict[str, Any]) -> str:
    return f"CT-{item['index']}"


def _ask_payload(state: CompileState) -> dict[str, Any]:
    items = state.get("items", [])
    questions = [
        {
            "id": _question_id(item),
            "text": item.get("question", ""),
            "options": item.get("options", []),
            "target": item.get("target", ""),
        }
        for item in items
        if item.get("status") == "asking"
    ]
    return {"schema_version": SCHEMA_VERSION, "questions": questions}


def _parse_answer_envelope(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"неверный конверт ответов компиляции: ожидалась schema_version={SCHEMA_VERSION}"
        )
    answers = raw.get("answers", {})
    if not isinstance(answers, dict):
        raise ValueError("конверт ответов компиляции: 'answers' должен быть объектом")
    return {str(key): value for key, value in answers.items() if isinstance(value, str)}


def ask_types_node(state: CompileState) -> dict[str, object]:
    """Ровно один `interrupt()` на раунд, одним конвертом на все спрашивающие типы."""
    answers = _parse_answer_envelope(interrupt(_ask_payload(state)))
    items = [dict(item) for item in state.get("items", [])]
    for item in items:
        if item.get("status") != "asking":
            continue
        item["feedback"] = answers.get(_question_id(item), "")
        item["status"] = "pending"
        item.pop("question", None)
        item.pop("options", None)
        item.pop("target", None)
    return {"items": items, "round": state.get("round", 1) + 1, "answers": answers}


def _preview_to_dict(result: Any) -> dict[str, Any]:
    return {
        "segments": [
            {
                "segment_order": segment.segment_order,
                "anchor_label": segment.anchor_label,
                "text": segment.text,
                "matches": [
                    {"start": match.start, "end": match.end, "value": match.value}
                    for match in segment.matches
                ],
            }
            for segment in result.segments
        ],
        "total_matches": result.total_matches,
    }


def preview_node(state: CompileState) -> dict[str, object]:
    """Прогнать live preview (шаг 10) по всем `compile`-исходам; `use_builtin` без preview."""
    document = _document(state)
    items = [dict(item) for item in state.get("items", [])]
    for item in items:
        if item.get("status") != "compiled":
            continue
        if item.get("outcome_kind") != "compile":
            item["preview"] = None
            continue
        spec = load_type_config({"version": 1, "types": [item["spec"]]})[0]
        item["preview"] = _preview_to_dict(preview(spec, document))
    return {"items": items}


def build_graph(deps: CompileDeps) -> StateGraph[CompileState]:
    graph: StateGraph[CompileState] = StateGraph(CompileState)
    graph.add_node("extract_sample", extract_sample_node)
    graph.add_node("compile", make_compile_node(deps))  # type: ignore[arg-type]
    graph.add_node("ask_types", ask_types_node)
    graph.add_node("preview", preview_node)

    graph.add_edge(START, "extract_sample")
    graph.add_edge("extract_sample", "compile")
    graph.add_conditional_edges(
        "compile", needs_ask, {"ask_types": "ask_types", "preview": "preview"}
    )
    graph.add_edge("ask_types", "compile")
    graph.add_edge("preview", END)
    return graph


def compile_graph(
    deps: CompileDeps, checkpointer: BaseCheckpointSaver[str]
) -> CompiledStateGraph[CompileState, None, CompileState, CompileState]:
    """Скомпилировать граф с внешним чекпойнтером — основа durable resume."""
    return build_graph(deps).compile(checkpointer=checkpointer)


def _config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


def _outcome_from_result(thread_id: str, result: dict[str, Any]) -> CompileRunOutcome:
    interrupts = result.get("__interrupt__", ())
    if interrupts:
        return CompileRunOutcome("waiting", thread_id, dict(interrupts[0].value), dict(result))
    return CompileRunOutcome("done", thread_id, None, dict(result))


def start_compile(
    path: str | Path,
    descriptions: Sequence[str],
    *,
    thread_id: str,
    checkpointer_factory: CheckpointerFactory,
    deps: CompileDeps,
) -> CompileRunOutcome:
    """Начать сессию компиляции под явно заданным `thread_id`.

    В отличие от `masker.run.start_run`, `thread_id` не выводится из
    содержимого — его назначает вызывающий (сервис, шаг 12) на каждый
    `POST /custom_types/compile`: сессия компиляции разовая, а не
    идемпотентный прогон по документу и опциям.
    """
    with checkpointer_factory() as saver:
        graph = compile_graph(deps, saver)
        config = _config(thread_id)
        initial: CompileState = {"path": str(path), "descriptions": list(descriptions)}
        result = graph.invoke(initial, config)
        return _outcome_from_result(thread_id, result)


def resume_compile(
    thread_id: str,
    answers: dict[str, str],
    *,
    checkpointer_factory: CheckpointerFactory,
    deps: CompileDeps,
) -> CompileRunOutcome:
    """Прислать ответы на приостановленную сессию компиляции."""
    with checkpointer_factory() as saver:
        graph = compile_graph(deps, saver)
        config = _config(thread_id)
        snapshot = graph.get_state(config)
        if snapshot.created_at is None:
            raise UnknownCompileThreadError(f"неизвестный thread_id компиляции: {thread_id!r}")
        if not snapshot.interrupts:
            raise CompileAlreadyFinishedError(f"компиляция {thread_id!r} уже завершена")

        resume_value = {"schema_version": SCHEMA_VERSION, "answers": dict(answers)}
        result = graph.invoke(Command(resume=resume_value), config)
        return _outcome_from_result(thread_id, result)
