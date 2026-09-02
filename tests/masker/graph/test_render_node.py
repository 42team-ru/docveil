"""render_node — preview/masked_highlight/masked_black в RunDeps.artifact_dir (T1.10, шаг 5)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from masker.graph import nodes
from masker.graph.serde import plan_from_dict
from masker.graph.state import State

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"
#: Реальный документ с известным узким полем (план T2.2.1, пачка 5: маркер
#: `[СТОРОНА-27-ОРГАНИЗАЦИЯ]` не помещался в исходную ширину «ГО и ЧС» до
#: лестницы отступления) — годится, чтобы проверить, что render_node
#: реально доносит деградацию до отчёта, а не только внутренняя функция
#: `pdf_render.py` её вычисляет.
PDF_FIXTURE = ROOT / "fixtures" / "labeled" / "contract_pdf_02_school.pdf"


def _planned_state(*, styles: tuple[str, ...] = (), preview: bool = True) -> State:
    """Состояние сразу после ``plan``: без профиля/политики — маскируется всё найденное."""
    state: State = {
        "path": str(FIXTURE),
        "options": {
            "rules_only": True,
            "types": None,
            "interactive": False,
            "styles": list(styles),
            "preview": preview,
        },
    }
    state.update(nodes.extract_node(state))
    state.update(nodes.detect_node(state))
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
        if replacement.entity.type.value == "inn"
    ]
    assert source_inns  # фикстура обязана содержать хотя бы один ИНН

    for name in ("masked_highlight.docx", "masked_black.docx"):
        with zipfile.ZipFile(tmp_path / name) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
        for value in source_inns:
            assert value not in xml, f"{name}: исходный ИНН {value!r} утёк в word/document.xml"


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


def test_render_node_surfaces_pdf_marker_degradations(tmp_path: Path) -> None:
    """render_node доносит деградации лестницы отступления PDF-рендера до
    состояния — план T2.2.1, пачка 5: «каждый спуск фиксируется в отчёте».

    Стиль ``blackbox`` из выборки убран (план T2.2.2, шаг 1): после отката
    метки на чёрном прямоугольнике он деградаций больше не порождает."""
    state: State = {
        "path": str(PDF_FIXTURE),
        "options": {
            "rules_only": False,
            "types": None,
            "interactive": False,
            "styles": ["marker"],
            "preview": False,
        },
    }
    state.update(nodes.extract_node(state))
    state.update(nodes.detect_node(state))
    state.update(nodes.plan_node(state))
    render_node = nodes.make_render_node(nodes.RunDeps(artifact_dir=tmp_path))

    result = render_node(state)

    degradations = result["render_degradations"]
    assert degradations, "на этом документе известно узкое поле — список не должен быть пуст"
    sample = degradations[0]
    assert sample["artifact"] == "masked_highlight.pdf"
    assert sample["shown_as"] in ("type_label", "blank")
    assert isinstance(sample["page"], int)
    assert sample["entity_type"]


def test_render_node_blackbox_never_surfaces_degradations(tmp_path: Path) -> None:
    """`report["render_degradations"]` для прогона со стилями
    `blackbox`+`marker` не содержит ни одной записи с
    `"role": "masked_black"` (план T2.2.2, шаг 1, приёмка)."""
    state: State = {
        "path": str(PDF_FIXTURE),
        "options": {
            "rules_only": False,
            "types": None,
            "interactive": False,
            "styles": ["marker", "blackbox"],
            "preview": False,
        },
    }
    state.update(nodes.extract_node(state))
    state.update(nodes.detect_node(state))
    state.update(nodes.plan_node(state))
    render_node = nodes.make_render_node(nodes.RunDeps(artifact_dir=tmp_path))

    result = render_node(state)

    degradations = result["render_degradations"]
    assert degradations, "на этом документе известно узкое поле — список не должен быть пуст"
    assert all(item["role"] != "masked_black" for item in degradations)
