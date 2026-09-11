"""Аргументы CLI: совместимый argparse-интерфейс с читаемой справкой."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import NoReturn

from masker.highlight import highlight_background_argument
from masker.model import EntityType

DEFAULT_OUTPUT = Path("out") / "inspect"


class FriendlyParser(argparse.ArgumentParser):
    """Короткая ошибка с понятным следующим действием вместо простыни usage."""

    def error(self, message: str) -> NoReturn:
        self.exit(2, f"ошибка: {message}\nПодсказка: masker --help\n")


def parse_types(value: str) -> frozenset[EntityType]:
    """Разобрать ``all`` или список типов, сообщив пользователю допустимые значения."""
    if value.casefold() == "all":
        return frozenset(EntityType)
    names = [name.strip().casefold() for name in value.split(",") if name.strip()]
    if not names:
        raise ValueError("список типов пуст")
    try:
        return frozenset(EntityType(name) for name in names)
    except ValueError as error:
        allowed = ", ".join(entity_type.value for entity_type in EntityType)
        raise ValueError(f"неизвестный тип {error.args[0]!r}; допустимы: all, {allowed}") from error


#: Имя команды в справке и примерах — то, что человек реально набирает.
PRODUCT_COMMAND = "docveil"


def build_parser() -> argparse.ArgumentParser:
    """Создать справку, разделённую по обычному сценарию, LLM и продолжению."""
    parser = FriendlyParser(
        prog=PRODUCT_COMMAND,
        description="Обезличить PII в DOCX/PDF через графовый конвейер.",
        epilog=(
            "Примеры:\n"
            f"  {PRODUCT_COMMAND} договор.docx --redact-style both\n"
            f"  {PRODUCT_COMMAND} scan.pdf --rules-only --out out/scan\n"
            f"  {PRODUCT_COMMAND} договор.docx --dry-run --types inn,passport\n"
            f"  {PRODUCT_COMMAND} --resume THREAD_ID --answers answers.json --out out/inspect"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    input_group = parser.add_argument_group("Вход и результат")
    input_group.add_argument("files", nargs="*", type=Path, help="файлы .docx/.pdf; не с --resume")
    input_group.add_argument(
        "--out", type=Path, default=DEFAULT_OUTPUT, help=f"каталог результатов ({DEFAULT_OUTPUT})"
    )
    input_group.add_argument(
        "--types", default="all", help="all или типы через запятую: inn,person"
    )
    input_group.add_argument(
        "--rules-only", action="store_true", help="без Natasha — только регулярки/контрольные суммы"
    )
    input_group.add_argument(
        "--redact-style",
        choices=["marker", "blackbox", "both"],
        default=None,
        metavar="STYLE",
        help="marker → masked_highlight.*; blackbox → masked_black.*; both — оба",
    )
    flags, keyword_args = highlight_background_argument()
    input_group.add_argument(*flags, **keyword_args)
    ux_group = parser.add_argument_group("Интерфейс")
    ux_group.add_argument("--quiet", action="store_true", help="печатать только ошибки")
    ux_group.add_argument(
        "--verbose", action="store_true", help="показывать ленту завершённых стадий"
    )
    ux_group.add_argument(
        "--dry-run",
        action="store_true",
        help="показать операцию, не вызывать граф и не писать файлы",
    )
    llm_group = parser.add_argument_group("Профили и модель")
    llm_group.add_argument(
        "--profile", action="store_true", help="профили и вердикты судьи в report.json"
    )
    llm_group.add_argument("--llm-config", type=Path, help="YAML-конфиг LLM; требует --profile")
    llm_group.add_argument(
        "--allow-remote-pii", action="store_true", help="разрешить отправку PII в удалённую LLM"
    )
    llm_group.add_argument(
        "--llm-trace", action="store_true", help="записать llm-trace.jsonl/.md; требует --profile"
    )
    flow_group = parser.add_argument_group("Вопросы и продолжение")
    flow_group.add_argument(
        "--ask",
        action="store_true",
        help="остановиться на вопросах, записать questions.json, код 10; требует --profile",
    )
    flow_group.add_argument(
        "--answers", type=Path, help="файл ответов JSON; допустим без --ask и с --resume"
    )
    flow_group.add_argument(
        "--resume", metavar="THREAD_ID", help="продолжить приостановленный прогон"
    )
    flow_group.add_argument(
        "--thread-id", dest="thread_id", help="идентификатор прогона вместо детерминированного"
    )
    flow_group.add_argument(
        "--state-db", type=Path, help="файл чекпойнтера (по умолчанию <--out>/state.sqlite)"
    )
    flow_group.add_argument("--fresh", action="store_true", help="удалить тред и начать заново")
    flow_group.add_argument(
        "--unmask-critical",
        action="store_true",
        help="разрешить снятие маски с критичных типов/профилей (первое из двух подтверждений)",
    )
    flow_group.add_argument(
        "--output-format",
        choices=["original", "pdf"],
        default="original",
        dest="output_format",
        help="формат вывода для картинок: original — исходный формат, pdf — одностраничный PDF",
    )
    return parser
