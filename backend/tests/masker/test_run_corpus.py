"""`run_corpus.py` не должен считать утечку успешным документом."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from masker.model import Leak, MaskPlan, ValidationReport
from masker.pipeline import MaskResult

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from run_corpus import run_corpus  # noqa: E402


def test_corpus_run_marks_validator_leak_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """М14: запланированная, но оставшаяся строка роняет corpus-прогон."""
    source = tmp_path / "source.pdf"
    source.touch()
    leak = Leak(
        kind="raw",
        artifact="masked_black.pdf",
        part="page 1",
        entity_type="email",
        value="signer@example.test",
        detail="исходная строка найдена побайтово",
    )
    result = MaskResult(
        plan=MaskPlan(replacements=(), groups=(), skipped=(), requested_types=()),
        validation=ValidationReport(
            leaked=(leak,),
            residual=(),
            checked_artifacts=("masked_black.pdf",),
            checked_parts=("masked_black.pdf:page 1",),
            ok=False,
        ),
        artifacts=(),
    )

    @contextmanager
    def leaking_mask_and_validate(*args: object, **kwargs: object) -> Iterator[MaskResult]:
        yield result

    monkeypatch.setattr("masker.pipeline.mask_and_validate", leaking_mask_and_validate)

    summary = run_corpus(
        tmp_path,
        layer="rules",
        llm_profile="none",
        out_root=tmp_path / "out",
        keep_artifacts=False,
    )

    assert summary["succeeded"] == 0
    assert summary["failed"] == 1
    assert summary["per_document"][0]["status"] == "leaked"
