"""Механическая часть разметки документа для корпуса ворот.

Разметка делится на две половины. Механическая — «какие числа в тексте
проходят контрольную сумму, какие строки похожи на почту, телефон, номер
договора, название в кавычках» — считается здесь и не требует суждения.
Содержательная — «это организация или орган власти», «где кончается ФИО»,
«какая сторона» — остаётся человеку или агенту-разметчику.

Скрипт ничего не пишет в разметку сам: он печатает кандидатов и сверяет их
с уже существующим `<файл>.labels.json`, отдельно называя пропущенное. Это
сознательно: разметка — эталон, по которому меряется детектор, и если её
генерировать тем же кодом, что и детектор, ворота станут декоративными.

    .venv/bin/python scripts/label_candidates.py fixtures/labeled/contract_09.pdf
    .venv/bin/python scripts/label_candidates.py fixtures/labeled/*.pdf --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from masker.detect.checksums import (
    is_valid_account,
    is_valid_bik,
    is_valid_inn,
    is_valid_ogrn,
    is_valid_snils,
)
from masker.ingest.docx_ingest import ingest_docx
from masker.ingest.pdf_ingest import ingest_pdf
from masker.model import EntityType

#: Ролевые и должностные слова: с них не имеет права начинаться `person`.
#: Пункт 6 схемы разметки — «Директора Зубрицкой» это должность плюс фамилия.
ROLE_PREFIXES = (
    "директор",
    "генеральн",
    "заказчик",
    "исполнител",
    "поставщик",
    "покупател",
    "арендатор",
    "арендодател",
    "учредител",
    "представител",
    "руководител",
    "заведующ",
    "главн",
    "начальник",
    "в лице",
)

#: Число целиком, без склейки соседних через пробел. Склеивать нельзя:
#: «БИК 016577551 к/сч 40102810…» иначе даёт несуществующий десятизначный
#: хвост, случайно проходящий контрольную сумму ИНН.
_DIGIT_TOKEN = re.compile(r"(?<!\d)\d{5,20}(?!\d)")
#: СНИЛС — единственный реквизит с канонической группировкой через пробелы.
_SNILS_GROUPED = re.compile(r"(?<!\d)\d{3}[-\s]\d{3}[-\s]\d{3}[-\s]\d{2}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
#: Телефон обязан иметь хотя бы один разделитель и не быть куском счёта:
#: 20 цифр подряд содержат внутри себя валидную по форме «восьмёрку».
_PHONE = re.compile(r"(?<!\d)(?:\+7|8)[\s(-]+\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)")
_QUOTED = re.compile(r"[«\"]([^«»\"]{2,80})[»\"]")
_CONTRACT_NO = re.compile(r"№\s*([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9./-]{4,30})")


@dataclass(frozen=True, slots=True)
class Candidate:
    """Кандидат в разметку: значение, предполагаемый тип и почему он предложен."""

    value: str
    type: str
    reason: str


@dataclass(slots=True)
class Audit:
    """Итог сверки кандидатов с существующей разметкой одного документа."""

    path: Path
    labels_path: Path
    has_labels: bool
    candidates: list[Candidate] = field(default_factory=list)
    missing: list[Candidate] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def read_text(path: Path) -> str:
    """Текст документа через штатный ingest, пробелы схлопнуты до одного.

    Схлопывание обязательно: разметка сравнивается с текстом в однострочной
    форме, иначе перенос строки внутри значения делает совпадение невозможным.
    """
    document = ingest_pdf(path) if path.suffix.casefold() == ".pdf" else ingest_docx(path)
    return " ".join(" ".join(segment.text for segment in document.segments).split())


def _digit_runs(text: str) -> Iterator[str]:
    for match in _DIGIT_TOKEN.finditer(text):
        yield match.group(0)
    for match in _SNILS_GROUPED.finditer(text):
        yield re.sub(r"[-\s]", "", match.group(0))


#: Метка слева от числа. Контрольная сумма у ИНН и ОГРН слабая: случайное
#: число нужной длины проходит её примерно раз из десяти, поэтому число без
#: метки рядом попадает в «решить», а не в обязательные к разметке.
_LABELS: dict[str, tuple[str, ...]] = {
    EntityType.INN: ("инн",),
    EntityType.OGRN: ("огрн",),
    EntityType.SNILS: ("снилс",),
    EntityType.BIK: ("бик",),
    EntityType.BANK_ACCOUNT: ("сч", "счёт", "счет"),
}


def _labelled_nearby(text: str, start: int, entity_type: str) -> bool:
    window = text[max(0, start - 40) : start].casefold()
    return any(label in window for label in _LABELS.get(entity_type, ()))


def find_requisites(text: str) -> list[Candidate]:
    """Числа, проходящие контрольную сумму, — механическая часть полноты.

    Счёт проверяется в паре с БИК: собственной контрольной суммы у него нет,
    поэтому перебираются все девятизначные кандидаты документа.
    """
    positions: dict[str, int] = {}
    for run in _digit_runs(text):
        positions.setdefault(run, text.find(run))
    biks = [run for run in positions if len(run) == 9 and is_valid_bik(run)]
    found: list[Candidate] = []

    def add(run: str, entity_type: str, reason: str) -> None:
        certain = _labelled_nearby(text, positions[run], entity_type)
        found.append(
            Candidate(run, entity_type, reason if certain else f"{reason}, метки нет — решить")
        )

    for run in positions:
        if len(run) in (10, 12) and is_valid_inn(run):
            add(run, EntityType.INN, "контрольная сумма ИНН")
        if len(run) in (13, 15) and is_valid_ogrn(run):
            add(run, EntityType.OGRN, "контрольная сумма ОГРН")
        if len(run) == 11 and is_valid_snils(run):
            add(run, EntityType.SNILS, "контрольная сумма СНИЛС")
        if len(run) == 9 and is_valid_bik(run):
            add(run, EntityType.BIK, "формат БИК")
        if len(run) == 20 and any(is_valid_account(run, bik) for bik in biks):
            add(run, EntityType.BANK_ACCOUNT, "ключ счёта сошёлся с БИК")
    return found


def find_contacts(text: str) -> list[Candidate]:
    """Почта и телефоны — форма однозначна, суждение не нужно."""
    found = [
        Candidate(match.group(0), EntityType.EMAIL, "форма адреса почты")
        for match in _EMAIL.finditer(text)
    ]
    found += [
        Candidate(" ".join(match.group(0).split()), EntityType.PHONE, "форма телефона")
        for match in _PHONE.finditer(text)
    ]
    return found


def find_hints(text: str) -> list[Candidate]:
    """Подсказки, требующие решения человека: кавычки и номера после «№».

    Не кандидаты в чистом виде: в кавычках бывает и название организации, и
    название блюда, а после «№» — и номер договора, и номер школы. Печатаются
    отдельным списком именно поэтому.
    """
    found = [
        Candidate(match.group(1).strip(), EntityType.ORG_NAME, "текст в кавычках — решить")
        for match in _QUOTED.finditer(text)
    ]
    found += [
        Candidate(
            match.group(1).strip(),
            EntityType.CONTRACT_NUMBER,
            "значение после № — решить",
        )
        for match in _CONTRACT_NO.finditer(text)
    ]
    return found


#: Типы, у которых значение — число: сравниваются по цифрам, потому что
#: «112 233 445 95» и «11223344595» — один и тот же СНИЛС, а группировка
#: пробелами в документе и в разметке совпадать не обязана. Телефон здесь же:
#: «+7(343)360- 62-28», разорванный переносом строки, — тот же номер, а не
#: второе значение.
_NUMERIC_TYPES = frozenset(
    {
        EntityType.INN,
        EntityType.KPP,
        EntityType.OGRN,
        EntityType.SNILS,
        EntityType.BIK,
        EntityType.BANK_ACCOUNT,
        EntityType.PHONE,
    }
)


def _key(value: str, entity_type: str) -> str:
    """Форма для сравнения: у чисел — только цифры, у остального — текст."""
    if entity_type in _NUMERIC_TYPES:
        return re.sub(r"\D", "", value)
    return " ".join(value.split())


def _dedup(candidates: list[Candidate]) -> list[Candidate]:
    seen: dict[tuple[str, str], Candidate] = {}
    for candidate in candidates:
        seen.setdefault((candidate.value, candidate.type), candidate)
    return list(seen.values())


def load_labels(labels_path: Path) -> list[dict[str, Any]]:
    """Существующая разметка или пустой список, если её ещё нет."""
    if not labels_path.exists():
        return []
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    entities: list[dict[str, Any]] = payload.get("entities", [])
    return entities


def check_labels(entities: list[dict[str, Any]], text: str) -> list[str]:
    """Проверки формы разметки, не требующие суждения.

    Ловит ровно те ошибки, которые уже случались: два пробела внутри
    значения, должность внутри ФИО, неизвестный тип и значение, которого
    нет в тексте документа (опечатка разметчика).
    """
    known = {entity_type.value for entity_type in EntityType}
    problems: list[str] = []
    for entity in entities:
        value = entity.get("text", "")
        entity_type = entity.get("type", "")
        if entity_type not in known:
            problems.append(f"неизвестный тип {entity_type!r} у {value!r}")
        if "  " in value or value != value.strip():
            problems.append(f"лишние пробелы в {value!r}")
        if entity_type == EntityType.PERSON:
            lowered = value.casefold()
            for prefix in ROLE_PREFIXES:
                if lowered.startswith(prefix):
                    problems.append(f"должность внутри ФИО: {value!r}")
                    break
        collapsed = " ".join(value.split())
        digits_only = re.sub(r"\D", "", collapsed)
        present = collapsed in text or (
            entity_type in _NUMERIC_TYPES
            and bool(digits_only)
            and digits_only in re.sub(r"\D", "", text)
        )
        if collapsed and not present:
            problems.append(f"значения нет в тексте документа: {value!r}")
    return problems


def audit(path: Path) -> Audit:
    """Собрать кандидатов по документу и сверить с его разметкой."""
    labels_path = path.with_suffix("").with_suffix(".labels.json")
    if labels_path.suffix != ".json":  # у файла без второго суффикса
        labels_path = path.parent / f"{path.stem}.labels.json"
    text = read_text(path)
    entities = load_labels(labels_path)
    labelled = {
        _key(str(entity.get("text", "")), str(entity.get("type", ""))) for entity in entities
    }

    found = _dedup(find_requisites(text) + find_contacts(text))
    certain = [c for c in found if "решить" not in c.reason]
    hints = _dedup([c for c in found if "решить" in c.reason] + find_hints(text))
    return Audit(
        path=path,
        labels_path=labels_path,
        has_labels=labels_path.exists(),
        candidates=certain + hints,
        missing=[c for c in certain if _key(c.value, c.type) not in labelled],
        problems=check_labels(entities, text),
    )


def _print_human(result: Audit) -> None:
    print(f"\n=== {result.path}")
    print(f"разметка: {result.labels_path}" + ("" if result.has_labels else " — НЕТ"))
    certain = [c for c in result.candidates if "решить" not in c.reason]
    hints = [c for c in result.candidates if "решить" in c.reason]
    print(f"\nМеханические кандидаты ({len(certain)}) — обязаны быть в разметке:")
    for candidate in certain:
        mark = "  " if candidate.value not in {c.value for c in result.missing} else "ПРОПУЩЕН "
        print(f"  {mark}{candidate.type:14} {candidate.value:24} ({candidate.reason})")
    print(f"\nТребуют решения ({len(hints)}) — организация или блюдо, договор или школа:")
    for candidate in hints:
        print(f"    {candidate.type:14} {candidate.value!r} ({candidate.reason})")
    if result.problems:
        print(f"\nПроблемы в существующей разметке ({len(result.problems)}):")
        for problem in result.problems:
            print(f"    {problem}")
    print(f"\nИТОГ: пропущено {len(result.missing)}, проблем {len(result.problems)}")


def main(argv: list[str] | None = None) -> int:
    """Код 0 — пропущенного и проблем нет; 1 — есть что доразметить."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="документы .docx/.pdf")
    parser.add_argument("--json", action="store_true", help="машинный вывод")
    args = parser.parse_args(argv)

    results = [audit(path) for path in args.files]
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "path": str(r.path),
                        "labels": str(r.labels_path),
                        "has_labels": r.has_labels,
                        "missing": [{"type": c.type, "text": c.value} for c in r.missing],
                        "hints": [
                            {"type": c.type, "text": c.value}
                            for c in r.candidates
                            if "решить" in c.reason
                        ],
                        "problems": r.problems,
                    }
                    for r in results
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for result in results:
            _print_human(result)
    return 1 if any(r.missing or r.problems for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
