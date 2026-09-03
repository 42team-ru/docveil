"""Загрузчик фикстуры спайка GLiNER.

Читает `spike_labels.json`, для источников из реальных DOCX сверяет актуальный
текст с эталоном (fail-fast), для синтетических — берёт текст прямо из json.
Возвращает плоский список `(phrase_id, text, spans)`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import docx  # python-docx
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "python-docx не установлен в текущем интерпретаторе. "
        "Для спайка запускай через uv run --with python-docx или из .venv проекта."
    ) from e


REPO_ROOT = Path(__file__).resolve().parents[2]
LABELS_PATH = Path(__file__).with_name("spike_labels.json")


def _load_docx_paragraphs(docx_path: Path) -> list[str]:
    doc = docx.Document(str(docx_path))
    return [p.text for p in doc.paragraphs]


def _load_docx_cells(docx_path: Path) -> list[str]:
    doc = docx.Document(str(docx_path))
    out: list[str] = []
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                out.append(cell.text)
    return out


def load_phrases() -> list[dict[str, Any]]:
    """Возвращает список фраз с текстом и спанами.

    Каждая запись: `{"id": str, "text": str, "spans": [ {type,text,start,end} ], "origin": "docx"|"synthetic"}`.
    """
    data = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    phrases: list[dict[str, Any]] = []

    for src in data.get("sources", []):
        docx_rel = src["docx"]
        docx_path = REPO_ROOT / docx_rel
        paragraphs = _load_docx_paragraphs(docx_path)
        cells = _load_docx_cells(docx_path)

        for p in src.get("paragraphs", []):
            idx = p["para_idx"]
            actual = paragraphs[idx]
            if actual != p["text"]:
                raise RuntimeError(
                    f"Параграф {idx} в {docx_rel} разъехался с фикстурой:\n"
                    f"  ожидалось: {p['text']!r}\n"
                    f"  фактически: {actual!r}"
                )
            for sp in p["spans"]:
                got = actual[sp["start"] : sp["end"]]
                if got != sp["text"]:
                    raise RuntimeError(
                        f"Span mismatch в {docx_rel}[{idx}]: {got!r} != {sp['text']!r}"
                    )
            phrases.append(
                {
                    "id": f"{Path(docx_rel).stem}::para{idx}",
                    "text": actual,
                    "spans": p["spans"],
                    "origin": "docx",
                }
            )

        for c in src.get("table_cells", []):
            expected = c["cell_text"]
            if expected not in cells:
                raise RuntimeError(f"Ячейка {expected!r} не найдена в {docx_rel}")
            for sp in c["spans"]:
                got = expected[sp["start"] : sp["end"]]
                if got != sp["text"]:
                    raise RuntimeError(
                        f"Span mismatch в table cell {docx_rel} {expected!r}: {got!r} != {sp['text']!r}"
                    )
            phrases.append(
                {
                    "id": f"{Path(docx_rel).stem}::cell::{expected[:20]}",
                    "text": expected,
                    "spans": c["spans"],
                    "origin": "docx",
                }
            )

    for f in data.get("synthetic", []):
        for sp in f["spans"]:
            got = f["text"][sp["start"] : sp["end"]]
            if got != sp["text"]:
                raise RuntimeError(
                    f"Span mismatch в synthetic {f['id']}: {got!r} != {sp['text']!r}"
                )
        phrases.append(
            {
                "id": f"synthetic::{f['id']}",
                "text": f["text"],
                "spans": f["spans"],
                "origin": "synthetic",
            }
        )

    return phrases


if __name__ == "__main__":
    phrases = load_phrases()
    total_spans = sum(len(p["spans"]) for p in phrases)
    print(f"Загружено {len(phrases)} фраз, {total_spans} спанов")
    for p in phrases:
        print(f"  [{p['origin']:9s}] {p['id']:40s} | spans={len(p['spans'])}")
