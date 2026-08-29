"""Проверка второго рискованного места: пауза графа на уточняющих вопросах.

Пункт 4 постановки — «если данных не хватает, задаёт уточняющие вопросы» —
единственное, ради чего LangGraph здесь оправдан. Остальной пайплайн линеен
и в оркестраторе не нуждается.

Спайк доказывает четыре вещи, каждую измеримо:
  1. граф паузится и отдаёт пачку вопросов одним прерыванием, а не по одному;
  2. состояние переживает пересоздание объекта графа (durable resume) —
     значит веб-интерфейс может спросить человека и вернуться через час;
  3. ответы человека доезжают до плана маскирования;
  4. критичные реквизиты в вопросы не попадают: их маскируют молча,
     потому что recall важнее precision.

Логика узлов — заглушки. Проверяется каркас, а не детекция.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

DB = pathlib.Path(__file__).parent / "out" / "spike_checkpoints.sqlite"

CRITICAL = {"inn", "bank_account"}
ASK_BELOW = 0.75


class State(TypedDict, total=False):
    """Состояние графа. Всё, что течёт между узлами, объявлено здесь."""

    path: str
    segments: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    profiles: list[dict[str, Any]]
    questions: list[dict[str, Any]]
    answers: dict[str, str]
    plan: list[dict[str, Any]]
    artifacts: dict[str, str]


def extract(state: State) -> dict[str, Any]:
    """Разбор файла. Не нейросетевой: парсер формата, якоря на месте."""
    return {
        "segments": [
            {"order": 0, "text": 'Поставщик: АО «Триема», ИНН 3662103003', "anchor": ("docx", 0, 0)},
            {"order": 1, "text": "Директор: Иванов Иван Иванович", "anchor": ("docx", 1, 0)},
            {"order": 2, "text": "Покупатель: ООО «Вектор», тел. +7 900 123-45-67", "anchor": ("docx", 2, 0)},
        ]
    }


def detect(state: State) -> dict[str, Any]:
    """Правила с контрольными суммами, локальный NER, затем LLM-арбитр."""
    return {
        "entities": [
            {"id": "e1", "type": "inn", "text": "3662103003", "seg": 0, "conf": 1.00, "src": "rule"},
            {"id": "e2", "type": "org_name", "text": "АО «Триема»", "seg": 0, "conf": 0.93, "src": "ner"},
            {"id": "e3", "type": "person", "text": "Иванов Иван Иванович", "seg": 1, "conf": 0.61, "src": "ner"},
            {"id": "e4", "type": "org_name", "text": "ООО «Вектор»", "seg": 2, "conf": 0.95, "src": "ner"},
            {"id": "e5", "type": "phone", "text": "+7 900 123-45-67", "seg": 2, "conf": 0.55, "src": "ner"},
        ]
    }


def profile(state: State) -> dict[str, Any]:
    """Группировка сущностей в профили субъектов. Роль — свойство профиля."""
    return {
        "profiles": [
            {"id": "p1", "role": "supplier", "members": ["e1", "e2", "e3"]},
            {"id": "p2", "role": "buyer", "members": ["e4", "e5"]},
        ]
    }


def judge(state: State) -> dict[str, Any]:
    """Судья: что маскируем молча, а что выносим человеку.

    Асимметрия намеренная. Критичный реквизит с любой уверенностью маскируется
    без вопроса: пропуск ИНН — утечка, лишняя маска — косметика. Спрашиваем
    только про некритичное и только пачкой, иначе демо превращается в допрос.
    """
    questions = [
        {
            "entity_id": e["id"],
            "text": f"«{e['text']}» — это {e['type']}? Уверенность {e['conf']:.2f}",
            "options": ["да, маскировать", "нет, оставить"],
        }
        for e in state["entities"]
        if e["conf"] < ASK_BELOW and e["type"] not in CRITICAL
    ]
    return {"questions": questions}


def ask_human(state: State) -> dict[str, Any]:
    """Одно прерывание на весь список вопросов."""
    answers = interrupt({"questions": state["questions"]})
    return {"answers": answers}


def needs_human(state: State) -> str:
    return "ask_human" if state.get("questions") else "plan"


def plan(state: State) -> dict[str, Any]:
    """Сущность → маркер. Ответы человека здесь уже учтены."""
    answers = state.get("answers") or {}
    role_of = {m: p["role"] for p in state["profiles"] for m in p["members"]}
    counters: dict[str, int] = {}
    items = []
    for e in state["entities"]:
        if answers.get(e["id"]) == "нет, оставить":
            continue
        role = role_of.get(e["id"], "third_party")
        key = f"{role}:{e['type']}"
        counters[key] = counters.get(key, 0) + 1
        label = {"supplier": "ПОСТАВЩИК", "buyer": "ПОКУПАТЕЛЬ"}.get(role, "СТОРОНА")
        items.append({"entity_id": e["id"], "marker": f"[{label}-{e['type'].upper()}-{counters[key]}]"})
    return {"plan": items}


def render(state: State) -> dict[str, Any]:
    """Один план — два документа. Разница только в стиле мазка."""
    return {
        "artifacts": {
            "black": "out/masked_black.docx",
            "highlight": "out/masked_highlight.docx",
            "report": "out/report.html",
        }
    }


def build() -> StateGraph:
    g = StateGraph(State)
    for name, fn in [
        ("extract", extract), ("detect", detect), ("profile", profile),
        ("judge", judge), ("ask_human", ask_human), ("plan", plan), ("render", render),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "extract")
    g.add_edge("extract", "detect")
    g.add_edge("detect", "profile")
    g.add_edge("profile", "judge")
    g.add_conditional_edges("judge", needs_human, {"ask_human": "ask_human", "plan": "plan"})
    g.add_edge("ask_human", "plan")
    g.add_edge("plan", "render")
    g.add_edge("render", END)
    return g


def main() -> int:
    DB.parent.mkdir(exist_ok=True)
    DB.unlink(missing_ok=True)
    config = {"configurable": {"thread_id": "spike-1"}}
    checks: dict[str, bool] = {}

    # Первый прогон: доходит до вопросов и встаёт.
    with SqliteSaver.from_conn_string(str(DB)) as saver:
        graph = build().compile(checkpointer=saver)
        first = graph.invoke({"path": "contract_01.docx"}, config)

    interrupts = first.get("__interrupt__", ())
    asked = list(interrupts[0].value["questions"]) if interrupts else []
    ids = {q["entity_id"] for q in asked}

    checks["граф встал на вопросах"] = bool(interrupts)
    checks["прерывание одно на всю пачку"] = len(interrupts) == 1
    checks["вопросов ровно 2"] = len(asked) == 2
    checks["критичный ИНН не вынесен человеку"] = "e1" not in ids
    checks["спрошено про ФИО и телефон"] = ids == {"e3", "e5"}
    checks["документы ещё не собраны"] = "artifacts" not in first

    # Второй прогон: НОВЫЙ объект графа, состояние берётся из sqlite.
    with SqliteSaver.from_conn_string(str(DB)) as saver:
        graph2 = build().compile(checkpointer=saver)
        answers = {"e3": "да, маскировать", "e5": "нет, оставить"}
        final = graph2.invoke(Command(resume=answers), config)

    markers = [i["marker"] for i in final["plan"]]
    checks["возобновление после пересборки графа"] = "artifacts" in final
    checks["ответ «оставить» убрал телефон из плана"] = not any("PHONE" in m for m in markers)
    checks["ответ «маскировать» оставил ФИО"] = any("PERSON" in m for m in markers)
    checks["роль попала в маркер"] = "[ПОСТАВЩИК-INN-1]" in markers
    checks["три артефакта"] = set(final["artifacts"]) == {"black", "highlight", "report"}

    for name, ok in checks.items():
        print(f"  {'ok  ' if ok else 'ПЛОХО'}  {name}")
    print("\nмаркеры:", markers)

    passed = all(checks.values())
    print("\nСПАЙК ПРОЙДЕН" if passed else "\nСПАЙК ПРОВАЛЕН")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
