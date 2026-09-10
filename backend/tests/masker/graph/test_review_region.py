"""bbox-правки оператора: `ManualEntityIn.region` (план feat/highlight-coords-edits, К2).

Без `region` оператор адресует значение текстом — движок ищет его по всему
документу (`test_review_round.py::test_manual_value_is_masked_everywhere_it_occurs`).
С `region` оператор обвёл место на превью: движок заводит искусственный
сегмент с якорем-bbox вместо текстового поиска — работает даже там, где
текстовый поиск не нашёл бы ничего (OCR ошибся, а человек прочитал верно).
"""

from __future__ import annotations

from pathlib import Path

from masker.graph.nodes import RunDeps
from masker.graph.review import SCHEMA_VERSION, parse_review_edits
from masker.run import RunOptions, resume_review, sqlite_checkpointer_factory, start_run

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_pdf_01.pdf"

#: Прямоугольник посреди первой страницы (595x842pt у фикстуры) — конкретные
#: координаты неважны, важно, что путь не зависит от текстового поиска.
_REGION = {"page": 0, "x0": 0.1, "y0": 0.1, "x1": 0.6, "y1": 0.15}


def _factory(tmp_path: Path):
    return sqlite_checkpointer_factory(tmp_path / "state.sqlite")


def _deps(tmp_path: Path) -> RunDeps:
    return RunDeps(artifact_dir=tmp_path / "artifacts")


def _reach_review(tmp_path: Path):
    options = RunOptions(
        rules_only=True,
        types=("inn",),
        interactive=False,
        review=True,
        styles=("marker",),
    )
    outcome = start_run(
        FIXTURE, options, checkpointer_factory=_factory(tmp_path), deps=_deps(tmp_path)
    )
    assert outcome.status == "waiting"
    return outcome


def test_manual_region_creates_entity_without_text_search(tmp_path: Path) -> None:
    """Значения, которого нет в тексте документа, текстовый поиск не найдёт —
    с `region` сущность всё равно появляется."""
    paused = _reach_review(tmp_path)
    text = "СВЕРХСЕКРЕТНОЕ_ЗНАЧЕНИЕ_НЕ_ИЗ_ТЕКСТА"
    assert text not in "\n".join(str(seg["text"]) for seg in paused.state["segments"])

    done = resume_review(
        paused.thread_id,
        {"manual": [{"type": "org_name", "text": text, "region": _REGION}]},
        checkpointer_factory=_factory(tmp_path),
        deps=_deps(tmp_path),
    )

    assert done.status == "done"
    added = [item for item in done.state["entities"] if item["source"] == "user"]
    assert any(item["text"] == text for item in added)


def test_manual_region_entity_gets_regions_and_round_survives(tmp_path: Path) -> None:
    """Регрессия на «забыли вернуть полный `segments`»: без него следующий
    проход графа (`plan → render → report`) не находит добавленный сегмент
    и падает или тихо теряет исходный документ. Заодно проверяет, что
    сущность получает `regions` на правильной странице в готовом отчёте."""
    paused = _reach_review(tmp_path)
    text = "ОБВЕДЕНО_РАМКОЙ_НА_ПРЕВЬЮ"

    done = resume_review(
        paused.thread_id,
        {"manual": [{"type": "org_name", "text": text, "region": _REGION}]},
        checkpointer_factory=_factory(tmp_path),
        deps=_deps(tmp_path),
    )

    assert done.status == "done"
    report = done.state["report"]
    matches = [e for e in report["entities"] if e["text"] == text]
    assert matches, "добавленная по region сущность обязана попасть в отчёт"
    entity = matches[0]
    assert entity["regions"], "у сущности, добавленной по region, должны быть regions"
    for region in entity["regions"]:
        assert region["page"] == 0
        assert 0.0 <= region["x0"] <= region["x1"] <= 1.0
        assert 0.0 <= region["y0"] <= region["y1"] <= 1.0

    # Исходный текст документа не потерялся вместе с добавленным сегментом.
    original_texts = {str(seg["text"]) for seg in paused.state["segments"]}
    survived_texts = {str(seg["text"]) for seg in done.state["segments"]}
    assert original_texts <= survived_texts


def test_manual_region_falls_back_to_text_search_when_page_unknown(tmp_path: Path) -> None:
    """`region` на несуществующей странице не роняет правку — деградирует к
    прежнему поведению (поиск текста по всему документу)."""
    paused = _reach_review(tmp_path)
    sample = str(paused.state["segments"][0]["text"]).split()[0]
    bad_region = {"page": 999, "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.2}

    done = resume_review(
        paused.thread_id,
        {"manual": [{"type": "org_name", "text": sample, "region": bad_region}]},
        checkpointer_factory=_factory(tmp_path),
        deps=_deps(tmp_path),
    )

    assert done.status == "done"
    added = [item for item in done.state["entities"] if item["source"] == "user"]
    assert any(item["text"] == sample for item in added)
    # Ни один добавленный сегмент не создан — сработал текстовый путь,
    # не bbox-путь (иначе segment_order указывал бы на новый сегмент).
    original_orders = {int(seg["order"]) for seg in paused.state["segments"]}
    assert all(int(item["segment_order"]) in original_orders for item in added)


def test_edits_with_malformed_region_are_dropped_not_rejected() -> None:
    """`_region()` защищает `_manual_entities` от произвольного словаря —
    некорректная форма region отбрасывается молча (как остальной мусор в
    конверте), а не роняет весь разбор."""
    parsed = parse_review_edits(
        {
            "schema_version": SCHEMA_VERSION,
            "edits": {
                "manual": [
                    {"type": "org_name", "text": "x", "region": {"page": 0, "x0": 0.5}},
                    {
                        "type": "org_name",
                        "text": "y",
                        "region": {"page": -1, "x0": 0, "y0": 0, "x1": 1, "y1": 1},
                    },
                    {"type": "org_name", "text": "z", "region": "not-a-dict"},
                ]
            },
        }
    )

    assert [item["type"] for item in parsed["manual"]] == ["org_name", "org_name", "org_name"]
    assert all("region" not in item for item in parsed["manual"])
