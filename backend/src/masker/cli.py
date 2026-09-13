"""CLI: единственный вызывающий графа (T1.10, шаг 9).

Разбор аргументов, LLM-конфиг, вызов ``start_run``/``resume_run``, запись
``report.json``/``questions.json``, печать, коды возврата.
Детекция, план, рендер, валидация и сборка структуры отчёта — в узлах
графа; сюда предметная логика обратно не тащится.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from masker.cli_args import build_parser, parse_types
from masker.cli_ui import CliPresenter, ensure_utf8_output
from masker.graph.build import compile_graph
from masker.graph.nodes import RunDeps
from masker.graph.questions import parse_answers
from masker.ingest import SUPPORTED_SUFFIXES, SUPPORTED_TITLES
from masker.llm import LLMError, LLMProvider, TracingProvider, resolve_cli_llm, write_trace
from masker.model import EntityType
from masker.ocr.select import select_ocr
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
    styles_for_redact_option,
)
from masker.telemetry import LLMPricing

#: 0 успех, 2 argparse, 3 ошибка треда, 4 утечка, 5 RunFailedError, 10 пауза.
EXIT_LEAK = 4
EXIT_RUN_FAILED = 5


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
    """Опции графа из CLI; PDF получает офлайн-профили сторон по умолчанию."""
    types_tuple = (
        None
        if selected_types == frozenset(EntityType)
        else tuple(sorted(entity_type.value for entity_type in selected_types))
    )
    # 11.09.2026: без структурного профиля PDF не может дать стороне один
    # номер во всех вхождениях. Это офлайн-кластеризация, а не отправка
    # документа в LLM; `--profile` по-прежнему нужен только для судьи/LLM.
    profile = args.profile or source.suffix.casefold() == ".pdf"
    return RunOptions(
        types=types_tuple,
        rules_only=args.rules_only,
        profile=profile,
        unmask_critical=args.unmask_critical,
        llm_config_id=str(args.llm_config) if args.llm_config is not None else "",
        interactive=interactive,
        styles=styles_for_redact_option(args.redact_style),
        preview=True,
        highlight_background=args.highlight_background,
        image_output_format=args.output_format,
    )


def _state_db_path(args: argparse.Namespace) -> Path:
    state_db: Path | None = args.state_db
    out: Path = args.out
    return state_db if state_db is not None else out / "state.sqlite"


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


def _load_llm(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> tuple[LLMProvider | None, LLMPricing | None]:
    """Ошибку конфигурации ``resolve_cli_llm`` превратить в код возврата 2."""
    try:
        return resolve_cli_llm(args.llm_config, allow_remote_pii=args.allow_remote_pii)
    except (LLMError, ValueError) as error:
        parser.error(str(error))
        raise AssertionError("unreachable") from error


def _finish(
    source: Path,
    outcome: RunOutcome,
    artifact_dir: Path,
    args: argparse.Namespace,
    *,
    trace_paths: tuple[Path, Path] | None,
    presenter: CliPresenter,
    elapsed_seconds: float,
) -> int:
    """Записать report.json, напечатать сводку, вернуть код."""
    report = report_of(outcome)
    report_path = artifact_dir / "report.json"
    _write_json(report_path, report)
    leaked = report.get("leaked") or []
    if leaked:
        print(f"{source}: найдены утечки в артефакте ({len(leaked)}):", file=sys.stderr)
        for item in leaked:
            print(
                f"  [{item['kind']}] {item['entity_type']} в {item['artifact']}:{item['part']} "
                f"— {item['value']!r} ({item['detail']})",
                file=sys.stderr,
            )
    presenter.result(
        source,
        report,
        artifacts_of(outcome),
        report_path,
        thread_id=outcome.thread_id,
        trace_paths=trace_paths,
        elapsed_seconds=elapsed_seconds,
    )
    return EXIT_LEAK if leaked else 0


def _start(
    source: Path,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    selected_types: frozenset[EntityType],
    llm: LLMProvider | None,
    pricing: LLMPricing | None,
    *,
    interactive: bool,
) -> int:
    """Начать прогон файла. Пакет файлов всегда ``fresh=True`` — иначе AlreadyFinishedError."""
    artifact_dir = args.out / source.stem
    factory = sqlite_checkpointer_factory(_state_db_path(args))
    options = _run_options_from_args(args, selected_types, source=source, interactive=interactive)
    presenter = CliPresenter(quiet=args.quiet, verbose=args.verbose)
    presenter.greet()

    tracer: TracingProvider | None = None
    run_llm = llm
    if args.llm_trace and llm is not None:
        tracer = TracingProvider(llm)
        run_llm = tracer
    deps = RunDeps(
        llm=run_llm,
        tracer=tracer,
        artifact_dir=artifact_dir,
        ocr=select_ocr(),
        signature=select_signature(),
        pricing=pricing,
        stage_observer=presenter.observe,
    )
    pre_answers = _load_answers(args.answers, parser) if args.answers is not None else None

    presenter.begin(source)
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
        presenter.finish_progress()
        print(str(error), file=sys.stderr)
        return 3
    except RunFailedError as error:
        presenter.finish_progress()
        print(str(error), file=sys.stderr)
        return EXIT_RUN_FAILED
    elapsed_seconds = presenter.finish_progress()

    if outcome.status == "waiting":
        questions_path = artifact_dir / "questions.json"
        assert outcome.payload is not None
        _write_json(questions_path, outcome.payload)
        presenter.questions(outcome.thread_id, outcome.payload["questions"], questions_path)
        presenter.info(
            "  для ответа: masker --resume "
            f"{outcome.thread_id} --answers <файл> --out <тот же --out> --profile"
        )
        return 10

    trace_paths = write_trace(artifact_dir, tracer) if tracer is not None else None
    try:
        return _finish(
            source,
            outcome,
            artifact_dir,
            args,
            trace_paths=trace_paths,
            presenter=presenter,
            elapsed_seconds=elapsed_seconds,
        )
    finally:
        meta = outcome.state.get("meta")
        if isinstance(meta, dict) and (p := meta.get("image_intermediate_pdf")):
            Path(str(p)).unlink(missing_ok=True)


def _resume(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Вторая фаза: ответы. ``meta.name`` читается через ``get_state``, без запуска узлов."""
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
    presenter = CliPresenter(quiet=args.quiet, verbose=args.verbose)
    presenter.begin(Path(name) if name else Path(args.resume))

    try:
        outcome = resume_run(
            args.resume,
            answers,
            checkpointer_factory=factory,
            deps=RunDeps(artifact_dir=artifact_dir, stage_observer=presenter.observe),
        )
    except (UnknownThreadError, AlreadyFinishedError) as error:
        presenter.finish_progress()
        print(str(error), file=sys.stderr)
        return 3
    except RunFailedError as error:
        presenter.finish_progress()
        print(str(error), file=sys.stderr)
        return EXIT_RUN_FAILED
    elapsed_seconds = presenter.finish_progress()

    if outcome.status == "waiting":
        questions_path = artifact_dir / "questions.json"
        assert outcome.payload is not None
        _write_json(questions_path, outcome.payload)
        presenter.questions(outcome.thread_id, outcome.payload["questions"], questions_path)
        return 10

    source = Path(str(outcome.state["path"]))
    return _finish(
        source,
        outcome,
        artifact_dir,
        args,
        trace_paths=None,
        presenter=presenter,
        elapsed_seconds=elapsed_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    # До любого разбора аргументов: `--help` печатается внутри argparse и на
    # однобайтовой консоли Windows падает раньше, чем мы что-либо покажем.
    ensure_utf8_output()
    command_args = sys.argv[1:] if argv is None else argv
    if command_args and command_args[0] == "tui":
        # Textual и весь интерфейс намеренно остаются вне CLI: этот модуль
        # продолжает быть тонким вызывающим для пакетного сценария.
        from masker.tui import launch_tui

        return launch_tui()
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
        selected_types = parse_types(args.types)
    except ValueError as error:
        parser.error(str(error))

    if args.resume is not None:
        return _resume(args, parser)

    invalid = [
        path
        for path in args.files
        if not path.is_file() or path.suffix.casefold() not in SUPPORTED_SUFFIXES
    ]
    if invalid:
        parser.error(
            f"ожидались существующие {SUPPORTED_TITLES}: "
            + ", ".join(str(path) for path in invalid)
        )

    if args.llm_config is not None and not args.profile:
        parser.error("--llm-config требует --profile")
    if args.allow_remote_pii and args.llm_config is None:
        parser.error("--allow-remote-pii требует --llm-config")
    if args.llm_trace and not args.profile:
        parser.error("--llm-trace требует --profile")
    if (args.ask or args.answers is not None) and len(args.files) != 1:
        parser.error("--ask/--answers без --resume работают ровно с одним файлом")

    if args.dry_run:
        presenter = CliPresenter(quiet=args.quiet, verbose=args.verbose)
        if args.resume is not None:
            presenter.info(
                f"прогон {args.resume}: предпросмотр продолжения, файлов не будет записано"
            )
        else:
            for source in args.files:
                presenter.dry_run(
                    source,
                    types=args.types,
                    profile=args.profile,
                    styles=args.redact_style,
                )
        return 0

    llm, pricing = _load_llm(args, parser)

    if args.llm_trace and llm is None:
        CliPresenter(quiet=args.quiet, verbose=args.verbose).info(
            "--llm-trace: LLM не подключена (--llm-config не задан), трейс не будет записан."
        )

    if args.ask or args.answers is not None:
        return _start(args.files[0], args, parser, selected_types, llm, pricing, interactive=True)

    any_leaked = False
    for source in args.files:
        code = _start(source, args, parser, selected_types, llm, pricing, interactive=False)
        if code == EXIT_LEAK:
            any_leaked = True
        elif code != 0:
            return code
    return EXIT_LEAK if any_leaked else 0


if __name__ == "__main__":
    raise SystemExit(main())
