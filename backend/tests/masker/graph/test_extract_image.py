"""Прогон `_extract` на картинке — интеграция ingest'а картинки в граф."""

from __future__ import annotations

import pathlib

from PIL import Image

from masker.graph.nodes import RunDeps, make_extract_node
from masker.ocr.fake import FakeOCR
from masker.ocr.provider import OCRLine


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


def _make_image(path: pathlib.Path) -> None:
    Image.new("RGB", (800, 1100), (255, 255, 255)).save(str(path), format="JPEG", dpi=(300, 300))


def test_extract_image_populates_state(tmp_path: pathlib.Path) -> None:
    src = tmp_path / "contract.jpg"
    _make_image(src)
    fake = FakeOCR(
        lines=(
            _line("Договор поставки № 42", 100),
            _line("ИНН 7707083893 КПП 770701001", 200),
            _line("Стороны: ООО Ромашка и ИП Иванов", 300),
        )
    )
    deps = RunDeps(ocr=fake)
    node = make_extract_node(deps)
    state: dict[str, object] = {"path": str(src)}
    result = node(state)  # type: ignore[arg-type]

    # После конвертации fmt всегда "pdf" — рендер и валидация идут PDF-путём.
    assert result["fmt"] == "pdf"
    meta = result["meta"]
    assert isinstance(meta, dict)
    assert meta["image_source"] == "contract.jpg"
    assert meta["image_suffix"] == ".jpg"
    assert meta["name"] == "contract.jpg"
    assert meta["format"] == "pdf"
    coverage = result["coverage"]
    assert isinstance(coverage, dict)
    assert "image" in coverage
    image_cov = coverage["image"]
    assert isinstance(image_cov, dict)
    assert image_cov["processed"] is True
    assert image_cov["source"] == "contract.jpg"
    segments = result["segments"]
    assert isinstance(segments, list)
    assert len(segments) == 3
    assert all(seg["origin"] == "ocr" for seg in segments)
