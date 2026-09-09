"""Генератор синтетических скан-фикстур из существующих PDF.

Каждая страница исходного PDF рендерится в PNG и укладывается обратно
в новый PDF без текстового слоя — получается «скан». Параллельно сохраняется
`.fake_ocr.json` с текстом каждой страницы, который используется `FakeOCR`
при `MASKER_OCR=fake` для воспроизводимых CI-прогонов.

Запуск:
    python scripts/gen_scan_fixtures.py

Генерирует:
    fixtures/labeled/scan_synth_01.pdf
    fixtures/labeled/scan_synth_01.labels.json
    fixtures/labeled/scan_synth_01.fake_ocr.json

Детерминизм: одни и те же входные файлы → побайтово одинаковые выходные
(DPI, порядок страниц, сжатие — все фиксированы).

DPI должен совпадать с `masker.ingest.scan_ingest._OCR_DPI`, иначе bbox-координаты
в fake_ocr.json не совпадут с тем, что вычисляет ingest при конвертации px→pt.
"""

from __future__ import annotations

import json
import pathlib
import sys

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = BACKEND_DIR / "fixtures" / "labeled"

sys.path.insert(0, str(BACKEND_DIR / "src"))


def _page_text_lines(page: object) -> list[dict]:  # type: ignore[type-arg]
    """Список OCRLine-совместимых dict'ов из текстового слоя страницы."""
    import pymupdf  # type: ignore[import-untyped]

    page_obj: pymupdf.Page = page  # type: ignore[assignment]
    data = page_obj.get_text("rawdict")
    lines: list[dict] = []
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
            # FakeOCR bbox — в пикселях при DPI (_OCR_DPI); pt_to_px = DPI/72
            scale = 300.0 / 72.0
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


def gen_scan_synth_01() -> None:
    """scan_synth_01 — прямой аналог contract_pdf_01.pdf, без текстового слоя."""
    import pymupdf  # type: ignore[import-untyped]

    src_pdf = FIXTURES / "contract_pdf_01.pdf"
    src_labels = FIXTURES / "contract_pdf_01.labels.json"
    if not src_pdf.exists():
        print(f"[skip] {src_pdf} не найден")
        return

    out_pdf = FIXTURES / "scan_synth_01.pdf"
    out_labels = FIXTURES / "scan_synth_01.labels.json"
    out_ocr = FIXTURES / "scan_synth_01.fake_ocr.json"

    from masker.ingest.scan_ingest import _OCR_DPI

    DPI = _OCR_DPI
    src_doc = pymupdf.open(str(src_pdf))
    new_doc = pymupdf.open()
    ocr_pages: list[list[dict]] = []

    for page_num in range(len(src_doc)):
        page = src_doc[page_num]
        # Сохранить OCR-строки до рендера (текстовый слой ещё есть)
        pix_size = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csRGB)
        page_entry = {
            "width_px": pix_size.width,
            "height_px": pix_size.height,
            "lines": _page_text_lines(page),
        }
        ocr_pages.append(page_entry)
        # Рендер в PNG (pix_size уже посчитан выше)
        pix = pix_size
        img_bytes = pix.tobytes("png")
        # Добавить страницу нужного размера в pt (1 pt = 1/72 дюйма)
        new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=img_bytes)

    src_doc.close()
    new_doc.save(str(out_pdf), garbage=4, deflate=True, no_new_id=1)
    new_doc.close()

    # Скопировать разметку (без изменений — текст тот же)
    labels = json.loads(src_labels.read_text(encoding="utf-8"))
    out_labels.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")

    # Сохранить OCR-строки для FakeOCR
    out_ocr.write_text(json.dumps(ocr_pages, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] {out_pdf.name}  ({len(ocr_pages)} стр.)")


if __name__ == "__main__":
    gen_scan_synth_01()
    print("Готово.")
