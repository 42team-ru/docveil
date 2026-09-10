"""Записать ответы живого GigaChat в кассеты для воспроизводимых ворот.

Зачем это отдельная ручная операция, а не часть `make gate`. Ворота обязаны
давать побайтово одинаковый результат на одном и том же входе, а живая модель
такого обещать не может: сегодня ответила так, завтра иначе — и непонятно,
качество упало или модель поменяла настроение. Плюс ворота должны работать
без сети. Поэтому модель спрашивают ОДИН раз, ответ сохраняют, и дальше
`CassetteProvider` проигрывает запись.

Ровно поэтому же GigaChat не попадает в дев-петлю: правило проекта из
AGENTS.md — «GigaChat продуктовый и в дев-петлю не тащится», а сеть в тестах
разрешена как часть приёмки. Один прогон записи и есть эта приёмка.

Скрипт повторяет тот же путь, которым идут ворота
(`eval._profile_judge_metrics`): ingest → DetectAgent → ProfileAgent. Иначе
ключи кассет не совпадут: ключ считается от точного набора сообщений, и
любое расхождение в промпте сделает запись бесполезной.

Запуск (нужна сеть до GigaChat и ключ в окружении):

    cd backend
    set -a; . ./.env; set +a
    .venv/bin/python scripts/record_cassettes.py

Без сертификата Минцифры соединение не встанет; отключить проверку TLS —
осознанно и только на время записи:

    .venv/bin/python scripts/record_cassettes.py --insecure-tls

Записанные кассеты коммитятся отдельно от кода: это данные, а не логика.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR / "src"))

#: Модель freemium-режима для физических лиц. Другие доступные:
#: GigaChat-2, GigaChat-2-Pro, GigaChat-2-Max — они тарифицируются иначе.
DEFAULT_MODEL = "GigaChat-3-Ultra"


class _RecordingProvider:
    """Прозрачная обёртка: спрашивает живую модель и запоминает ответ.

    Ключ считается той же функцией `cassette_key`, что и при чтении, —
    поэтому записанное гарантированно найдётся при проигрывании.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.recorded: dict[str, str] = {}

    def complete(self, messages: list[Any], *, schema: dict[str, Any] | None = None) -> str:
        from masker.llm.cassette import cassette_key

        response = self._inner.complete(messages, schema=schema)
        self.recorded[cassette_key(messages)] = response
        return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"модель (по умолчанию {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--insecure-tls",
        action="store_true",
        help="не проверять сертификат сервера — только если нет корневого сертификата Минцифры",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=BACKEND_DIR / "fixtures" / "llm" / "roles",
        help="каталог кассет",
    )
    args = parser.parse_args()

    credentials = os.environ.get("GIGACHAT_CREDENTIALS", "")
    if not credentials:
        print("Нет GIGACHAT_CREDENTIALS в окружении.", file=sys.stderr)
        print("Подставьте ключ:  set -a; . ./.env; set +a", file=sys.stderr)
        return 2

    from masker.detect.agent import DetectAgent
    from masker.eval import FIXTURES, _ingest, load_corpus
    from masker.llm.gigachat import GigaChatProvider
    from masker.profile import ProfileAgent

    live = GigaChatProvider(
        credentials=credentials,
        model=args.model,
        verify_ssl_certs=not args.insecure_tls,
    )
    if args.insecure_tls:
        print("ВНИМАНИЕ: проверка сертификата отключена, ключ уходит по непроверенному каналу.\n")

    recorder = _RecordingProvider(live)
    corpus = load_corpus(FIXTURES)
    print(f"Документов в корпусе: {len(corpus)}, модель: {args.model}\n")

    failures = 0
    for path, _labels in corpus:
        before = len(recorder.recorded)
        try:
            document = _ingest(path)
            detection = DetectAgent().detect(document)
            ProfileAgent(recorder).profile(document, detection)
        except Exception as error:
            failures += 1
            print(f"  ✗ {path.name}: {type(error).__name__}: {error}")
            continue
        added = len(recorder.recorded) - before
        print(f"  ✓ {path.name}: запросов к модели {added}")

    if not recorder.recorded:
        print("\nМодель не вызывалась ни разу: у всех профилей роль определена эвристикой.")
        print("Записывать нечего — это факт о корпусе, а не ошибка.")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    # Имя файла — от ключа: так повторная запись обновляет ту же кассету,
    # а не плодит дубли с разными именами и одинаковым содержимым.
    for key, response in sorted(recorder.recorded.items()):
        target = args.out / f"roles-{key[:12]}.json"
        target.write_text(
            json.dumps({"key": key, "response": response}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"\nЗаписано кассет: {len(recorder.recorded)} → {args.out}")
    if failures:
        print(f"Документов с ошибкой: {failures} — разберите их перед коммитом.")
    print("Проверьте содержимое, затем закоммитьте кассеты отдельным коммитом.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
