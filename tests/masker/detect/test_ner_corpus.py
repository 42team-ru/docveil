"""Пороги T1.3 для выхода DetectAgent до появления полного пайплайна."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache

from masker.detect import DetectAgent
from masker.detect.ner import NER_CONFIDENCE
from masker.eval import load_corpus, score
from masker.ingest.docx_ingest import ingest_docx
from masker.model import CRITICAL_TYPES, EntityType


@lru_cache(maxsize=1)
def _corpus_metrics() -> tuple[
    dict[str, dict[str, set[tuple[str, str]]]], dict[str, dict[str, float]]
]:
    by_type: dict[str, dict[str, set[tuple[str, str]]]] = defaultdict(
        lambda: {"expected": set(), "found": set()}
    )
    for path, labels in load_corpus():
        for item in labels["entities"]:
            by_type[item["type"]]["expected"].add((path.name, item["text"]))
        for entity in DetectAgent().detect(ingest_docx(path)).entities:
            by_type[entity.type.value]["found"].add((path.name, entity.text))

    metrics: dict[str, dict[str, float]] = {}
    for name in sorted(by_type):
        metrics[name] = score(by_type[name]["expected"], by_type[name]["found"])
    return by_type, metrics


def test_detect_agent_meets_labeled_corpus_thresholds() -> None:
    _by_type, metrics = _corpus_metrics()
    print(f"{'тип':<18}{'P':>7}{'R':>7}")
    for name in sorted(metrics):
        m = metrics[name]
        print(f"{name:<18}{m['precision']:>7.3f}{m['recall']:>7.3f}")

    for entity_type in CRITICAL_TYPES:
        name = entity_type.value
        assert metrics[name]["recall"] == 1.0
    for entity_type in (EntityType.PERSON, EntityType.ORG_NAME):
        m = metrics[entity_type.value]
        assert m["precision"] >= 0.90
        assert m["recall"] >= 0.85


def test_ner_confidence_is_calibrated() -> None:
    _by_type, metrics = _corpus_metrics()
    for entity_type in (EntityType.PERSON, EntityType.ORG_NAME):
        precision = metrics[entity_type.value]["precision"]
        assert precision - 0.20 <= NER_CONFIDENCE[entity_type] <= precision


def test_no_address_in_corpus() -> None:
    by_type, _metrics = _corpus_metrics()
    assert "address" not in by_type
