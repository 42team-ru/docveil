"""Пороги T1.3 для выхода DetectAgent до появления полного пайплайна."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache

from masker.detect import DetectAgent
from masker.detect.ner import NER_CONFIDENCE
from masker.detect.normalize import normalize_value
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


def test_every_occurrence_of_critical_value_is_detected() -> None:
    failures: list[str] = []
    checked: set[tuple[str, EntityType, str]] = set()
    for path, labels in load_corpus():
        document = ingest_docx(path)
        entities = DetectAgent().detect(document).entities
        text = document.text()
        for item in labels["entities"]:
            entity_type = EntityType(item["type"])
            if entity_type not in CRITICAL_TYPES:
                continue
            expected_text = item["text"]
            key = (path.name, entity_type, expected_text)
            if key in checked:
                continue
            checked.add(key)
            normalized = normalize_value(entity_type, expected_text)
            expected_count = text.count(expected_text)
            found_count = sum(
                1
                for entity in entities
                if entity.type is entity_type and entity.normalized == normalized
            )
            if found_count != expected_count:
                failures.append(
                    f"{path.name}: {entity_type.value} {expected_text!r} "
                    f"найдено {found_count}, вхождений {expected_count}"
                )

    assert failures == []
