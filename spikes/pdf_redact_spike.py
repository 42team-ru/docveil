"""Проверка самого рискованного места: настоящее удаление текста из PDF.

Закрашенный прямоугольник поверх текста — не обезличивание: текст остаётся
в файле и вынимается копипастом. PyMuPDF `apply_redactions()` вырезает его
из потока содержимого. Спайк доказывает разницу измеримо.

Две грабли, на которых теряется полдня:

1. Параметр `text=` у `add_redact_annot` рисует базовым шрифтом (WinAnsi) —
   кириллица молча не появляется. Маркер вписываем сами, шрифтом с кириллицей.
2. Маркер шире освободившегося места молча не рисуется. Кегль подбираем под
   ширину прямоугольника и проверяем возвращённое значение `insert_textbox`.
"""

from __future__ import annotations

import pathlib
import sys

import pymupdf

OUT = pathlib.Path(__file__).parent / "out"
FONT_FILE = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_NAME = "cyr"
HIGHLIGHT = (1.0, 0.95, 0.4)

SECRET_INN = "3662103003"
SECRET_ACC = "40702810100000000001"


def make_source(path: pathlib.Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname=FONT_NAME, fontfile=FONT_FILE)
    lines = [
        "ДОГОВОР ПОСТАВКИ № 44/2026",
        "",
        "Поставщик: АО «Триема», ИНН " + SECRET_INN,
        "Директор: Иванов Иван Иванович",
        "Расчётный счёт: " + SECRET_ACC,
    ]
    y = 80
    for line in lines:
        page.insert_text((72, y), line, fontname=FONT_NAME, fontsize=12)
        y += 22
    doc.set_metadata({"author": "Иванов И.И.", "title": "Договор 44/2026"})
    doc.save(path)
    doc.close()


_FONT = pymupdf.Font(fontfile=FONT_FILE)


def fit_fontsize(rect: pymupdf.Rect, text: str) -> float:
    """Наибольший кегль, при котором маркер влезает в освободившееся место."""
    for size in (10, 9, 8, 7, 6, 5, 4):
        if _FONT.text_length(text, fontsize=size) <= rect.width and size <= rect.height:
            return float(size)
    return 4.0


def redact(src: pathlib.Path, dst: pathlib.Path, targets: dict[str, str]) -> int:
    doc = pymupdf.open(src)
    hits = 0
    for page in doc:
        page.insert_font(fontname=FONT_NAME, fontfile=FONT_FILE)
        placements: list[tuple[pymupdf.Rect, str]] = []
        for needle, marker in targets.items():
            for rect in page.search_for(needle):
                # Заливка — та самая визуальная подсветка изменения.
                page.add_redact_annot(rect, fill=HIGHLIGHT)
                placements.append((rect, marker))
                hits += 1
        page.apply_redactions()

        # Текст уже вырезан — вписываем маркер поверх освободившегося места.
        for rect, marker in placements:
            size = fit_fontsize(rect, marker)
            box = pymupdf.Rect(rect.x0, rect.y0 - 1, rect.x1 + 2, rect.y1 + 2)
            rc = page.insert_textbox(
                box,
                marker,
                fontname=FONT_NAME,
                fontfile=FONT_FILE,
                fontsize=size,
                color=(0.35, 0.15, 0.0),
                align=pymupdf.TEXT_ALIGN_LEFT,
            )
            if rc < 0:
                raise RuntimeError(f"маркер {marker!r} не влез в {rect}")

    doc.set_metadata({})  # метаданные — тоже канал утечки
    doc.del_xml_metadata()
    doc.save(dst, garbage=4, deflate=True)
    doc.close()
    return hits


def main() -> int:
    OUT.mkdir(exist_ok=True)
    src, dst = OUT / "source.pdf", OUT / "masked.pdf"
    make_source(src)
    hits = redact(src, dst, {SECRET_INN: "[ИНН-1]", SECRET_ACC: "[СЧЁТ-1]"})

    with pymupdf.open(src) as a, pymupdf.open(dst) as b:
        before, after = a[0].get_text(), b[0].get_text()
        pages_ok = len(a) == len(b)
        meta_clean = not (b.metadata or {}).get("author")
    raw = dst.read_bytes()

    checks = {
        "найдено спанов = 2": hits == 2,
        "ИНН был в исходнике": SECRET_INN in before,
        "ИНН удалён из текстового слоя": SECRET_INN not in after,
        "счёт удалён из текстового слоя": SECRET_ACC not in after,
        "ИНН отсутствует в байтах файла": SECRET_INN.encode() not in raw,
        "маркер [ИНН-1] на месте": "[ИНН-1]" in after,
        "маркер [СЧЁТ-1] на месте": "[СЧЁТ-1]" in after,
        "остальной текст цел": "Иванов Иван Иванович" in after,
        "число страниц сохранено": pages_ok,
        "метаданные зачищены": meta_clean,
    }
    for name, ok in checks.items():
        print(f"  {'ok  ' if ok else 'ПЛОХО'}  {name}")

    passed = all(checks.values())
    print("\nСПАЙК ПРОЙДЕН" if passed else "\nСПАЙК ПРОВАЛЕН")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
