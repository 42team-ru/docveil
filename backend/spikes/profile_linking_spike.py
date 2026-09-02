"""Спайк распознавания реквизитов в DOCX-документе.

Загружает договор, находит сущности с надёжными формальными правилами и
выводит их вместе с расположением в исходном документе.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "src")

from masker.detect.rules import detect_by_rules  # noqa: E402
from masker.ingest.docx_ingest import ingest_docx  # noqa: E402

DEFAULT_DOCUMENT = Path("fixtures/labeled/contract_01.docx")


def main() -> int:
    """Распознать реквизиты в переданном DOCX или в тестовом договоре."""
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DOCUMENT
    doc = ingest_docx(path)
    entities = detect_by_rules(doc.segments)

    print(f"Документ: {doc.path}")
    print(f"Сегментов: {len(doc.segments)}")
    print(f"Найдено сущностей: {len(entities)}")

    for entity in entities:
        segment = doc.segments[entity.segment_order]
        print(
            f"{entity.type.value:<14} {entity.text:<26} "
            f"({segment.anchor.label}, {entity.start}:{entity.end})"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
