"""Сборка StateGraph, чекпойнтер, durable resume — раздел 6 плана T1.5.1.

Все тесты работают на ``tmp_path`` с ``SqliteSaver.from_conn_string`` и не
ходят в сеть: профили в ``contract_01.docx`` собираются структурно (см.
``test_profile_judge.py``), ``RunDeps()`` без LLM хватает почти везде;
``FakeProvider`` нужен только там, где требуется вопрос вида "entity" —
все реальные сущности фикстуры уверенно детектируются (>= 0.8), порог
судьи (0.75) естественным путём не пробивается.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from masker.detect.agent import DetectAgent
from masker.graph.build import compile_graph
from masker.graph.nodes import RunDeps
from masker.graph.serde import plan_from_dict
from masker.llm.base import Message
from masker.model import EntityType

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"
#: Только для теста конверта вопросов: в `contract_02_hard.docx` есть профиль
#: без структурно подтверждённой роли, поэтому после И2-3 ProfileAgent
#: действительно зовёт модель. Остальные тесты файла рассчитаны на
#: `contract_01.docx` (там есть phone, на котором проверяется отказ от типа),
#: поэтому общая фикстура остаётся прежней.
OPEN_ROLE_FIXTURE = ROOT / "fixtures" / "labeled" / "contract_02_hard.docx"

#: В contract_02_hard.docx есть профиль без структурно подтверждённой роли,
#: поэтому после И2-3 ProfileAgent действительно вызывает LLM. Кандидат
#: ``money`` в свободном заголовке даёт вопрос ``entity`` детерминированно.
_CANDIDATE_RESPONSE = (
    '{"profiles": [], "candidates": ['
    '{"segment_order": 0, "text": "АКТ", "type": "money", "confidence": 0.6}'
    "]}"
)


class _RoutingProvider:
    """Отвечает по СОДЕРЖАНИЮ запроса, а не по порядку вызовов.

    После Р7-1 в графе два независимых потребителя модели: верификатор
    в ``detect_node`` и судья в ``profile_node``. ``FakeProvider`` со
    списком ответов раздаёт их по очереди, поэтому единственный
    заготовленный ответ забирал тот, кто позвал первым, — тест ловил не
    свой дефект. Верификатор здесь не выключен: он получает пустой, но
    валидный по контракту ответ, и вопрос "entity" по-прежнему рождается
    из ответа судьи.
    """

    def __init__(self, decision: str) -> None:
        self._decision = decision
        self.calls = 0
        self.verifier_calls = 0

    def complete(self, messages: list[Message], *, schema: dict[str, Any] | None = None) -> str:
        del schema
        self.calls += 1
        # Запрос верификатора — это payload вида {"windows": [...]},
        # запрос судьи — {"profiles": [...], ...}. Разбирать промпт целиком
        # не нужно: ключ верхнего уровня однозначен.
        if any('"windows"' in message.content for message in messages):
            self.verifier_calls += 1
            return '{"windows": []}'
        return self._decision


def _options(*, interactive: bool, thread_id: str = "t1") -> dict[str, object]:
    return {
        "types": None,
        "rules_only": False,
        "interactive": interactive,
        "unmask_critical": False,
        "thread_id": thread_id,
    }


def _initial_state(
    *, interactive: bool, thread_id: str = "t1", source: Path = FIXTURE
) -> dict[str, object]:
    return {"path": str(source), "options": _options(interactive=interactive, thread_id=thread_id)}


def test_interactive_run_pauses_with_one_interrupt_before_finalize(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(), saver)
        first = graph.invoke(_initial_state(interactive=True), config)

    interrupts = first.get("__interrupt__", ())
    assert len(interrupts) == 1
    assert "final_actions" not in first


def test_envelope_has_type_profile_and_entity_questions(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        provider = _RoutingProvider(_CANDIDATE_RESPONSE)
        graph = compile_graph(RunDeps(llm=provider), saver)
        # `contract_01` даёт окно верификатора, но роли в нём уже уверенно
        # собраны структурно; отдельный запуск нужен именно после И2-3.
        graph.invoke(
            _initial_state(interactive=True, thread_id="verifier"),
            {"configurable": {"thread_id": "verifier"}},
        )
        first = graph.invoke(_initial_state(interactive=True, source=OPEN_ROLE_FIXTURE), config)

    payload = first["__interrupt__"][0].value
    kinds = {question["kind"] for question in payload["questions"]}
    assert "type" in kinds
    assert "profile" in kinds
    assert "entity" in kinds
    # Верификатор в графе жив (Р7-1) — тест обязан падать, если его отключат.
    assert provider.verifier_calls > 0


def test_durable_resume_survives_new_graph_and_saver_objects(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(), saver)
        first = graph.invoke(_initial_state(interactive=True), config)

    payload = first["__interrupt__"][0].value
    answers = {question["id"]: question["default"] for question in payload["questions"]}
    # Конверт, не голый словарь: пустой/«плоский» resume-словарь без
    # обёртки трактуется langgraph как отсутствие значения (см. run.py).
    resume_value = {"schema_version": payload["schema_version"], "answers": answers}

    # Новый объект графа и новый SqliteSaver на том же файле — не тот же процесс.
    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(artifact_dir=tmp_path / "artifacts"), saver)
        final = graph.invoke(Command(resume=resume_value), config)

    assert "__interrupt__" not in final
    assert final["final_actions"]
    assert {item["ref"] for item in final["final_actions"]}


def test_get_state_returns_same_envelope_without_re_running_nodes(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    calls = 0
    original_detect = DetectAgent.detect

    def counting_detect(self: DetectAgent, document: object) -> object:
        nonlocal calls
        calls += 1
        return original_detect(self, document)  # type: ignore[arg-type]

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(), saver)
        first = graph.invoke(_initial_state(interactive=True), config)
    assert calls == 0  # детектор ещё не подменён — считаем честно с этой точки

    DetectAgent.detect = counting_detect  # type: ignore[method-assign]
    try:
        with SqliteSaver.from_conn_string(str(db)) as saver:
            graph = compile_graph(RunDeps(), saver)
            snapshot = graph.get_state(config)
    finally:
        DetectAgent.detect = original_detect  # type: ignore[method-assign]

    assert calls == 0
    assert len(snapshot.interrupts) == 1
    assert snapshot.interrupts[0].value == first["__interrupt__"][0].value


def test_non_interactive_run_finishes_in_one_invoke_without_interrupt(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(artifact_dir=tmp_path / "artifacts"), saver)
        result = graph.invoke(_initial_state(interactive=False), config)

    assert "__interrupt__" not in result
    assert result["final_actions"]
    # Никто не спрашивал ни про тип, ни про профиль, ни про сущность — только
    # уверенность судьи и защита критичных типов могли повлиять на решение.
    decided_by = {item["decided_by"] for item in result["final_actions"]}
    assert decided_by <= {"judge", "default", "critical_guard"}
    assert decided_by & {"entity", "profile", "type"} == set()


def test_delete_thread_and_rerun_is_deterministic(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(artifact_dir=tmp_path / "artifacts"), saver)
        first = graph.invoke(_initial_state(interactive=False), config)

    with SqliteSaver.from_conn_string(str(db)) as saver:
        saver.delete_thread("t1")
        graph = compile_graph(RunDeps(artifact_dir=tmp_path / "artifacts"), saver)
        second = graph.invoke(_initial_state(interactive=False), config)

    assert first["final_actions"] == second["final_actions"]


@pytest.mark.parametrize("thread_id", ["unknown-thread"])
def test_get_state_of_unknown_thread_has_no_interrupts(tmp_path: Path, thread_id: str) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": thread_id}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(), saver)
        snapshot = graph.get_state(config)

    assert snapshot.interrupts == ()
    assert snapshot.created_at is None


def test_plan_node_applies_final_actions_kept_type_stays_out_but_critical_stays_in(
    tmp_path: Path,
) -> None:
    """T1.10, шаг 4: ``plan`` строится из ``final_actions``, не из «маскировать всё».

    ``profile: False`` (T1.10, шаг 3) убирает привязку сущностей к профилям —
    иначе решение уровня «профиль» (по умолчанию «маскировать», раз вопрос не
    задан персонально) перебило бы ответ на вопрос о типе (раздел 4 плана
    T1.5.1: PROFILE сильнее TYPE), и тест перестал бы проверять именно
    применение ответа на тип. ``TYPE-inn`` отвечен тем же «оставить», но ИНН
    критичен: единственный доступный вариант для него — «маскировать»,
    неверный ответ откатывается на умолчание — так проверяется, что
    ``critical_guard`` не обойдён ответом человека.
    """
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t-plan"}}
    initial_state = _initial_state(interactive=True, thread_id="t-plan")
    initial_state["options"]["profile"] = False
    initial_state["answers"] = {"TYPE-phone": "оставить", "TYPE-inn": "оставить"}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(artifact_dir=tmp_path / "artifacts"), saver)
        result = graph.invoke(initial_state, config)

    assert "__interrupt__" not in result
    plan = plan_from_dict(result["plan"])

    phone_skipped = [item for item in plan.skipped if item.type == EntityType.PHONE]
    assert phone_skipped
    assert all(item.reason == "kept" for item in phone_skipped)
    assert not any(repl.entity.type == EntityType.PHONE for repl in plan.replacements)

    inn_replacements = [repl for repl in plan.replacements if repl.entity.type == EntityType.INN]
    assert inn_replacements
