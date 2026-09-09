"""render_node — preview/masked_highlight/masked_black в RunDeps.artifact_dir (T1.10, шаг 5)."""

from __future__ import annotations

import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from masker.graph import nodes
from masker.graph.serde import plan_from_dict
from masker.graph.state import State

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"
XLSX_FIXTURE = ROOT / "fixtures" / "labeled" / "order_01.xlsx"


def _planned_state(
    *, source: Path = FIXTURE, styles: tuple[str, ...] = (), preview: bool = True
) -> State:
    """Состояние сразу после ``plan``: без профиля/политики — маскируется всё найденное."""
    state: State = {
        "path": str(source),
        "options": {
            "rules_only": True,
            "types": None,
            "interactive": False,
            "styles": list(styles),
            "preview": preview,
        },
    }
    state.update(nodes.extract_node(state))
    state.update(nodes.make_detect_node(nodes.RunDeps())(state))
    state.update(nodes.plan_node(state))
    return state


def test_render_node_creates_preview_and_both_styles_in_fixed_order(tmp_path: Path) -> None:
    state = _planned_state(styles=("blackbox", "marker"))
    render_node = nodes.make_render_node(nodes.RunDeps(artifact_dir=tmp_path))

    result = render_node(state)

    artifacts = result["artifacts"]
    assert [item["role"] for item in artifacts] == [
        "preview",
        "masked_highlight",
        "masked_black",
    ]
    assert (tmp_path / "preview.docx").is_file()
    assert (tmp_path / "masked_highlight.docx").is_file()
    assert (tmp_path / "masked_black.docx").is_file()
    for item in artifacts:
        mode = Path(item["path"]).stat().st_mode
        assert oct(mode)[-3:] == "600"


def test_render_node_redacted_files_do_not_contain_source_inn(tmp_path: Path) -> None:
    state = _planned_state(styles=("marker", "blackbox"))
    render_node = nodes.make_render_node(nodes.RunDeps(artifact_dir=tmp_path))

    render_node(state)

    plan = plan_from_dict(state["plan"])
    source_inns = [
        replacement.entity.text
        for replacement in plan.replacements
        if replacement.entity.type == "inn"
    ]
    assert source_inns  # фикстура обязана содержать хотя бы один ИНН

    for name in ("masked_highlight.docx", "masked_black.docx"):
        with zipfile.ZipFile(tmp_path / name) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
        for value in source_inns:
            assert value not in xml, f"{name}: исходный ИНН {value!r} утёк в word/document.xml"


def test_render_node_runs_xlsx_through_both_redacting_roles(tmp_path: Path) -> None:
    """XLSX не обходит LangGraph: из узла выходят оба варианта рендера.

    Preview намеренно отсутствует: отдельный XLSX-preview пока не умеет
    подсвечивать ячейки, а копия источника не может честно называться preview.
    """
    state = _planned_state(source=XLSX_FIXTURE, styles=("marker", "blackbox"))

    result = nodes.make_render_node(nodes.RunDeps(artifact_dir=tmp_path))(state)

    assert [item["role"] for item in result["artifacts"]] == [
        "masked_highlight",
        "masked_black",
    ]
    assert (tmp_path / "masked_highlight.xlsx").is_file()
    assert (tmp_path / "masked_black.xlsx").is_file()


def test_render_node_requires_artifact_dir() -> None:
    state = _planned_state(styles=())
    render_node = nodes.make_render_node(nodes.RunDeps(artifact_dir=None))

    with pytest.raises(ValueError):
        render_node(state)


def test_render_node_without_styles_writes_only_preview(tmp_path: Path) -> None:
    state = _planned_state(styles=())
    render_node = nodes.make_render_node(nodes.RunDeps(artifact_dir=tmp_path))

    result = render_node(state)

    assert [item["role"] for item in result["artifacts"]] == ["preview"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["preview.docx"]


def test_render_node_is_deterministic_across_directories(tmp_path: Path) -> None:
    state = _planned_state(styles=("blackbox",))
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    nodes.make_render_node(nodes.RunDeps(artifact_dir=dir_a))(state)
    nodes.make_render_node(nodes.RunDeps(artifact_dir=dir_b))(state)

    def _unzipped(path: Path) -> dict[str, bytes]:
        with zipfile.ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    assert _unzipped(dir_a / "masked_black.docx") == _unzipped(dir_b / "masked_black.docx")


def test_render_node_surfaces_pdf_marker_degradations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, planned_pdf_state: State
) -> None:
    """render_node доносит деградации лестницы отступления PDF-рендера до
    состояния — план T2.2.1, пачка 5: «каждый спуск фиксируется в отчёте».

    Стиль ``blackbox`` из выборки убран (план T2.2.2, шаг 1): после отката
    метки на чёрном прямоугольнике он деградаций больше не порождает.

    Деградация инжектируется через monkeypatch: конкретный PDF-документ не
    обязан иметь узкие поля при текущем наборе сущностей — важно, что
    render_node корректно доносит список деградаций до состояния."""
    from masker.model import MarkerRenderResult
    from masker.render import pdf_render as pdf_render_module
    from masker.render.pdf_render import RenderOutcome

    def patched_render(  # type: ignore[no-untyped-def]
        _source, _destination, _document, plan, *, style, highlight_background
    ):
        del highlight_background
        if style != "marker":
            return RenderOutcome(replacements=plan.replacements, markers=(), collisions=())
        replacement = plan.replacements[0]
        fake_marker = MarkerRenderResult(
            ref=replacement.ref,
            group_id=replacement.group_id,
            page=1,
            font_size=8.0,
            shown_label="ОРГАНИЗАЦИЯ",
            fallback_reason="type_only",
        )
        return RenderOutcome(
            replacements=plan.replacements,
            markers=(fake_marker,),
            collisions=(),
        )

    monkeypatch.setattr(pdf_render_module, "render_pdf_redacted", patched_render)

    state = deepcopy(planned_pdf_state)
    render_node = nodes.make_render_node(nodes.RunDeps(artifact_dir=tmp_path))

    result = render_node(state)

    degradations = result["render_degradations"]
    assert degradations, "render_node должен доносить деградации из PDF-рендера до состояния"
    sample = degradations[0]
    assert sample["artifact"] == "masked_highlight.pdf"
    assert sample["fallback_reason"] == "type_only"
    assert isinstance(sample["page"], int)
    assert sample["entity_type"]


def test_render_node_blackbox_never_surfaces_degradations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, planned_pdf_state: State
) -> None:
    """`report["render_degradations"]` для прогона со стилями
    `blackbox`+`marker` не содержит ни одной записи с
    `"role": "masked_black"` (план T2.2.2, шаг 1, приёмка)."""
    from masker.model import MarkerRenderResult
    from masker.render import pdf_render as pdf_render_module
    from masker.render.pdf_render import RenderOutcome

    def patched_render(  # type: ignore[no-untyped-def]
        _source, _destination, _document, plan, *, style, highlight_background
    ):
        del highlight_background
        if style != "marker":
            return RenderOutcome(replacements=plan.replacements, markers=(), collisions=())
        replacement = plan.replacements[0]
        fake_marker = MarkerRenderResult(
            ref=replacement.ref,
            group_id=replacement.group_id,
            page=1,
            font_size=8.0,
            shown_label="ОРГАНИЗАЦИЯ",
            fallback_reason="type_only",
        )
        return RenderOutcome(
            replacements=plan.replacements,
            markers=(fake_marker,),
            collisions=(),
        )

    monkeypatch.setattr(pdf_render_module, "render_pdf_redacted", patched_render)

    state = deepcopy(planned_pdf_state)
    state["options"]["styles"] = ["marker", "blackbox"]
    render_node = nodes.make_render_node(nodes.RunDeps(artifact_dir=tmp_path))

    result = render_node(state)

    degradations = result["render_degradations"]
    assert degradations, "инжектированная деградация должна появиться в состоянии"
    assert all(item["role"] != "masked_black" for item in degradations)
