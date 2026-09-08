"""Сколько текста реально надо отдать модели в верификаторе Р7.

Первая редакция Р7 предполагала «весь документ одним вызовом». Замер
показывает, во что это обходится на настоящем 46-страничном договоре и
насколько дешевле обходится фильтр по кандидатам.

Исправлено вместе с задачей Р7 (08.09.2026): первая версия этого спайка
исключала из выборки СЕГМЕНТ целиком, если в нём сработал хоть один
детектор, — ресерч показал, что это ошибка (5 из 7 пропущенных gold-сущностей
лежали ровно в таких сегментах). Спайк больше не считает окна сам, а зовёт
`masker.detect.verifier.build_windows` — ту же функцию, что и продакшен-код
и тесты приёмки, чтобы цифра здесь и цифра в воротах не могли разойтись.

Запуск (из backend/):
    .venv/bin/python spikes/verifier_payload_spike.py [путь.pdf]

Оценка токенов грубая: для кириллицы ~2.5 символа на токен. Точная цифра
зависит от токенизатора провайдера, но порядок величины она передаёт, а
спор идёт именно о порядке.
"""

from __future__ import annotations

import sys

from masker.detect import DetectAgent, default_detectors
from masker.detect.verifier import DEFAULT_WINDOW_CHARS, build_windows
from masker.ingest.pdf_ingest import ingest_pdf

CHARS_PER_TOKEN = 2.5


def _tokens(chars: int) -> int:
    return int(chars / CHARS_PER_TOKEN)


def main(path: str) -> None:
    document = ingest_pdf(path)
    text = document.text()
    pages = len({segment.anchor.locator[1] for segment in document.segments})

    baseline = DetectAgent(default_detectors()).detect(document).entities

    windows = build_windows(document, baseline, window_chars=DEFAULT_WINDOW_CHARS)
    unique_texts = {window.text for window in windows}

    whole = len(text)
    windowed = sum(len(window.text) for window in windows)
    deduped = sum(len(value) for value in unique_texts)

    print(f"{path}")
    print(f"  страниц {pages}, сегментов {len(document.segments)}, символов {whole}")
    print(f"  сегментов с находками baseline: {len({e.segment_order for e in baseline})}")
    print(
        f"  окон-кандидатов: {len(windows)}, уникальных после точного дедупа: {len(unique_texts)}"
    )
    print()
    print(f"  весь документ:   {_tokens(whole):>7} токенов   100.0%")
    print(f"  окна кандидатов: {_tokens(windowed):>7} токенов   {100 * windowed / whole:>5.1f}%")
    print(f"  после дедупа:    {_tokens(deduped):>7} токенов   {100 * deduped / whole:>5.1f}%")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "fixtures/labeled/contract_pdf_02_school.pdf")
