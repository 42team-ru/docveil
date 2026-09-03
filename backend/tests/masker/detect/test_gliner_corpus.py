"""Замер F1 GLiNER2 на классе D — роль поверх одинакового формата.

T1.13.1, шаг 17. `shipment_date` и `signing_date` — обе `dd.mm.yyyy`,
формат совпадает буквально; различить их можно только по контексту вокруг
конкретного вхождения. Порог приёмки — F1 ≥ 0.9 (эмпирика спайка для M4:
0.928, запас всего 0.028). Если замер здесь даст меньше 0.9 — это повод
вернуться к модели M2 (план, раздел «Отвергнутые альтернативы»), а не
понижать порог.

Сравнение — по точной позиции (`segment_order`, `start`, `end`), не по
паре (тип, текст): обе роли делят одно и то же значение даты, наивное
сравнение «тип+текст» засчитало бы совпадение, даже перепутай модель, какое
вхождение к какой роли относится — то есть не поймало бы ровно то, что
класс D должен ловить.

Без extra `[gliner]` модуль целиком пропускается с явной строкой — молчаливый
пропуск выглядел бы как «метрика есть», а её нет.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

if importlib.util.find_spec("gliner2") is None:
    pytest.skip("пропущено: gliner не установлен", allow_module_level=True)

from masker.detect import DetectAgent, default_detectors
from masker.entity_types import EntityTypeRegistry
from masker.eval import score
from masker.ingest.docx_ingest import ingest_docx
from masker.model import Document
from masker.typeconfig import load_type_config

pytestmark = pytest.mark.gliner

FIXTURES = pathlib.Path(__file__).resolve().parents[3] / "fixtures" / "gliner"
DOC_PATH = FIXTURES / "contract_10_roles_dates.docx"
LABELS_PATH = FIXTURES / "contract_10_roles_dates.labels.json"

#: Порог приёмки шага 17 — не трогать без решения о смене модели (план,
#: раздел «Отвергнутые альтернативы», M2 против M4).
MIN_F1 = 0.9


def _payload() -> dict[str, object]:
    return json.loads(LABELS_PATH.read_text(encoding="utf-8"))


def _expected_spans(
    document: Document, class_d: list[dict[str, str]]
) -> set[tuple[str, int, int, int]]:
    """Позиция каждой роли внутри своего абзаца — по разу на abzац.

    Абзац найден по точному совпадению текста с `class_d["text"]`
    (`make_fixtures.contract_10_roles_dates`, докстринг). Подписание
    всегда упоминается раньше отгрузки в тексте абзаца (так построен
    сам абзац), поэтому первое вхождение даты — `signing_date`, второе —
    `shipment_date`.
    """
    by_text = {segment.text: segment.order for segment in document.segments}
    expected: set[tuple[str, int, int, int]] = set()
    for pair in class_d:
        text = pair["text"]
        date = pair["date"]
        order = by_text.get(text)
        assert order is not None, f"абзац класса D не найден среди сегментов документа: {text!r}"
        signing_start = text.index(date)
        signing_end = signing_start + len(date)
        shipment_start = text.index(date, signing_end)
        shipment_end = shipment_start + len(date)
        expected.add(("signing_date", order, signing_start, signing_end))
        expected.add(("shipment_date", order, shipment_start, shipment_end))
    return expected


def test_gliner_corpus_class_d() -> None:
    """F1 по `shipment_date`/`signing_date` на документе с одинаковым форматом обеих ролей.

    Через полный `DetectAgent` (тот же набор детекторов, что и в проде,
    `default_detectors`), не через голый `GlinerDetector`: `_carve` вычитает
    спаны с более высоким приоритетом (например, `contract_number` из
    `RuleDetector` на «№ 10/2026») — без этого шага замер штрафовал бы GLiNER
    за ложное срабатывание, которое реальный конвейер уже не пропускает.
    """
    payload = _payload()
    document = ingest_docx(DOC_PATH)
    specs = load_type_config({"version": 1, "types": payload["custom_types"]})
    registry = EntityTypeRegistry.builtin().extend(item.spec for item in specs)
    agent = DetectAgent(default_detectors(specs), registry)

    entities = agent.detect(document).entities
    found = {
        (entity.type, entity.segment_order, entity.start, entity.end)
        for entity in entities
        if entity.type in {"shipment_date", "signing_date"}
    }
    expected = _expected_spans(document, payload["class_d"])

    print(f"\n{'тип':<15}{'P':>7}{'R':>7}{'F1':>7}{'FN':>5}{'FP':>5}")
    results: dict[str, dict[str, float]] = {}
    for type_id in ("shipment_date", "signing_date"):
        exp = {item for item in expected if item[0] == type_id}
        got = {item for item in found if item[0] == type_id}
        metrics = score(exp, got)
        results[type_id] = metrics
        print(
            f"{type_id:<15}{metrics['precision']:>7.3f}{metrics['recall']:>7.3f}"
            f"{metrics['f1']:>7.3f}{metrics['fn']:>5}{metrics['fp']:>5}"
        )

    for type_id, metrics in results.items():
        assert metrics["f1"] >= MIN_F1, (
            f"класс D: F1 по {type_id} {metrics['f1']:.3f} < {MIN_F1} — запас модели M4 "
            "исчерпан, повод вернуться к M2 (план T1.13.1, раздел «Отвергнутые альтернативы»), "
            "а не понижать порог"
        )
