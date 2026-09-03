"""Обёртки для сравнения Natasha и Natasha+GLiNER в спайке.

Три виртуальные "модели":
- ``NatashaOnly`` — Natasha из проекта (со всей постобработкой в src/masker/detect/ner.py),
  но обёрнутая под интерфейс predict-like вызова из runner-а.
- ``NatashaRaw`` — тот же Natasha, но без постобработки (persons.py, orgforms.py,
  org_rules.py) — для сравнения "raw NER" vs "с костылями".
- ``NatashaGlinerCombo`` — Natasha primary, GLiNER (M4) добивает границы у ORG-спанов
  через окно ±50 chars (combo B из design notes T1.13).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Импорты из проекта — оба доступны, если запускаться так, что .venv проекта
# на sys.path, либо uv run --with даёт natasha в эфемерном env.

BOUNDARY_WINDOW = 50  # символов слева и справа для combo B


@dataclass
class _NatashaSpan:
    type: str
    start: int
    end: int
    text: str


def _run_natasha_processed(text: str) -> list[dict[str, Any]]:
    """Natasha со всей постобработкой проекта, применённая к одному тексту.

    Строим синтетический Document с одним Segment, вызываем NatashaDetector.detect,
    возвращаем список dict-ов в формате runner-а.
    """
    from masker.detect.ner import NatashaDetector
    from masker.model import Anchor, Document, Segment

    seg = Segment(text=text, anchor=Anchor(fmt="txt", locator=("body", 0)), order=0)
    doc = Document(path="<spike>", fmt="txt", segments=[seg])
    detector = NatashaDetector()
    entities = detector.detect(doc)
    out: list[dict[str, Any]] = []
    for e in entities:
        out.append({"type": e.type.value, "start": e.start, "end": e.end, "text": e.text})
    return out


def _run_natasha_raw(text: str) -> list[dict[str, Any]]:
    """Голая Natasha без нашей постобработки — сырые PER/ORG спаны."""
    from masker.detect.ner import natasha_tagger

    tagger = natasha_tagger()
    spans = tagger.spans(text)
    # LABEL_TO_TYPE в src/masker/detect/ner.py: PER→person, ORG→org_name.
    label_to_type = {"PER": "person", "ORG": "org_name", "LOC": "location"}
    out: list[dict[str, Any]] = []
    for s in spans:
        t = label_to_type.get(s.label)
        if t is None:
            continue
        out.append({"type": t, "start": s.start, "end": s.end, "text": text[s.start : s.end]})
    return out


class NatashaOnly:
    """Natasha со всей постобработкой проекта."""

    kind = "natasha"

    def predict(self, text: str, *_ignored, **__ignored) -> list[dict[str, Any]]:
        return _run_natasha_processed(text)


class NatashaRaw:
    """Natasha без нашей постобработки — сырой PER/ORG/LOC."""

    kind = "natasha_raw"

    def predict(self, text: str, *_ignored, **__ignored) -> list[dict[str, Any]]:
        return _run_natasha_raw(text)


class NatashaGlinerCombo:
    """Natasha primary + GLiNER (M2 fastino/gliner2.5-multi-v1) для расширения
    границ ORG-спанов.

    Combo B из design notes T1.13:
    1. Natasha ищет person/org_name/location — берём результат как есть
       (со всеми костылями из orgforms/persons/org_rules).
    2. Для каждого ORG-спана — GLiNER на окне ±BOUNDARY_WINDOW chars, ищет
       свой ORG-span. Если он *содержит* Natasha-спан и длиннее — заменяем
       Natasha-версию на GLiNER-версию.
    3. Person/location не трогаем — Natasha на них по спайку сильна, GLiNER
       только добавит FP.
    """

    kind = "natasha_gliner_combo"

    def __init__(self, gliner_model) -> None:
        """gliner_model — уже загруженная GLiNER2 модель (M2)."""
        self._gliner = gliner_model

    def predict(self, text: str, *_ignored, **__ignored) -> list[dict[str, Any]]:
        natasha_ents = _run_natasha_processed(text)
        extended: list[dict[str, Any]] = []
        for ent in natasha_ents:
            if ent["type"] != "org_name":
                extended.append(ent)
                continue
            win_start = max(0, ent["start"] - BOUNDARY_WINDOW)
            win_end = min(len(text), ent["end"] + BOUNDARY_WINDOW)
            window_text = text[win_start:win_end]
            # Ищем ORG в окне через GLiNER (RU labels + description как в S3).
            g_result = self._gliner.extract_entities(
                window_text,
                {
                    "название организации": "название юридического лица: ООО, АО, ИП, полная или сокращённая форма"
                },
                threshold=0.5,
            )
            # Формат GLiNER2: {'entities': {label: [text, ...]}}
            candidates: list[tuple[int, int, str]] = []
            if isinstance(g_result, dict) and "entities" in g_result:
                for _label, texts in g_result["entities"].items():
                    if not isinstance(texts, list):
                        continue
                    search_from = 0
                    from collections import Counter

                    for span_text, count in Counter(texts).items():
                        if not span_text:
                            continue
                        for _ in range(count):
                            idx = window_text.find(span_text, search_from)
                            if idx < 0:
                                break
                            candidates.append(
                                (win_start + idx, win_start + idx + len(span_text), span_text)
                            )
                            search_from = idx + len(span_text)
            # Ищем самый длинный кандидат, содержащий Natasha-спан
            best = ent
            for c_start, c_end, c_text in candidates:
                if (
                    c_start <= ent["start"]
                    and c_end >= ent["end"]
                    and (c_end - c_start) > (ent["end"] - ent["start"])
                ):
                    if not best or (c_end - c_start) > (best["end"] - best["start"]):
                        best = {"type": "org_name", "start": c_start, "end": c_end, "text": c_text}
            extended.append(best)
        return extended
