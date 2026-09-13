"""Замер качества сборки профилей сторон по корпусу документов.

Зачем отдельно от `masker.eval`. Там `_profile_judge_metrics` считает
`cluster_purity` по полю `entities[].party` в разметке, но это поле
заполнено только у одного файла корпуса `real-contracts` из 21
(`bashkirschool-usak-kichu2-4149.pdf`) — на остальных метрика молчит.
Здесь метрика структурная и не требует разметки сторон вовсе: сколько
профилей получилось, какой из них самый большой (признак склейки двух
сторон в один) и сколько профилей-одиночек (признак осыпания в пыль).

Ингест — без OCR (`_ingest` не создаёт `OCRProvider`), поэтому скан-страницы
молча пропускаются (`meta["scan_pages_skipped"]`), а не бросают
`OCRError: Кэш PaddleX не найден`. Документ пропускается только если после
этого сегментов не осталось вовсе (весь файл — скан).

LLM не подключается: у `ProfileAgent` роли уточняет модель, но структуру
блоков и кластеров — нет, а с ней сравнение стало бы недетерминированным.

    python scripts/check_profiles.py
    python scripts/check_profiles.py fixtures/labeled
    python scripts/check_profiles.py fixtures/real-contracts/open-contracts --json out.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import warnings
from typing import Any

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_READABLE = {".docx", ".pdf", ".xlsx"}
_DEFAULT_ROOT = ROOT / "fixtures" / "real-contracts" / "open-contracts"


def _iter_documents(root: pathlib.Path) -> list[pathlib.Path]:
    if root.is_file():
        return [root]
    return sorted(p for p in root.iterdir() if p.suffix.casefold() in _READABLE)


def _profile_row(path: pathlib.Path) -> dict[str, Any]:
    from masker.detect.agent import DetectAgent
    from masker.eval import _ingest
    from masker.profile.agent import ProfileAgent

    document = _ingest(path)
    if not document.segments:
        return {"document": path.name, "skipped": "скан без текстового слоя"}
    detection = DetectAgent().detect(document)
    result = ProfileAgent().profile(document, detection)
    sizes = sorted((len(profile.members) for profile in result.profiles), reverse=True)
    labeled = sum(1 for profile in result.profiles if profile.role_title)
    singles = sum(1 for size in sizes if size == 1)
    top = [
        (profile.marker_label, len(profile.members))
        for profile in sorted(result.profiles, key=lambda item: -len(item.members))[:3]
    ]
    return {
        "document": path.name,
        "segments": len(document.segments),
        "entities": len(detection.entities),
        "profilable": sum(len(block.entities) for block in result.blocks),
        "blocks": len(result.blocks),
        "blocks_labeled": sum(1 for block in result.blocks if block.label),
        "profiles": len(result.profiles),
        "profiles_labeled": labeled,
        "profiles_single": singles,
        "largest": sizes[0] if sizes else 0,
        "top": top,
    }


def _print_table(rows: list[dict[str, Any]]) -> None:
    header = (
        f"{'документ':<32} {'сегм':>5} {'сущн':>5} {'блок':>5} {'проф':>5} "
        f"{'одиноч':>6} {'макс':>5}  топ-3"
    )
    print(header)
    print("-" * len(header))
    profile_counts = []
    for row in rows:
        if "skipped" in row:
            print(f"{row['document']:<32} — {row['skipped']}")
            continue
        profile_counts.append(row["profiles"])
        top = ", ".join(f"{label} {size}" for label, size in row["top"])
        print(
            f"{row['document']:<32} {row['segments']:>5} {row['entities']:>5} "
            f"{row['blocks']:>5} {row['profiles']:>5} {row['profiles_single']:>6} "
            f"{row['largest']:>5}  {top}"
        )
    if profile_counts:
        print("-" * len(header))
        print(
            f"документов: {len(profile_counts)}; "
            f"профилей: сумма {sum(profile_counts)}, "
            f"медиана {statistics.median(profile_counts):.0f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "root",
        nargs="?",
        type=pathlib.Path,
        default=_DEFAULT_ROOT,
        help="файл или каталог корпуса (по умолчанию real-contracts/open-contracts)",
    )
    parser.add_argument("--json", type=pathlib.Path, help="сохранить таблицу в JSON")
    args = parser.parse_args()

    documents = _iter_documents(args.root)
    if not documents:
        parser.error(f"в {args.root} нет .docx/.pdf/.xlsx")
    rows = [_profile_row(path) for path in documents]
    _print_table(rows)
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nсохранено: {args.json}")


if __name__ == "__main__":
    main()
