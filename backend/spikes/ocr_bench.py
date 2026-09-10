#!/usr/bin/env python
"""OCR-бенчмарк: прогон скан-PDF через разные провайдеры OCR.

Запуск (из backend/):
    python spikes/ocr_bench.py                          # все провайдеры, все PDF
    python spikes/ocr_bench.py -p rapid easy            # только rapid и easy
    python spikes/ocr_bench.py -f fixtures/non-text-pdfs/*.pdf
    python spikes/ocr_bench.py -p rapid --out bench_out/  # сохранить .txt

Эталон: fixtures/non-text-pdfs/TEXTS/<stem>.txt — если файл есть, считаются
CER и WER нормализованного OCR-вывода против нормализованного эталона.

Нормализация (применяется к эталону И к OCR-выводу одинаково):
  • переносы строк → пробел
  • все виды тире (—–‒) → дефис -
  • все виды кавычек («»""'') → "
  • неразрывные/тонкие пробелы → обычный пробел
  • мягкий перенос (U+00AD) → убрать
  • многоточие … → ...
  • схлопывание множественных пробелов
  Не трогаем: буквы, цифры, email, ИНН, даты, номера телефонов, адреса.

DPI рендера: 300 (по умолчанию). Менять через --dpi.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
import time
from pathlib import Path

# Директории фикстур относительно backend/.
_FIXTURE_DIRS = [
    Path("fixtures/labeled"),
    Path("fixtures/non-text-pdfs"),
]
# Каталог с эталонными текстами (относительно backend/).
_REF_DIR = Path("fixtures/non-text-pdfs/TEXTS")

# Провайдеры в порядке скорости (быстрые первыми).
_ALL_PROVIDERS = ["rapid", "easy", "tesseract"]


# ---------------------------------------------------------------------------
# Нормализация текста для сравнения
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """Нормализовать текст для метрик: убрать неоднозначные спецсимволы.

    Правила:
    - Мягкий перенос (U+00AD) — убрать полностью.
    - Переносы строк → пробел.
    - Неразрывные и типографские пробелы → ASCII-пробел.
    - Все виды тире (em-dash, en-dash, горизонтальная черта, минус) → дефис.
    - Все виды кавычек → прямая двойная кавычка.
    - Многоточие … → три точки.
    - Collapse множественных пробелов в один.
    Буквы, цифры, email, даты, телефоны, ИНН — не трогаем.
    """
    # Мягкий перенос — убрать.
    text = text.replace("­", "")

    # Переносы строк → пробел.
    text = re.sub(r"[\r\n]+", " ", text)

    # Все типографские пробелы → ASCII-пробел.
    # U+00A0 NBSP, U+2002..U+200B разные узкие/средние, U+202F узкий NBSP, U+205F, U+3000.
    text = re.sub(r"[          ​  　]", " ", text)

    # Все виды тире → дефис-минус.
    # U+2010 HYPHEN, U+2011 NON-BREAKING HYPHEN, U+2012 FIGURE DASH,
    # U+2013 EN DASH, U+2014 EM DASH, U+2015 HORIZONTAL BAR,
    # U+2212 MINUS SIGN, U+FE58 SMALL EM DASH, U+FE63 SMALL HYPHEN-MINUS,
    # U+FF0D FULLWIDTH HYPHEN-MINUS.
    text = re.sub(r"[‐‑‒–—―−﹘﹣－]", "-", text)

    # Все виды кавычек → прямая двойная кавычка.
    # «» (guillemets), "" (curly), „" (low-high), '' (curly single) → "
    text = re.sub(r"[«»“”„‟‘’ʼʻ]", '"', text)

    # Многоточие → три точки.
    text = text.replace("…", "...")

    # Collapse пробелов.
    text = re.sub(r" {2,}", " ", text)

    return text.strip()


def cer(hypothesis: str, reference: str) -> float:
    """Character Error Rate: 0.0 = идеально, 1.0 = совпадений нет."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    sm = difflib.SequenceMatcher(None, hypothesis, reference, autojunk=False)
    return round(1.0 - sm.ratio(), 4)


def wer(hypothesis: str, reference: str) -> float:
    """Word Error Rate по словам (split())."""
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    sm = difflib.SequenceMatcher(None, hyp_words, ref_words, autojunk=False)
    return round(1.0 - sm.ratio(), 4)


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


def _find_scan_pdfs(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            for p in sorted(root.glob("*.pdf")):
                found.append(p)
    return found


def _load_reference(pdf_path: Path, ref_dir: Path) -> str | None:
    """Вернуть нормализованный эталонный текст для PDF или None."""
    ref_path = ref_dir / (pdf_path.stem + ".txt")
    if not ref_path.exists():
        return None
    raw = ref_path.read_text(encoding="utf-8")
    return normalize(raw)


def _render_pages(pdf_path: Path, dpi: int) -> list[tuple[int, object]]:
    """Вернуть [(page_num, bgr_ndarray), ...] для каждой страницы PDF."""
    import numpy as np
    import pymupdf

    pages: list[tuple[int, object]] = []
    doc = pymupdf.open(str(pdf_path))  # type: ignore[no-untyped-call]
    try:
        for i, page in enumerate(doc):  # type: ignore[var-annotated]
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB)
            img_rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            img_bgr = img_rgb[:, :, ::-1].copy()
            pages.append((i, img_bgr))
    finally:
        doc.close()  # type: ignore[no-untyped-call]
    return pages


def _run_provider(
    name: str, pages: list[tuple[int, object]], dpi: int
) -> tuple[str | None, float, list[str]]:
    """Прогнать страницы через провайдер. Возвращает (error, elapsed_s, page_texts)."""
    try:
        from masker.ocr.select import select_ocr

        provider = select_ocr(name)
    except Exception as e:
        return str(e), 0.0, []

    texts: list[str] = []
    t0 = time.perf_counter()
    for _page_num, img_bgr in pages:
        try:
            lines = provider.recognize(img_bgr, dpi=dpi)  # type: ignore[arg-type]
            texts.append(" ".join(ln.text for ln in lines if ln.text.strip()))
        except Exception as e:
            texts.append(f"[ОШИБКА РАСПОЗНАВАНИЯ: {e}]")
    elapsed = time.perf_counter() - t0
    return None, elapsed, texts


# ---------------------------------------------------------------------------
# Вывод
# ---------------------------------------------------------------------------

_W = 76


def _hr(char: str = "─") -> str:
    return char * _W


def _print_provider_result(
    provider: str,
    error: str | None,
    elapsed: float,
    page_texts: list[str],
    reference: str | None,
    *,
    verbose: bool,
    out,
) -> None:
    print(f"\n  ┌{'─' * (_W - 2)}┐", file=out)
    print(f"  │  провайдер: {provider:<{_W - 17}}│", file=out)
    if error:
        msg = f"НЕДОСТУПЕН — {error}"
        print(f"  │  {msg[: _W - 6]:<{_W - 6}}│", file=out)
        print(f"  └{'─' * (_W - 2)}┘", file=out)
        return

    n_pages = len(page_texts)
    total_chars = sum(len(t) for t in page_texts)
    combined = normalize(" ".join(page_texts))

    metric_str = ""
    if reference is not None:
        c = cer(combined, reference)
        w = wer(combined, reference)
        metric_str = f"  CER={c:.1%}  WER={w:.1%}"

    info = f"стр:{n_pages}  символов:{total_chars}  время:{elapsed:.1f}s{metric_str}"
    print(f"  │  {info:<{_W - 6}}│", file=out)
    print(f"  └{'─' * (_W - 2)}┘", file=out)

    for i, text in enumerate(page_texts):
        if verbose or n_pages == 1:
            print(f"\n  ── стр. {i + 1} ──", file=out)
            print(text or "(пусто)", file=out)
        else:
            preview = text[:180].replace("\n", " ")
            suffix = "…" if len(text) > 180 else ""
            print(f"  стр.{i + 1}: {preview}{suffix}", file=out)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OCR-бенчмарк: сравнение провайдеров на скан-PDF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-p",
        "--providers",
        nargs="+",
        default=_ALL_PROVIDERS,
        metavar="ПРОВАЙДЕР",
        help=f"провайдеры (default: {' '.join(_ALL_PROVIDERS)})",
    )
    parser.add_argument(
        "-f",
        "--files",
        nargs="+",
        type=Path,
        metavar="PDF",
        help="конкретные PDF (default: все из fixtures/)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="DPI рендера страниц (default: 300)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="КАТАЛОГ",
        help="сохранить .txt-файлы с нормализованным текстом и эталоном",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="полный текст каждой страницы (по умолчанию — превью 180 символов)",
    )
    args = parser.parse_args(argv)

    # Список PDF.
    if args.files:
        pdfs = [p.resolve() for p in args.files]
    else:
        here = Path(__file__).parent.parent  # backend/
        pdfs = _find_scan_pdfs([here / d for d in _FIXTURE_DIRS])
        # Пропустить _ocr-версии (уже имеют текстовый слой).
        pdfs = [p for p in pdfs if "_ocr" not in p.stem]

    if not pdfs:
        print("Нет PDF-файлов. Укажите --files или проверьте fixtures/.", file=sys.stderr)
        return 1

    here = Path(__file__).parent.parent
    ref_dir = here / _REF_DIR

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    print(
        f"PDF-файлов: {len(pdfs)}  |  провайдеры: {', '.join(args.providers)}  |  DPI: {args.dpi}"
    )
    print(f"Эталоны: {ref_dir}")

    for pdf_path in pdfs:
        print(f"\n{'═' * _W}")
        print(f"  {pdf_path.name}")
        print(f"{'═' * _W}")

        reference = _load_reference(pdf_path, ref_dir)
        if reference is not None:
            print(f"  [эталон найден: {len(reference)} символов после нормализации]")
        else:
            print("  [эталон отсутствует — метрики не вычисляются]")

        try:
            pages = _render_pages(pdf_path, dpi=args.dpi)
        except Exception as e:
            print(f"  [РЕНДЕР ОШИБКА]: {e}", file=sys.stderr)
            continue
        print(f"  Страниц: {len(pages)}")

        for provider_name in args.providers:
            error, elapsed, page_texts = _run_provider(provider_name, pages, dpi=args.dpi)

            if args.out and not error:
                stem = f"{pdf_path.stem}__{provider_name}"
                # Сырой OCR-текст.
                raw_file = args.out / f"{stem}.txt"
                with raw_file.open("w", encoding="utf-8") as fh:
                    for i, text in enumerate(page_texts):
                        fh.write(f"=== стр. {i + 1} ===\n{text}\n\n")
                # Нормализованный OCR-текст для диффа с эталоном.
                norm_file = args.out / f"{stem}.norm.txt"
                with norm_file.open("w", encoding="utf-8") as fh:
                    fh.write(normalize(" ".join(page_texts)))
                    fh.write("\n")
                # Нормализованный эталон (один раз на PDF, но сохранить рядом).
                if reference is not None:
                    ref_out = args.out / f"{pdf_path.stem}__REF.norm.txt"
                    if not ref_out.exists():
                        ref_out.write_text(reference + "\n", encoding="utf-8")

            _print_provider_result(
                provider_name,
                error,
                elapsed,
                page_texts,
                reference,
                verbose=args.verbose,
                out=sys.stdout,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
