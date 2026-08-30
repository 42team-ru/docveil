"""Инварианты локального корпуса реальных документов, не входящего в git."""

from __future__ import annotations

from pathlib import Path

import pytest

from masker.detect import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.model import EntityType

PRIVATE_CORPUS = Path(__file__).resolve().parents[3] / "fixtures" / "private"


@pytest.mark.private
def test_private_corpus_invariants() -> None:
    paths = sorted(PRIVATE_CORPUS.glob("*.docx"))
    if not paths:
        pytest.skip("fixtures/private не содержит локальных DOCX")

    role_fragments = ("продав", "покупател", "должник", "поставщик")
    for path in paths:
        document = ingest_docx(path)
        segments = {segment.order: segment for segment in document.segments}
        entities = DetectAgent().detect(document).entities
        for entity in entities:
            print(
                path.name,
                entity.type.value,
                repr(entity.text),
                entity.source.value,
                f"{entity.confidence:.2f}",
            )
            assert entity.text.strip("_")
            assert entity.text == segments[entity.segment_order].text[entity.start : entity.end]
            if entity.type is EntityType.PERSON:
                folded = entity.text.casefold()
                assert not any(fragment in folded for fragment in role_fragments)
