"""Сколько текста реально надо отдать модели в верификаторе Р7.

Первая редакция Р7 предполагала «весь документ одним вызовом». Замер
показывает, во что это обходится на настоящем 46-страничном договоре и
насколько дешевле обходится фильтр по кандидатам.

Запуск (из backend/):
    .venv/bin/python spikes/verifier_payload_spike.py [путь.pdf]

Оценка токенов грубая: для кириллицы ~2.5 символа на токен. Точная цифра
зависит от токенизатора провайдера, но порядок величины она передаёт, а
спор идёт именно о порядке.
"""

from __future__ import annotations

import functools
import re
import sys

from natasha import MorphVocab

from masker.detect import DetectAgent, default_detectors
from masker.ingest.pdf_ingest import ingest_pdf

CHARS_PER_TOKEN = 2.5
WINDOW = 80

#: Заглавное слово или аббревиатура — грубый признак имени собственного.
WORD = re.compile(r"[А-ЯЁ][а-яё]+|[А-ЯЁ]{2,}")
#: Название в кавычках — почти детерминированный признак организации.
ORG_QUOTED = re.compile(r'[«"„][^»"‟]{2,40}[»"‟]')

_vocab = MorphVocab()


@functools.lru_cache(maxsize=100_000)
def name_grammemes(word: str) -> frozenset[str]:
    """Граммемы OpenCorpora, указывающие на имя собственное."""
    found: set[str] = set()
    for form in _vocab(word):
        tag = str(getattr(form, "tag", ""))
        for key in ("Surn", "Name", "Patr", "Geox"):
            if key in tag:
                found.add(key)
    return frozenset(found)


def _tokens(chars: int) -> int:
    return int(chars / CHARS_PER_TOKEN)


def main(path: str) -> None:
    document = ingest_pdf(path)
    text = document.text()
    pages = len({segment.anchor.locator[1] for segment in document.segments})

    result = DetectAgent(default_detectors()).detect(document)
    entities = result.entities if hasattr(result, "entities") else result
    covered = {entity.segment_order for entity in entities}

    windows: list[str] = []
    for segment in document.segments:
        if segment.order in covered:
            continue
        spans = [m.span() for m in WORD.finditer(segment.text) if name_grammemes(m.group())]
        spans += [m.span() for m in ORG_QUOTED.finditer(segment.text)]
        if not spans:
            continue
        start = max(0, min(s[0] for s in spans) - WINDOW)
        end = min(len(segment.text), max(s[1] for s in spans) + WINDOW)
        windows.append(segment.text[start:end])

    unique = {
        re.sub(r"\s+", " ", re.sub(r"\d+", "#", window.strip().casefold())) for window in windows
    }

    whole = len(text)
    windowed = sum(len(w) for w in windows)
    deduped = sum(len(u) for u in unique)

    print(f"{path}")
    print(f"  страниц {pages}, сегментов {len(document.segments)}, символов {whole}")
    print(f"  сегментов с находками детекторов: {len(covered)}")
    print(f"  сегментов-кандидатов: {len(windows)}, уникальных окон: {len(unique)}")
    print()
    print(f"  весь документ:   {_tokens(whole):>7} токенов   100.0%")
    print(f"  окна кандидатов: {_tokens(windowed):>7} токенов   {100 * windowed / whole:>5.1f}%")
    print(f"  после дедупа:    {_tokens(deduped):>7} токенов   {100 * deduped / whole:>5.1f}%")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "fixtures/labeled/contract_pdf_02_school.pdf")
