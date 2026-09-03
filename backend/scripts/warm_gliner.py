"""Скачать GLiNER2 в явный локальный каталог для офлайн-исполнения."""

from __future__ import annotations

import argparse
from pathlib import Path

MODEL_ID = "fastino/gliner2-privacy-filter-PII-multi"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("models/gliner"))
    args = parser.parse_args()

    from huggingface_hub import snapshot_download

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=MODEL_ID, local_dir=output)
    size = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    print(f"GLiNER2: {output} ({size / 1024**3:.2f} GiB)")


if __name__ == "__main__":
    main()
