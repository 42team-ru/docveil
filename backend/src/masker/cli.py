"""CLI: единственный вызывающий графа (T1.10, шаг 9).

Разбор аргументов, LLM-конфиг, вызов ``start_run``/``resume_run``, запись
``report.json``/``questions.json``/``report.html``, печать, коды возврата.
Детекция, план, рендер, валидация и сборка структуры отчёта — в узлах
графа; сюда предметная логика обратно не тащится.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from masker.graph.build import compile_graph
from masker.graph.nodes import RunDeps
from masker.graph.questions import parse_answers
from masker.llm import (
    LLMError,
    LLMProvider,
    TracingProvider,
    get_provider,
    load_llm_config,
    write_trace,
)
from masker.model import EntityType
from masker.ocr.select import select_ocr
from masker.report.html import render_html_report
from masker.run import (
    AlreadyFinishedError,
    RunFailedError,
    RunOptions,
    RunOutcome,
    ThreadExistsError,
    UnknownThreadError,
    artifacts_of,
    report_of,
    resume_run,
    sqlite_checkpointer_factory,
    start_run,
)

DEFAULT_OUTPUT = Path("out") / "inspect"

#: 0 успех, 2 argparse, 3 ошибка треда, 4 утечка, 5 RunFailedError, 10 пауза.
EXIT_LEAK = 4
EXIT_RUN_FAILED = 5

_SUPPORTED_SUFFIXES = frozenset({".docx", ".pdf"})

#: ``--redact-style`` → ``RunOptions.styles`` (решение Р1 плана T1.10):
#: ``marker`` → ``masked_highlight.*``, ``blackbox`` → ``masked_black.*``,
#: ``both`` — оба сразу.
_STYLES_BY_REDACT_OPTION: dict[str, tuple[str, ...]] = {
    "marker": ("marker",),
    "blackbox": ("blackbox",),
    "both": ("marker", "blackbox"),
}


def _parse_types(value: str) -> frozenset[EntityType]:
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _run_options_from_args(
    args: argparse.Namespace,
    selected_types: frozenset[EntityType],
    *,
    source: Path,
    interactive: bool,
) -> RunOptions:
    """Опции графа из CLI. ``styles``/``preview`` вне ``thread_id`` (T1.10, раздел 4).

    PDF всегда ``profile=False`` (риск R5): человек в цикле и профили для
    PDF не реализованы (T2.2 покрывает только детекцию).
    """
    types_tuple = (
        None
        if selected_types == frozenset(EntityType)
        else tuple(sorted(entity_type.value for entity_type in selected_types))
    )
    profile = args.profile and source.suffix.casefold() != ".pdf"
    return RunOptions(
        types=types_tuple,
        rules_only=args.rules_only,
        profile=profile,
        unmask_critical=args.unmask_critical,
        llm_config_id=str(args.llm_config) if args.llm_config is not None else "",
        interactive=interactive,
        styles=_STYLES_BY_REDACT_OPTION.get(args.redact_style, ()),
        preview=True,
    )


def _state_db_path(args: argparse.Namespace) -> Path:
    state_db: Path | None = args.state_db
    out: Path = args.out
    return state_db if state_db is not None else out / "state.sqlite"


def _print_questions(outcome: RunOutcome, questions_path: Path) -> None:
    assert outcome.payload is not None
    print(f"thread_id: {outcome.thread_id}")
    print(f"вопросов: {len(outcome.payload['questions'])}")
    for question in outcome.payload["questions"]:
        options_text = ", ".join(question["options"])
        print(f"  [{question['id']}] {question['prompt']} — варианты: {options_text}")
    print(f"  файл вопросов: {questions_path}")
    print(
        "  для ответа: masker --resume "
        f"{outcome.thread_id} --answers <файл> --out <тот же --out> --profile"
    )


def _load_answers(path: Path, parser: argparse.ArgumentParser) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        parser.error(f"не удалось прочитать --answers {path}: {error}")
        raise AssertionError("unreachable") from error
    except json.JSONDecodeError as error:
        parser.error(f"--answers {path} не является корректным JSON: {error}")
        raise AssertionError("unreachable") from error
    try:
        return parse_answers(raw)
    except ValueError as error:
        parser.error(str(error))
        raise AssertionError("unreachable") from error


def _load_llm(args: argparse.Namespace, parser: argparse.ArgumentParser) -> LLMProvider | None:
    if args.llm_config is None:
        return None
    try:
        config = load_llm_config(args.llm_config)
        if config.provider != "fake" and not args.allow_remote_pii:
            parser.error("OpenRouter получит исходные PII и контекст; добавьте --allow-remote-pii")
        return get_provider(config)
    except LLMError as error:
        parser.error(str(error))
    except ValueError as error:
        parser.error(str(error))
    raise AssertionError("unreachable")


def _print_leaks(source: Path, report: dict[str, Any]) -> bool:
    """Утечки — в stderr (диагностика), report.json["leaked"] — для машин."""
    leaked = report.get("leaked") or []
    if not leaked:
        return False
    print(f"{source}: найдены утечки в артефакте ({len(leaked)}):", file=sys.stderr)
    for item in leaked:
        print(
            f"  [{item['kind']}] {item['entity_type']} в {item['artifact']}:{item['part']} "
            f"— {item['value']!r} ({item['detail']})",
            file=sys.stderr,
        )
    return True


def _finish(
    source: Path,
    outcome: RunOutcome,
    artifact_dir: Path,
    args: argparse.Namespace,
    *,
    trace_paths: tuple[Path, Path] | None,
) -> int:
    """Записать report.json (+report.html), напечатать сводку, вернуть код."""
    report = report_of(outcome)
    report_path = artifact_dir / "report.json"
    _write_json(report_path, report)
    # Шаблон HTML читает покрытие DOCX; у PDF оно другой формы, рендер упал бы.
    html_wanted = bool(args.html) and report["format"] == "docx"
    if args.html and not html_wanted:
        print(f"{source}: --html поддержан только для DOCX, report.html не создан")
    html_path = artifact_dir / "report.html" if html_wanted else None
    if html_path is not None:
        render_html_report(report, source, html_path)
    print(f"{source}: прогон завершён, thread_id {outcome.thread_id}")
    print(f"  отчёт: {report_path}")
    for item in artifacts_of(outcome):
        print(f"  {item['role']}: {item['path']}")
    if html_path is not None:
        print(f"  HTML:  {html_path}")
    if args.profile and "profile_judge" in report:
        profile_judge = report["profile_judge"]
        print(
            "  профили: "
            f"{len(profile_judge['profiles'])}; LLM-вызовы: {profile_judge['llm_calls']}; "
            f"вопросы: {len(profile_judge['questions'])}"
        )
        for diagnostic in profile_judge["diagnostics"]:
            print(f"  диагностика LLM: {diagnostic}")
    if trace_paths is not None:
        trace_jsonl, trace_markdown = trace_paths
        print(f"  LLM-трейс:  {trace_jsonl}")
        print(f"  LLM-трейс (человекочитаемый): {trace_markdown}")
        print(
            "  ВНИМАНИЕ: файлы llm-trace содержат исходные PII в открытом виде "
            "и не предназначены для передачи наружу."
        )
    leaked = _print_leaks(source, report)
    print("ВАЖНО: preview содержит исходный текст и служит только для проверки детектора.")
    return EXIT_LEAK if leaked else 0


def _start(
    source: Path,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    selected_types: frozenset[EntityType],
    llm: LLMProvider | None,
    *,
    interactive: bool,
) -> int:
    """Начать прогон файла через граф.

    ``interactive`` — только при ``--ask``/``--answers``: вправе
    приостановиться на ``ask_human``, ``--fresh`` берётся с CLI как есть.
    Пакетный прогон нескольких файлов — всегда ``fresh=True`` (T1.10, шаг
    9), иначе второй прогон того же файла упрётся в ``AlreadyFinishedError``.
    """
    artifact_dir = args.out / source.stem
    factory = sqlite_checkpointer_factory(_state_db_path(args))
    options = _run_options_from_args(args, selected_types, source=source, interactive=interactive)

    tracer: TracingProvider | None = None
    run_llm = llm
    if args.llm_trace and llm is not None:
        tracer = TracingProvider(llm)
        run_llm = tracer
    deps = RunDeps(llm=run_llm, tracer=tracer, artifact_dir=artifact_dir, ocr=select_ocr())
    pre_answers = _load_answers(args.answers, parser) if args.answers is not None else None

    try:
        outcome = start_run(
            source,
            options,
            checkpointer_factory=factory,
            deps=deps,
            thread_id=args.thread_id,
            fresh=args.fresh if interactive else True,
            answers=pre_answers,
        )
    except (UnknownThreadError, AlreadyFinishedError, ThreadExistsError) as error:
        print(str(error))
        return 3
    except RunFailedError as error:
        print(str(error), file=sys.stderr)
        return EXIT_RUN_FAILED

    if outcome.status == "waiting":
        questions_path = artifact_dir / "questions.json"
        assert outcome.payload is not None
        _write_json(questions_path, outcome.payload)
        _print_questions(outcome, questions_path)
        return 10

    trace_paths = write_trace(artifact_dir, tracer) if tracer is not None else None
    return _finish(source, outcome, artifact_dir, args, trace_paths=trace_paths)


def _resume(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Вторая фаза: прислать ответы на приостановленный прогон.

    Каталог артефактов зависит от имени файла первой фазы (``meta.name``),
    уже лежащего в чекпойнте на паузе ``ask_human``: читается через
    ``get_state`` без выполнения узлов, чтобы ``render_node`` внутри
    ``resume_run`` сразу писал в правильный каталог (T1.10, шаг 9).
    """
    if args.answers is None:
        parser.error("--resume требует --answers")
    answers = _load_answers(args.answers, parser)
    factory = sqlite_checkpointer_factory(_state_db_path(args))

    with factory() as saver:
        graph = compile_graph(RunDeps(), saver)
        snapshot = graph.get_state({"configurable": {"thread_id": args.resume}})
    name = str((snapshot.values or {}).get("meta", {}).get("name") or "")
    stem = Path(name).stem if name else args.resume
    artifact_dir = args.out / stem

    try:
        outcome = resume_run(
            args.resume,
            answers,
            checkpointer_factory=factory,
            deps=RunDeps(artifact_dir=artifact_dir),
        )
    except (UnknownThreadError, AlreadyFinishedError) as error:
        print(str(error))
        return 3
    except RunFailedError as error:
        print(str(error), file=sys.stderr)
        return EXIT_RUN_FAILED

    if outcome.status == "waiting":
        questions_path = artifact_dir / "questions.json"
        assert outcome.payload is not None
        _write_json(questions_path, outcome.payload)
        _print_questions(outcome, questions_path)
        return 10

    source = Path(str(outcome.state["path"]))
    return _finish(source, outcome, artifact_dir, args, trace_paths=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="masker",
        description="Обезличить PII в DOCX/PDF через графовый конвейер, создать report.json.",
    )
    parser.add_argument("files", nargs="*", type=Path, help="файлы .docx/.pdf; не с --resume")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUTPUT, help=f"каталог результатов ({DEFAULT_OUTPUT})"
    )
    parser.add_argument("--types", default="all", help="all или типы через запятую: inn,person")
    parser.add_argument(
        "--rules-only", action="store_true", help="без Natasha — только регулярки/контрольные суммы"
    )
    parser.add_argument("--html", action="store_true", help="создать report.html (только DOCX)")
    parser.add_argument(
        "--redact-style",
        choices=["marker", "blackbox", "both"],
        default=None,
        metavar="STYLE",
        help="marker → masked_highlight.*; blackbox → masked_black.*; both — оба",
    )
    parser.add_argument(
        "--profile", action="store_true", help="профили и вердикты судьи в report.json"
    )
    parser.add_argument("--llm-config", type=Path, help="YAML-конфиг LLM; требует --profile")
    parser.add_argument(
        "--allow-remote-pii", action="store_true", help="разрешить отправку PII в удалённую LLM"
    )
    parser.add_argument(
        "--llm-trace",
        action="store_true",
        help="записать llm-trace.jsonl/.md рядом с report.json; требует --profile",
    )
    parser.add_argument(
        "--ask",
        action="store_true",
        help="остановиться на вопросах, записать questions.json, код 10; требует --profile",
    )
    parser.add_argument(
        "--answers", type=Path, help="файл ответов (JSON); допустим без --ask и с --resume"
    )
    parser.add_argument("--resume", metavar="THREAD_ID", help="продолжить приостановленный прогон")
    parser.add_argument(
        "--thread-id", dest="thread_id", help="идентификатор прогона вместо детерминированного"
    )
    parser.add_argument(
        "--state-db", type=Path, help="файл чекпойнтера (по умолчанию <--out>/state.sqlite)"
    )
    parser.add_argument("--fresh", action="store_true", help="удалить тред и начать заново")
    parser.add_argument(
        "--unmask-critical",
        action="store_true",
        help="разрешить снятие маски с критичных типов/профилей (первое из двух подтверждений)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.files and args.resume is None:
        parser.error("нужны файлы или --resume THREAD_ID")
    if args.files and args.resume is not None:
        parser.error("--resume не принимает позиционные файлы")
    if args.ask and not args.profile:
        parser.error("--ask требует --profile")
    if args.answers is not None and args.resume is None and not args.profile:
        parser.error("--answers без --resume требует --profile")
    if args.unmask_critical and args.resume is None and not args.profile:
        parser.error("--unmask-critical требует --profile (или используйте вместе с --resume)")
    if args.thread_id is not None and args.resume is not None:
        parser.error("--thread-id не сочетается с --resume: идентификатор уже задан позиционно")

    try:
        selected_types = _parse_types(args.types)
    except ValueError as error:
        parser.error(str(error))

    if args.resume is not None:
        return _resume(args, parser)

    invalid = [
        path
        for path in args.files
        if not path.is_file() or path.suffix.casefold() not in _SUPPORTED_SUFFIXES
    ]
    if invalid:
        parser.error(
            "ожидались существующие DOCX или PDF: " + ", ".join(str(path) for path in invalid)
        )

    if args.llm_config is not None and not args.profile:
        parser.error("--llm-config требует --profile")
    if args.allow_remote_pii and args.llm_config is None:
        parser.error("--allow-remote-pii требует --llm-config")
    if args.llm_trace and not args.profile:
        parser.error("--llm-trace требует --profile")
    if (args.ask or args.answers is not None) and len(args.files) != 1:
        parser.error("--ask/--answers без --resume работают ровно с одним файлом")

    llm = _load_llm(args, parser)

    if args.llm_trace and llm is None:
        print("--llm-trace: LLM не подключена (--llm-config не задан), трейс не будет записан.")

    if args.ask or args.answers is not None:
        return _start(args.files[0], args, parser, selected_types, llm, interactive=True)

    any_leaked = False
    for source in args.files:
        code = _start(source, args, parser, selected_types, llm, interactive=False)
        if code == EXIT_LEAK:
            any_leaked = True
        elif code != 0:
            return code
    return EXIT_LEAK if any_leaked else 0


if __name__ == "__main__":
    raise SystemExit(main())
