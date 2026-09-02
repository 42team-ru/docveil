"""Механическая полнота разметки всего корпуса, а не двух выбранных файлов.

`test_corpus_labels.py` проверяет два PDF поимённо — он писался под задачу
T2.2.1. Этот файл делает то же самое для **любого** документа корпуса, в том
числе добавленного завтра: новый файл без разметки или с неполной разметкой
роняет тест сам, без правки списка.

Проверка идёт через `scripts/label_candidates.py` — тот же инструмент, что
даёт агенту-разметчику список кандидатов. Это сознательно: если инструмент
разметки и проверка разметки разъедутся, агент будет считать работу
сделанной там, где ворота считают иначе.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "labeled"
sys.path.insert(0, str(ROOT / "scripts"))

from label_candidates import audit  # noqa: E402

DOCUMENTS = sorted(path for path in CORPUS.iterdir() if path.suffix.casefold() in (".docx", ".pdf"))

#: Кандидаты, отвергнутые разметчиком осознанно: значение похоже на тип по
#: форме, но им не является. Каждая строка — принятое решение, а не «пусть
#: тест позеленеет»: `8-82984602` — инвентарный номер морозильника из
#: таблицы оборудования, стоящий перед датой, а не телефон.
ACCEPTED_NON_ENTITIES: frozenset[tuple[str, str]] = frozenset(
    {("contract_pdf_02_school.pdf", "8-82984602 30")}
)


def test_corpus_is_not_empty() -> None:
    """Пустой корпус сделал бы остальные тесты этого файла бессмысленными."""
    assert DOCUMENTS, f"в {CORPUS} нет ни одного документа"


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: path.name)
def test_document_has_labels(document: Path) -> None:
    """У каждого документа корпуса есть разметка.

    Документ без разметки не участвует в `make eval` вовсе — то есть лежит в
    репозитории и молча ничего не проверяет. Ровно так `contract_pdf_01.pdf`
    прожил до T2.2.1.
    """
    result = audit(document)
    assert result.has_labels, f"нет разметки: {result.labels_path.name}"


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: path.name)
def test_labels_are_well_formed(document: Path) -> None:
    """Форма разметки: известный тип, нет лишних пробелов, нет должности в ФИО,
    и каждое значение действительно встречается в тексте документа."""
    problems = audit(document).problems
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: path.name)
def test_no_checksummed_requisite_is_missing(document: Path) -> None:
    """Каждый реквизит с валидной контрольной суммой размечен.

    Пропущенный ИНН в разметке — это не «недочёт эталона»: recall по нему
    посчитается как 1.0 при любом поведении детектора, и ворота перестанут
    видеть настоящий пропуск на критичном типе.
    """
    result = audit(document)
    missing = [
        candidate
        for candidate in result.missing
        if (document.name, candidate.value) not in ACCEPTED_NON_ENTITIES
    ]
    assert missing == [], "не размечено: " + ", ".join(
        f"{candidate.type} {candidate.value}" for candidate in missing
    )
