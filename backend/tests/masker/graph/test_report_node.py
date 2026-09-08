"""report_node — report.json-совместимая структура из State (T1.10, шаг 7)."""

from __future__ import annotations

import json
from pathlib import Path

from masker.graph import nodes
from masker.graph.state import State

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"

#: Множество ключей верхнего уровня report.json «простого пути» (``cli.py::
#: inspect_docx``) на ``contract_01.docx --profile --types all``, плюс
#: ``decisions`` — единственная запись, которой у простого пути нет и не
#: может быть: она про решения человека/политики, а простой путь их не
#: принимает. Значение проверено эмпирически перед написанием этого теста
#: (``main([... "--profile"])`` и сравнение множеств ключей двух report.json).
_REFERENCE_KEYS = frozenset(
    {
        "report_version",
        "input",
        "format",
        "preview_only",
        "selected_types",
        "entity_count",
        "chunk_count",
        "summary",
        "detection_coverage",
        "document_coverage",
        "entities",
        "chunks",
        "limitations",
        "plan",
        "profile_judge",
        "validation",
        "leaked",
        "decisions",
        #: Спуски по лестнице отступления маркера PDF (план T2.2.1, пачка 5).
        "render_degradations",
        #: Сохранность текстового слоя PDF вне замен (план T2.2.2, шаг 5).
        "layout",
        #: Р8 — «снять одним кликом»: группы уровня "possible" отдельным
        #: списком, даже пустым, если план был построен.
        "review_possible",
    }
)


def _full_state(tmp_path: Path, *, profile: bool = True, styles: tuple[str, ...] = ()) -> State:
    """Прогнать состояние через весь граф до ``validate`` включительно.

    Неинтерактивно (``interactive=False``): вопросы политике/судье не
    задаются, а решения опираются только на уверенность детектора и защиту
    критичных типов — этого достаточно, чтобы дойти до ``final_actions``/
    ``plan``/``artifacts``/``validation``, которые и собирает ``report_node``.
    """
    state: State = {
        "path": str(FIXTURE),
        "options": {
            "rules_only": True,
            "types": None,
            "interactive": False,
            "profile": profile,
            "unmask_critical": False,
            "thread_id": "t-report",
            "styles": list(styles),
            "preview": True,
        },
    }
    state.update(nodes.extract_node(state))
    state.update(nodes.make_detect_node(nodes.RunDeps())(state))
    state.update(nodes.make_profile_node(nodes.RunDeps())(state))
    state.update(nodes.make_judge_node(nodes.RunDeps())(state))
    state.update(nodes.policy_node(state))
    state["answers"] = {}
    state.update(nodes.apply_answers_node(state))
    state.update(nodes.finalize_node(state))
    state.update(nodes.plan_node(state))
    state.update(nodes.make_render_node(nodes.RunDeps(artifact_dir=tmp_path))(state))
    state.update(nodes.validate_node(state))
    return state


def test_report_node_top_level_keys_match_reference(tmp_path: Path) -> None:
    state = _full_state(tmp_path)

    result = nodes.make_report_node(nodes.RunDeps())(state)

    report = result["report"]
    assert report["report_version"] == 3
    assert set(report.keys()) == _REFERENCE_KEYS


def test_report_node_json_serializable_and_has_no_absolute_paths(tmp_path: Path) -> None:
    state = _full_state(tmp_path, styles=("marker", "blackbox"))
    # Артефакты обязаны нести абсолютные пути внутри State (нужны CLI/валидатору) —
    # тест проваливается сам по себе, если в этом окружении это не так.
    assert any(item["path"] for item in state["artifacts"])
    assert all(Path(item["path"]).is_absolute() for item in state["artifacts"])

    result = nodes.make_report_node(nodes.RunDeps())(state)
    report = result["report"]

    dumped = json.dumps(report, ensure_ascii=False)  # не должно упасть — json-сериализуемо
    assert str(tmp_path) not in dumped
    assert report["input"] == FIXTURE.name


def test_report_node_without_profile_has_no_profile_judge_key(tmp_path: Path) -> None:
    state = _full_state(tmp_path, profile=False)

    result = nodes.make_report_node(nodes.RunDeps())(state)

    report = result["report"]
    assert "profile_judge" not in report
    assert report["entity_count"] > 0


def test_report_node_notes_llm_trace_limitation_only_when_tracer_present(tmp_path: Path) -> None:
    """``deps.tracer`` — единственный сигнал узлу, что шёл трейс LLM (T1.10, шаг 9).

    Раньше узел был голой функцией и жёстко передавал ``llm_trace=False`` —
    отчёт графового пути никогда не предупреждал про содержимое
    ``llm-trace.*`` в ``report["limitations"]``, даже когда трейс реально
    записывался (``cli.py`` через ``TracingProvider``).
    """
    state = _full_state(tmp_path)

    without_tracer = nodes.make_report_node(nodes.RunDeps())(state)["report"]
    assert not any("llm-trace" in item for item in without_tracer["limitations"])

    from masker.llm.fake import FakeProvider
    from masker.llm.trace import TracingProvider

    with_tracer = nodes.make_report_node(nodes.RunDeps(tracer=TracingProvider(FakeProvider())))(
        state
    )["report"]
    assert any("llm-trace" in item for item in with_tracer["limitations"])
