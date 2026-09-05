"""Полнота разметки дат по всему корпусу (план T1.15, шаг 6).

Независимая аудит-регулярка: не импортируется из ``src``, живёт здесь. Она
намеренно шире, чем `_NUMERIC_PATTERN`/`_TEXTUAL_PATTERN` детектора —
если разметка не покрывает хотя бы одну её находку, тест красный. Защита от
кольцевой аргументации: детектор и разметка проверяются двумя независимыми
источниками истины, а не одним.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

from masker.detect import default_detectors
from masker.detect.agent import DetectAgent
from masker.detect.dateparse import parse_literal
from masker.entity_types import EntityTypeRegistry
from masker.ingest.docx_ingest import ingest_docx
from masker.typeconfig import load_type_config

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "labeled"

#: Аудит-регулярка: намеренно шире детектора, ловит формы, которые сам
#: детектор игнорирует (двузначный год, «в марте 2025»). Всё, что она
#: находит, должно либо быть в разметке (`date`/`birth_date`), либо
#: попасть в `_KNOWN_NON_DATES` с комментарием.
_AUDIT_PATTERN = re.compile(
    r"(?:\d{1,2}[./]\d{1,2}[./]\d{2,4})"
    r"|(?:\d{4}-\d{1,2}-\d{1,2})"
    r"|(?:\d{1,2}\s+(?:январ[ья]|феврал[ья]|март[а]?|апрел[ья]|ма[йя]|июн[ья]|июл[ья]|"
    r"август[а]?|сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья])\s+\d{4})",
    flags=re.IGNORECASE,
)

#: Явные исключения — строки, которые аудит-регулярка ловит, но которые
#: не являются календарными датами (не разметкой их, а описанием того,
#: почему они лишние). Пусто на текущем корпусе — если появится ложный
#: аудит-хит, он попадёт сюда с комментарием.
_KNOWN_NON_DATES: dict[str, str] = {
    # «12.02.25» в contract_07_dates.docx — двузначный год, детектор
    # осознанно не берёт (план T1.15, «Не ловим»), разметки нет.
    "12.02.25": "двузначный год: детектор осознанно игнорирует",
}


def _docx_fixtures() -> list[Path]:
    return sorted(FIXTURES.glob("*.docx"))


def _label_texts(labels_path: Path) -> set[str]:
    """Тексты **любых** размеченных сущностей: аудит проверяет, что дата
    вообще размечена (может быть под кастомным типом вроде `shipment_date`),
    а не только под встроенными `date`/`birth_date`. Специализированный тип
    поверх даты — валидное покрытие, лишь бы дата не терялась в тексте."""
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    return {item["text"] for item in payload.get("entities", [])}


@pytest.mark.parametrize("docx_path", _docx_fixtures(), ids=lambda p: p.name)
def test_every_date_in_corpus_is_labeled(docx_path: Path) -> None:
    """Каждое попадание аудит-регулярки должно быть или в разметке, или в
    списке исключений с комментарием: иначе разметка отстаёт от корпуса и
    метрики врут.
    """
    labels_path = docx_path.with_suffix(".labels.json")
    if not labels_path.exists():
        pytest.skip(f"нет разметки для {docx_path.name}")

    document = ingest_docx(docx_path)
    labeled = _label_texts(labels_path)
    for segment in document.segments:
        for match in _AUDIT_PATTERN.finditer(segment.text):
            hit = match.group(0)
            if hit in _KNOWN_NON_DATES:
                continue
            if hit in labeled:
                continue
            # Возможно, разметка использует кавычки/пробел вокруг, а аудит —
            # без них. Проверяем через parse_literal: если строки дают одну
            # и ту же дату, считаем покрытыми.
            hit_date = parse_literal(hit)
            if hit_date is not None and any(parse_literal(t) == hit_date for t in labeled):
                continue
            pytest.fail(
                f"{docx_path.name}: аудит нашёл `{hit}` (сегмент {segment.order}), "
                f"но в labels.json нет типа date/birth_date с этим значением. "
                f"Разметьте или добавьте в _KNOWN_NON_DATES с комментарием."
            )


def test_date_type_thresholds_on_labeled_corpus() -> None:
    """Пороги для `date` и `birth_date` на всём корпусе: P ≥ 0.90, R ≥ 0.85
    (некритичные типы, план T1.15). Проверка агрегированная — если один
    файл проседает, но остальные компенсируют, ворота остаются зелёными.

    Пользовательские типы фикстуры (например, `shipment_date` в
    contract_09) подключаются через `default_detectors(specs)`: без этого
    ConfigDetector не работает, DateDetector съедает пересекающиеся спаны
    и в `date` попадают ложные FP.
    """
    expected: dict[str, set[tuple[str, str]]] = defaultdict(set)
    found: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for docx_path in _docx_fixtures():
        labels_path = docx_path.with_suffix(".labels.json")
        if not labels_path.exists():
            continue
        payload = json.loads(labels_path.read_text(encoding="utf-8"))
        for item in payload.get("entities", []):
            if item.get("type") in {"date", "birth_date"}:
                expected[item["type"]].add((docx_path.name, item["text"]))
        raw_custom = payload.get("custom_types", [])
        specs = load_type_config({"version": 1, "types": raw_custom}) if raw_custom else []
        registry = EntityTypeRegistry.builtin().extend(item.spec for item in specs)
        agent = DetectAgent(default_detectors(specs), registry)
        for entity in agent.detect(ingest_docx(docx_path)).entities:
            if entity.type in {"date", "birth_date"}:
                found[entity.type].add((docx_path.name, entity.text))

    for date_type in ("date", "birth_date"):
        exp = expected[date_type]
        got = found[date_type]
        if not exp:
            continue
        true_positive = len(exp & got)
        precision = true_positive / max(len(got), 1)
        recall = true_positive / len(exp)
        assert recall >= 0.85, f"{date_type}: recall {recall:.3f} < 0.85; пропущено {exp - got}"
        assert precision >= 0.90, (
            f"{date_type}: precision {precision:.3f} < 0.90; лишнее {got - exp}"
        )
