"""Слой детекции PII."""

from masker.detect.address import AddressDetector
from masker.detect.agent import DetectAgent
from masker.detect.base import EntityDetector
from masker.detect.ner import NatashaDetector, memoize_tagger, natasha_tagger
from masker.detect.org_rules import OrgFormDetector
from masker.detect.result import DetectionResult, PiiChunk, build_pii_chunks
from masker.detect.rules import RuleDetector, detect_by_rules


def default_detectors() -> list[EntityDetector]:
    """Стандартный офлайн-набор: точные правила, словарь оргформ (Д11,
    план T2.2.2, шаг 6) и локальная NER-модель."""
    tagger = memoize_tagger(natasha_tagger())
    return [
        RuleDetector(),
        AddressDetector(tagger),
        OrgFormDetector(),
        NatashaDetector(tagger),
    ]


__all__ = [
    "AddressDetector",
    "DetectAgent",
    "DetectionResult",
    "EntityDetector",
    "NatashaDetector",
    "OrgFormDetector",
    "PiiChunk",
    "RuleDetector",
    "build_pii_chunks",
    "default_detectors",
    "detect_by_rules",
]
