"""Координаты подсветки (`report.pages`/`entities[].regions`) для картинки.

Регресс, который ловит этот файл: `image_export_node` конвертирует
PDF-артефакты в картинку и заменяет `state["artifacts"][i]["path"]` на
`.jpg` **до** `report_node` — без отдельного ключа `pdf_path` `report_node`
не может найти PDF-артефакт (`_pick_pdf_artifact` ищет `path.suffix ==
".pdf"`), и `pages`/`regions` молча остаются пустыми ровно в дефолтном
режиме (`image_output_format="original"`) — том самом, что видит оператор.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from masker.graph.nodes import RunDeps
from masker.ocr.fake import FakeOCR
from masker.ocr.provider import OCRLine
from masker.run import RunOptions, sqlite_checkpointer_factory, start_run


def _line(text: str, y: int) -> OCRLine:
    return OCRLine(
        text=text,
        bbox=(50.0, float(y), 50.0 + 10.0 * len(text), float(y + 20)),
        polygon=(
            (50.0, float(y)),
            (50.0 + 10.0 * len(text), float(y)),
            (50.0 + 10.0 * len(text), float(y + 20)),
            (50.0, float(y + 20)),
        ),
        confidence=1.0,
    )


def _make_image(path: Path) -> None:
    Image.new("RGB", (800, 1100), (255, 255, 255)).save(str(path), format="JPEG", dpi=(300, 300))


def _run_image(tmp_path: Path, *, image_output_format: str = "original"):
    src = tmp_path / "contract.jpg"
    _make_image(src)
    fake = FakeOCR(
        lines=(
            _line("Договор поставки № 42", 100),
            _line("ИНН 7707083893 КПП 770701001", 200),
            _line("Стороны: ООО Ромашка и ИП Иванов", 300),
        )
    )
    options = RunOptions(
        rules_only=True,
        types=("inn",),
        interactive=False,
        styles=("marker",),
        image_output_format=image_output_format,  # type: ignore[arg-type]
    )
    deps = RunDeps(ocr=fake, artifact_dir=tmp_path / "artifacts")
    checkpointer_factory = sqlite_checkpointer_factory(tmp_path / "state.sqlite")
    return start_run(src, options, checkpointer_factory=checkpointer_factory, deps=deps)


def test_image_report_has_pages_and_regions_with_default_output_format(tmp_path: Path) -> None:
    """Дефолтный `image_output_format="original"`: артефакт — JPEG, но
    координаты подсветки всё равно приезжают в отчёт."""
    outcome = _run_image(tmp_path)
    assert outcome.status == "done"

    report = outcome.state["report"]
    assert report["pages"], "regions/pages не должны быть пустыми для картинки"
    assert all("width_pt" in page and "height_pt" in page for page in report["pages"])

    entities_with_regions = [e for e in report["entities"] if e.get("regions")]
    assert entities_with_regions, "хотя бы одна сущность должна получить regions"
    known_pages = {int(p["page"]) for p in report["pages"]}
    for entity in entities_with_regions:
        for region in entity["regions"]:
            assert region["page"] in known_pages
            assert 0.0 <= region["x0"] <= region["x1"] <= 1.0
            assert 0.0 <= region["y0"] <= region["y1"] <= 1.0

    # Итоговый артефакт — картинка, не PDF: пользователь видит JPEG.
    artifacts = {item["role"]: item["name"] for item in outcome.state["artifacts"]}
    assert artifacts["masked_highlight"].endswith(".jpg")


def test_image_report_has_pages_and_regions_with_pdf_output_format(tmp_path: Path) -> None:
    """`image_output_format="pdf"`: тот же контракт, но контрольный случай
    без конвертации — `_pick_pdf_artifact` находит PDF старым путём."""
    outcome = _run_image(tmp_path, image_output_format="pdf")
    assert outcome.status == "done"

    report = outcome.state["report"]
    assert report["pages"]
    assert any(e.get("regions") for e in report["entities"])

    artifacts = {item["role"]: item["name"] for item in outcome.state["artifacts"]}
    assert artifacts["masked_highlight"].endswith(".pdf")
