"""Генератор синтетических image-фикстур из существующих PDF.

Каждая PDF-страница рендерится в JPEG и укладывается рядом с исходной
разметкой. Параллельно сохраняется `.fake_ocr.json` с координатами строк
для `FakeOCR` — точно так же, как `gen_scan_fixtures.py` делает для
`scan_synth_*.pdf`.

Запуск:
    python scripts/gen_image_fixtures.py

Генерирует:
    fixtures/labeled/image_01.jpg
    fixtures/labeled/image_01.labels.json
    fixtures/labeled/image_01.fake_ocr.json

Детерминизм: JPEG-encoder Pillow при фиксированных `quality`/`optimize`
даёт побайтово одинаковый файл между прогонами на одной машине.

DPI совпадает с `masker.ingest.scan_ingest._OCR_DPI` (400), чтобы
координаты в `.fake_ocr.json` соответствовали тому, что вычислит ingest
после конвертации картинки в промежуточный PDF.
"""

from __future__ import annotations

import json
import pathlib
import sys

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = BACKEND_DIR / "fixtures" / "labeled"

sys.path.insert(0, str(BACKEND_DIR / "src"))


def _page_text_lines(page: object, dpi: int) -> list[dict]:  # type: ignore[type-arg]
    """OCRLine-совместимые dict'ы из текстового слоя страницы (координаты в px)."""
    import pymupdf  # type: ignore[import-untyped]

    page_obj: pymupdf.Page = page  # type: ignore[assignment]
    data = page_obj.get_text("rawdict")
    lines: list[dict] = []
    scale = dpi / 72.0
    for block in data["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            text = " ".join(
                "".join(ch["c"] for ch in span["chars"]) for span in line["spans"]
            ).strip()
            if not text:
                continue
            bbox_pts = line["bbox"]  # (x0, y0, x1, y1) in pt
            bbox_px = [coord * scale for coord in bbox_pts]
            lines.append(
                {
                    "text": text,
                    "bbox": bbox_px,
                    "polygon": [
                        [bbox_px[0], bbox_px[1]],
                        [bbox_px[2], bbox_px[1]],
                        [bbox_px[2], bbox_px[3]],
                        [bbox_px[0], bbox_px[3]],
                    ],
                    "confidence": 1.0,
                }
            )
    return lines


def gen_image_01() -> None:
    """image_01.jpg — первая страница contract_pdf_01.pdf в JPEG 300 dpi."""
    import pymupdf  # type: ignore[import-untyped]

    src_pdf = FIXTURES / "contract_pdf_01.pdf"
    src_labels = FIXTURES / "contract_pdf_01.labels.json"
    if not src_pdf.exists():
        print(f"[skip] {src_pdf} не найден")
        return

    out_jpg = FIXTURES / "image_01.jpg"
    out_labels = FIXTURES / "image_01.labels.json"
    out_ocr = FIXTURES / "image_01.fake_ocr.json"

    # DPI картинки: 300 (типичный canonical для «отсканировано с бумаги»),
    # НЕ scan_ingest._OCR_DPI: OCR-роутер рендерит нашу картинку заново
    # при том DPI, что задан в scan_ingest — но нам нужны те же px-координаты,
    # что и рендер сделает.
    from masker.ingest.scan_ingest import _OCR_DPI

    dpi_render = _OCR_DPI

    src_doc = pymupdf.open(str(src_pdf))
    page = src_doc[0]
    # Рендерим страницу в pixmap с dpi_render, чтобы координаты OCR-линий
    # совпали с тем, что реально увидит `ocr_segments_for_page` после
    # конвертации нашей картинки в PDF.
    pix = page.get_pixmap(dpi=dpi_render, colorspace=pymupdf.csRGB)
    ocr_page = {
        "width_px": pix.width,
        "height_px": pix.height,
        "lines": _page_text_lines(page, dpi_render),
    }

    from PIL import Image

    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    # Сохраняем как JPEG с фиксированным quality — побайтово детерминированно
    # между прогонами на одной сборке Pillow.
    img.save(str(out_jpg), format="JPEG", quality=95, optimize=False, dpi=(dpi_render, dpi_render))
    src_doc.close()

    labels = json.loads(src_labels.read_text(encoding="utf-8"))
    out_labels.write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    out_ocr.write_text(
        json.dumps([ocr_page], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[ok] {out_jpg.name}  ({pix.width}x{pix.height}, dpi={dpi_render})")


if __name__ == "__main__":
    gen_image_01()
    print("Готово.")
