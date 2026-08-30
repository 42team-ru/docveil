"""Слой детекции PII."""

from masker.detect.agent import DetectAgent
from masker.detect.address import AddressDetector
from masker.detect.base import EntityDetector
from masker.detect.ner import NatashaDetector
from masker.detect.result import DetectionResult, PiiChunk, build_pii_chunks
from masker.detect.rules import RuleDetector, detect_by_rules


def default_detectors() -> list[EntityDetector]:
    """Стандартный офлайн-набор: точные правила и локальная NER-модель."""
    return [RuleDetector(), AddressDetector(), NatashaDetector()]


__all__ = [
    "DetectAgent",
    "AddressDetector",
    "DetectionResult",
    "EntityDetector",
    "NatashaDetector",
    "PiiChunk",
    "RuleDetector",
    "build_pii_chunks",
    "default_detectors",
    "detect_by_rules",
]
