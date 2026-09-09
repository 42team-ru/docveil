"""Диагностика OCR: что движок нашёл на каждой странице скан-PDF.

Выводит в stdout все распознанные строки (с confidence) и сохраняет
PDF с видимым текстовым слоем — можно открыть и выделить текст, чтобы
сравнить с тем, что нашёл детектор.

Запуск:
    MASKER_OCR=paddle .venv/bin/python scripts/ocr_dump.py <файл.pdf>
    MASKER_OCR=paddle .venv/bin/python scripts/ocr_dump.py <файл.pdf> --out ocr_out.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Скан-PDF для OCR")
    parser.add_argument("--out", type=Path, default=None, help="Куда сохранить PDF с текстом")
    parser.add_argument("--min-confidence", type=float, default=0.0, help="Порог confidence (0..1)")
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"Файл не найден: {args.pdf}", file=sys.stderr)
        return 1

    import pymupdf

    from masker.ingest.scan_ingest import _page_is_scan, ocr_segments_for_page
    from masker.ocr.select import select_ocr

    ocr = select_ocr()
    doc = pymupdf.open(str(args.pdf))

    out_path = args.out or args.pdf.with_stem(args.pdf.stem + "_ocr")

    print(f"Файл:     {args.pdf.name}")
    print(f"Страниц:  {len(doc)}")
    print(f"OCR:      {type(ocr).__name__}")
    print(f"Вывод:    {out_path}")
    print()

    total_lines = 0
    for page_num in range(len(doc)):
        page = doc[page_num]
        is_scan = _page_is_scan(page)
        print(f"─── Стр. {page_num + 1}  {'(скан)' if is_scan else '(текстовый слой)'}")

        if not is_scan:
            # Текстовая страница — показать то, что видит ingest
            text = page.get_text("text").strip()
            if text:
                for line in text.splitlines():
                    print(f"  {line}")
            else:
                print("  (пусто)")
            print()
            continue

        # Скан: запустить OCR
        segs = ocr_segments_for_page(page, page_num, ocr)
        page_lines = [s for s in segs if s.text.strip()]

        if not page_lines:
            print("  (OCR ничего не нашёл)")
            print()
            continue

        for seg in page_lines:
            total_lines += 1
            print(f"  {seg.text}")

        # Добавить видимый текстовый слой в PDF
        _add_text_layer(page, segs, args.min_confidence)
        print()

    print(f"Итого строк OCR: {total_lines}")

    doc.save(str(out_path))
    doc.close()
    print(f"\nСохранён: {out_path}")
    print("Откройте в PDF-ридере — текст доступен для выделения и копирования.")
    return 0


def _add_text_layer(page: pymupdf.Page, segs: list, min_confidence: float) -> None:
    """Наложить OCR-текст как видимый слой на страницу (render_mode=0)."""
    import pymupdf

    for seg in segs:
        if not seg.text.strip():
            continue
        # bbox из локатора: ("page", num, "ocr", x0*100, y0*100, x1*100, y1*100)
        locator = seg.anchor.locator
        if len(locator) != 7 or locator[2] != "ocr":
            continue
        _, _page_num, _tag, x0_i, y0_i, x1_i, y1_i = locator
        x0, y0, x1, y1 = x0_i / 100, y0_i / 100, x1_i / 100, y1_i / 100
        height = y1 - y0
        fontsize = max(6.0, height * 0.7)
        # Полупрозрачный красный прямоугольник — граница сегмента
        page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(1, 0, 0), width=0.5)
        # Видимый текст (render_mode=0) — можно выделить и скопировать
        page.insert_text(
            (x0, y1 - 2),
            seg.text,
            fontsize=fontsize,
            color=(0.8, 0, 0),
        )


if __name__ == "__main__":
    sys.exit(main())
