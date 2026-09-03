"""Слой детекции PII."""

from collections.abc import Sequence

from masker.detect.address import AddressDetector
from masker.detect.agent import DetectAgent
from masker.detect.base import EntityDetector
from masker.detect.ner import NatashaDetector, memoize_tagger, natasha_tagger
from masker.detect.org_rules import OrgFormDetector
from masker.detect.result import DetectionResult, PiiChunk, build_pii_chunks
from masker.detect.rules import RuleDetector, detect_by_rules
from masker.typeconfig import CustomTypeSpec


def default_detectors(custom_specs: Sequence[CustomTypeSpec] = ()) -> list[EntityDetector]:
    """Стандартный офлайн-набор: точные правила, словарь оргформ (Д11,
    план T2.2.2, шаг 6) и локальная NER-модель."""
    tagger = memoize_tagger(natasha_tagger())
    detectors: list[EntityDetector] = [
        RuleDetector(),
        AddressDetector(tagger),
        OrgFormDetector(),
        NatashaDetector(tagger),
    ]
    if custom_specs:
        from masker.detect.config_detector import ConfigDetector

        detectors.insert(1, ConfigDetector(custom_specs))
        gliner_specs = [item for item in custom_specs if item.kind.startswith("gliner_")]
        if gliner_specs:
            from masker.detect.gliner import GlinerDetector

            detectors.append(GlinerDetector(gliner_specs))
    return detectors


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
