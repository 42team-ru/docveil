"""Записать ответы GigaChat для Д3 в кассеты, не запуская весь корпус.

Скрипт проходит только необходимый Д3 путь для явно переданных документов:
разбор → локальная детекция → локальное профилирование → тип и пересказ.
Поля договора собираются правилами и попадают в карточку с цитатами. Рендер,
маскирование, валидация и остальные документы корпуса сюда не входят.

Первый запуск обращается к GigaChat и сохраняет ответы в ``fixtures/llm/summary``.
Повторный на тех же входах использует уже записанный ответ, поэтому не создаёт
дубликатов и не расходует токены. Карточки для проверки глазами записываются
отдельно в ``out/llm-summary-cassettes/cards.md``; они содержат исходные
значения из открытых документов и не предназначены для передачи дальше.

После изменения промпта жанра 11.09.2026 ключи кассет намеренно изменятся:
владелец должен сделать третью запись пяти сценариев живым GigaChat, а не
подгонять новые сообщения под старые ответы.

    cd backend
    .venv/bin/python scripts/record_llm_cassettes.py
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

DEFAULT_PROFILE = "gigachat-max"
DEFAULT_DOCUMENTS = (
    BACKEND_DIR / "fixtures/real-contracts/open-contracts/arkhschool-68-183.pdf",
    BACKEND_DIR / "fixtures/real-contracts/open-contracts/brsc-contract.pdf",
    BACKEND_DIR / "fixtures/real-contracts/open-contracts/dagestanschool-kais-808.pdf",
    BACKEND_DIR / "fixtures/real-contracts/open-contracts/eat-654000009321.pdf",
    BACKEND_DIR / "fixtures/negative/negative_01_gost.docx",
)
DEFAULT_CASSETTES = BACKEND_DIR / "fixtures/llm/summary"
DEFAULT_CARDS = BACKEND_DIR / "out/llm-summary-cassettes"


class RecordingProvider:
    """Запомнить живой ответ по тому же ключу, что читает CassetteProvider."""

    def __init__(self, inner: Any, existing: dict[str, str]) -> None:
        self._inner = inner
        self.responses = dict(existing)
        self.recorded = 0
        self.reused = 0

    @property
    def provider_kind(self) -> str:
        """Пометить чистый повтор как cassette, чтобы стоимость была нулевой."""
        return "gigachat" if self.recorded else "cassette"

    def complete(self, messages: list[Any], *, schema: dict[str, Any] | None = None) -> str:
        return self.complete_with_usage(messages, schema=schema)[0]

    def complete_with_usage(
        self, messages: list[Any], *, schema: dict[str, Any] | None = None
    ) -> tuple[str, Any]:
        """Вернуть старую запись либо спросить модель и сохранить её дословно."""
        from masker.llm.cassette import cassette_key

        key = cassette_key(messages)
        if key in self.responses:
            self.reused += 1
            return self.responses[key], None
        complete_with_usage = getattr(self._inner, "complete_with_usage", None)
        if callable(complete_with_usage):
            response, usage = complete_with_usage(messages, schema=schema)
        else:
            response = self._inner.complete(messages, schema=schema)
            usage = None
        self.responses[key] = response
        self.recorded += 1
        return response, usage


def _read_cassettes(directory: Path) -> dict[str, str]:
    """Прочитать существующие кассеты и не затереть повреждённые данные."""
    if not directory.exists():
        return {}
    from masker.llm.cassette import _load_responses

    return _load_responses(directory)


def _write_cassettes(directory: Path, responses: dict[str, str]) -> None:
    """Записать по одному ответу на ключ; имя стабильно при повторном запуске."""
    directory.mkdir(parents=True, exist_ok=True)
    for key, response in sorted(responses.items()):
        target = directory / f"summary-{key[:12]}.json"
        target.write_text(
            json.dumps({"key": key, "response": response}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _format_card(path: Path, card: dict[str, object]) -> str:
    """Вернуть Markdown-карточку, достаточную для ручной проверки ответа."""
    kind = card["document_kind"]
    assert isinstance(kind, dict)
    status = str(kind["status"])
    genre = kind.get("genre") or "—"
    kind_text = {
        "contract": "договор",
        "non_contract": f"не договор; жанр: {genre}",
        "unknown": "тип не определён",
    }.get(status, status)
    lines = [
        f"## {path.name}",
        "",
        f"- Тип: **{kind_text}**.",
        f"- Краткое содержание: {card.get('brief_summary') or '—'}",
        "",
    ]
    if status == "non_contract":
        lines.extend(
            ["Поля договора не собирались: документ подтверждённо не является договором.", ""]
        )
        return "\n".join(lines)
    lines.extend(["### Поля договора", ""])
    for label, key in (
        ("Заказчик", "customer_fact"),
        ("Поставщик", "supplier_fact"),
        ("Номер", "contract_number_fact"),
        ("Сумма", "contract_amount_fact"),
    ):
        fact = card.get(key)
        if not isinstance(fact, dict) or not fact.get("value"):
            lines.append(f"- {label}: —")
            continue
        lines.append(f"- {label}: {fact['value']}")
        lines.append(f"  - Цитата: {fact.get('source_quote') or '—'}")
    for label, key in (("Оплата", "payment_facts"), ("Поставка", "delivery_facts")):
        facts = card.get(key)
        if not isinstance(facts, list) or not facts:
            lines.append(f"- {label}: —")
            continue
        for fact in facts:
            if isinstance(fact, dict):
                lines.append(f"- {label}: {fact.get('value') or '—'}")
                lines.append(f"  - Цитата: {fact.get('source_quote') or '—'}")
    laws = card.get("federal_law_facts")
    if not isinstance(laws, list) or not laws:
        lines.append("- ФЗ: —")
    else:
        for law in laws:
            if isinstance(law, dict):
                lines.append(f"- ФЗ: {law.get('value') or '—'}")
                lines.append(f"  - Цитата: {law.get('source_quote') or '—'}")
    lines.append("")
    return "\n".join(lines)


def _write_cards(directory: Path, cards: list[tuple[Path, dict[str, object]]]) -> Path:
    """Сохранить все карточки в один читаемый файл с ограниченным доступом."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "cards.md"
    text = ["# Д3: карточки живого прогона", ""]
    for path, card in cards:
        text.append(_format_card(path, card))
    target.write_text("\n".join(text), encoding="utf-8")
    target.chmod(0o600)
    return target


def _config_for_profile(profile: str) -> Any:
    """Выбрать профиль модели из masker.yaml, не копируя тариф в скрипт."""
    from masker.config import project_section
    from masker.llm.config import llm_config_from_mapping

    settings = dict(project_section("llm"))
    settings["profile"] = profile
    # Утилита записи всегда обязана использовать профиль из `--llm`: скрытая
    # переменная `MASKER_LLM=fake` не должна превратить живую приёмку в
    # успешный, но бесполезный офлайн-прогон.
    return llm_config_from_mapping(settings)


def record(
    documents: list[Path], *, profile: str, cassette_directory: Path, cards_directory: Path
) -> int:
    """Прогнать Д3 для документов, записать кассеты и вернуть код завершения."""
    from masker.detect import DetectAgent, default_detectors
    from masker.eval import _ingest
    from masker.llm import GigaChatProvider
    from masker.profile import ProfileAgent
    from masker.summary import build_document_card
    from masker.telemetry import MeteringProvider, empty_telemetry, report_telemetry

    missing = [path for path in documents if not path.is_file()]
    if missing:
        for path in missing:
            print(f"Нет документа: {path}", file=sys.stderr)
        return 2
    config = _config_for_profile(profile)
    if config.provider != "gigachat":
        print(
            f"Профиль {profile!r} выбрал {config.provider!r}, а для записи Д3 нужен gigachat.",
            file=sys.stderr,
        )
        return 2
    credentials = os.environ.get(config.api_key_env, "")
    if not credentials:
        print(
            f"Нет {config.api_key_env} в окружении. Экспортируйте ключ и повторите запуск.",
            file=sys.stderr,
        )
        return 2
    live = GigaChatProvider(
        credentials=credentials,
        model=config.model,
        scope=config.gigachat_scope,
        temperature=config.gigachat_temperature,
        timeout_seconds=config.timeout_seconds,
        ca_bundle_file=config.gigachat_ca_bundle_file or None,
        verify_ssl_certs=not config.gigachat_insecure_skip_tls_verify,
    )
    recorder = RecordingProvider(live, _read_cassettes(cassette_directory))
    meter = MeteringProvider(recorder, config.pricing)
    cards: list[tuple[Path, dict[str, object]]] = []
    failures = 0
    for path in documents:
        try:
            document = _ingest(path)
            detection = DetectAgent(default_detectors()).detect(document)
            profiles = ProfileAgent(None).profile(document, detection).profiles
            with meter.for_stage("summary"):
                summary = build_document_card(document, detection.entities, profiles, meter)
            card = summary.model_dump(mode="json")
            cards.append((path, card))
            kind = card["document_kind"]
            assert isinstance(kind, dict)
            print(
                f"✓ {path.name}: {kind['status']}; запросов Д3: {summary.llm_calls}; "
                f"полей суммы: {1 if summary.contract_amount else 0}"
            )
        except Exception as error:
            failures += 1
            print(f"✗ {path.name}: {type(error).__name__}: {error}", file=sys.stderr)
    if cards:
        cards_path = _write_cards(cards_directory, cards)
        print(f"Карточки для проверки: {cards_path}")
    _write_cassettes(cassette_directory, recorder.responses)
    telemetry = empty_telemetry(pricing=config.pricing)
    telemetry["llm"] = {"calls": meter.delta_since(0)[1]}
    usage = report_telemetry(telemetry, runtime_available=False)["llm"]
    assert isinstance(usage, dict), "report_telemetry должен вернуть объект llm"
    print(f"Кассет в каталоге: {len(recorder.responses)} → {cassette_directory}")
    print(f"Новых ответов: {recorder.recorded}; повторно использовано: {recorder.reused}")
    print(
        "Токены: "
        f"вход {usage['prompt_tokens']}, выход {usage['completion_tokens']}; {usage['message']}"
    )
    return 1 if failures else 0


def main() -> int:
    """Разобрать аргументы ручного прогона записи кассет Д3."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "documents", nargs="*", type=Path, help="документы вместо пяти рекомендуемых"
    )
    parser.add_argument(
        "--llm",
        default=DEFAULT_PROFILE,
        help=f"профиль из masker.yaml (по умолчанию {DEFAULT_PROFILE})",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_CASSETTES, help="каталог JSON-кассет")
    parser.add_argument(
        "--cards-out", type=Path, default=DEFAULT_CARDS, help="каталог Markdown-карточек"
    )
    args = parser.parse_args()
    return record(
        args.documents or list(DEFAULT_DOCUMENTS),
        profile=args.llm,
        cassette_directory=args.out,
        cards_directory=args.cards_out,
    )


if __name__ == "__main__":
    raise SystemExit(main())
