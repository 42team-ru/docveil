"""Экраны Textual для интерактивного запуска DocVeil."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Label,
    ProgressBar,
    RichLog,
    SelectionList,
    Static,
)

from masker.branding import (
    BORDER,
    FOLD,
    INK,
    PAPER,
    PRODUCT,
    STEEL,
    SURFACE,
    TAGLINE,
    hex_colour,
    logo_text,
    wordmark_text,
)
from masker.cli_ui import _STAGES
from masker.entity_types import EntityTypeRegistry, builtin_specs
from masker.tui.service import (
    SUPPORTED_SUFFIXES,
    StageObserver,
    TuiRunRequest,
    TuiRunResult,
    TuiRunService,
)

_STAGE_LABELS = dict(_STAGES)


class SupportedDirectoryTree(DirectoryTree):
    """Дерево, которое оставляет каталоги и документы, понятные движку."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [
            path for path in paths if path.is_dir() or path.suffix.casefold() in SUPPORTED_SUFFIXES
        ]


class RunService(Protocol):
    """Минимальный контракт сервиса, удобный для headless UI-тестов."""

    def run(self, request: TuiRunRequest, observe: StageObserver) -> TuiRunResult:
        """Вернуть результат графового прогона."""


class WelcomeScreen(Screen[None]):
    """Заставка продукта."""

    def compose(self) -> ComposeResult:
        with Center(), Container(id="welcome-card"):
            yield Static(logo_text(), id="logo")
            yield Static(wordmark_text(), id="product-name")
            yield Label(TAGLINE, id="tagline")
            yield Button("Начать обезличивание", id="start", variant="primary")
            yield Label("Файлы не покидают ваш компьютер", id="local-note")
        yield Footer()

    @on(Button.Pressed, "#start")
    def start(self) -> None:
        self.app.push_screen(FileScreen())


class FileScreen(Screen[None]):
    """Выбор единственного документа из отфильтрованного дерева."""

    def __init__(self, root: Path | None = None) -> None:
        super().__init__()
        self._root = root or Path.cwd()
        self._selected: Path | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(classes="page"):
            yield Label("1. Выберите документ", classes="page-title")
            yield Label("Показываются только .docx, .pdf и .xlsx", classes="muted")
            yield SupportedDirectoryTree(self._root, id="files")
            yield Static("Файл не выбран", id="selected-file")
            with Horizontal(classes="actions"):
                yield Button("Назад", id="back")
                yield Button("Далее: типы данных", id="next", variant="primary")
        yield Footer()

    @on(DirectoryTree.FileSelected, "#files")
    def select_file(self, event: DirectoryTree.FileSelected) -> None:
        self.select_path(event.path)

    def select_path(self, path: Path) -> None:
        """Выбрать путь из дерева; отдельный метод сохраняет проверку тестируемой."""
        if path.suffix.casefold() not in SUPPORTED_SUFFIXES:
            self.app.notify("Поддерживаются DOCX, PDF и XLSX", severity="warning")
            return
        self._selected = path
        self.query_one("#selected-file", Static).update(f"Выбрано: {path}")

    @on(Button.Pressed, "#back")
    def back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#next")
    def next(self) -> None:
        if self._selected is None:
            self.app.notify("Сначала выберите файл", severity="warning")
            return
        self.app.push_screen(TypeScreen(self._selected))


class TypeScreen(Screen[None]):
    """Выбор категорий данных через флажки реестра сущностей."""

    def __init__(self, source: Path) -> None:
        super().__init__()
        self._source = source

    def compose(self) -> ComposeResult:
        choices = [(f"{spec.title} ({spec.id})", spec.id, True) for spec in builtin_specs()]
        yield Header(show_clock=False)
        with Container(classes="page"):
            yield Label("2. Какие данные маскировать?", classes="page-title")
            yield Label("Все типы выбраны по умолчанию. Критичные типы маскируются без вопросов.")
            yield SelectionList(*choices, id="types")
            with Horizontal(classes="actions"):
                yield Button("Назад", id="back")
                yield Button("Запустить", id="run", variant="success")
        yield Footer()

    @on(Button.Pressed, "#back")
    def back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#run")
    def run(self) -> None:
        selected = frozenset(str(item) for item in self.query_one("#types", SelectionList).selected)
        if not selected:
            self.app.notify("Выберите хотя бы один тип", severity="warning")
            return
        request = TuiRunRequest(source=self._source, types=selected)
        self.app.push_screen(ProgressScreen(request))
        # `self.app` типизирован как App[Any]; сужаем к своему приложению,
        # иначе вызов собственного метода не проходит проверку типов.
        cast("DocVeilApp", self.app).begin_document(request)


def _forget(observer: Callable[[str, str, str], Any]) -> Callable[[str, str, str], None]:
    """Отбросить результат наблюдателя.

    `post_message` возвращает bool, а контракт наблюдателя стадий обещает
    `None`. Молча подсунуть несовпадающий тип нельзя: он разъедется при
    первой же смене одной из сторон.
    """

    def observe(node: str, status: str, detail: str) -> None:
        observer(node, status, detail)

    return observe


class StageUpdate(Message):
    """Потокобезопасное событие от graph observer к главному циклу Textual."""

    def __init__(self, node: str, status: str, detail: str) -> None:
        super().__init__()
        self.node = node
        self.status = status
        self.detail = detail


class RunFinished(Message):
    """Итог фонового прогона без передачи изменяемого UI-состояния в поток."""

    def __init__(self, result: TuiRunResult | None, error: str | None) -> None:
        super().__init__()
        self.result = result
        self.error = error


class ProgressScreen(Screen[None]):
    """Живая стадия, шкала и журнал обработки."""

    def __init__(self, request: TuiRunRequest) -> None:
        super().__init__()
        self._request = request
        self._completed: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(classes="page"):
            yield Label("3. Обработка документа", classes="page-title")
            yield Static(f"Файл: {self._request.source}", classes="muted")
            yield Static("Подготовка…", id="current-stage")
            yield ProgressBar(total=len(_STAGES), show_eta=False, id="progress")
            yield RichLog(highlight=True, markup=False, id="events")
            yield Label("Не закрывайте терминал до завершения прогона.", classes="muted")
        yield Footer()

    def apply_stage(self, update: StageUpdate) -> None:
        label = _STAGE_LABELS.get(update.node, update.node)
        log = self.query_one("#events", RichLog)
        if update.status == "started":
            self.query_one("#current-stage", Static).update(f"Сейчас: {label}")
            log.write(f"→ {label}")
        elif update.status == "completed":
            self._completed.add(update.node)
            self.query_one("#progress", ProgressBar).update(progress=len(self._completed))
            log.write(f"✓ {label}{': ' + update.detail if update.detail else ''}")


class ResultScreen(Screen[None]):
    """Таблица сущностей, карточка документа и пути безопасных артефактов."""

    def __init__(self, result: TuiRunResult, elapsed_seconds: float) -> None:
        super().__init__()
        self._result = result
        self._elapsed_seconds = elapsed_seconds

    def compose(self) -> ComposeResult:
        report = self._result.report
        yield Header(show_clock=False)
        with VerticalScroll(classes="page"):
            yield Label("4. Готово", classes="page-title")
            yield Static(self._summary_text(report), id="run-summary")
            yield Label("Найденные сущности", classes="section-title")
            yield DataTable(id="entities", zebra_stripes=True)
            yield Label("Карточка документа", classes="section-title")
            yield Static(self._contract_text(report), id="contract-card")
            yield Label("Готовые файлы", classes="section-title")
            yield Static(self._paths_text(), id="artifact-paths")
            yield Button("Новый документ", id="again", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#entities", DataTable)
        table.add_columns("Тип", "Маркер", "Уверенность", "Где найдено")
        registry = EntityTypeRegistry.builtin()
        for item in _records(self._result.report.get("entities")):
            type_id = str(item.get("type", ""))
            try:
                title = registry.spec(type_id).title
            except KeyError:
                title = type_id
            table.add_row(
                title,
                str(item.get("marker") or "—"),
                f"{float(item.get('confidence', 0.0)):.0%}",
                _location(item),
            )

    @on(Button.Pressed, "#again")
    def again(self) -> None:
        self.app.switch_screen(FileScreen())

    def _summary_text(self, report: dict[str, Any]) -> str:
        llm = _mapping(_mapping(report.get("telemetry")).get("llm"))
        return (
            f"Найдено: {report.get('entity_count', 0)}; "
            f"время: {_duration(self._elapsed_seconds)}; "
            f"модель: {llm.get('message', 'данные о стоимости отсутствуют')}"
        )

    def _contract_text(self, report: dict[str, Any]) -> str:
        card = _mapping(report.get("contract_summary"))
        if not card:
            return "Карточка договора не определена."
        return "\n".join(
            (
                f"Заказчик: {_party(card.get('customer'))}",
                f"Поставщик: {_party(card.get('supplier'))}",
                f"Номер: {card.get('contract_number') or '—'}",
                f"Сумма: {card.get('contract_amount') or '—'}",
                f"Сроки: {', '.join(_strings(card.get('delivery_periods'))) or '—'}",
                f"Сертификат: {_certificate_status(report.get('certificate'))}",
                f"Верификатор: {_verifier_status(report.get('verifier'))}",
            )
        )

    def _paths_text(self) -> str:
        paths = [f"Отчёт: {self._result.report_path}"]
        paths.extend(
            f"{item.get('role', 'файл')}: {item.get('path', '—')}"
            for item in self._result.artifacts
        )
        paths.append(f"Метрики: {self._result.runtime_metrics_path}")
        return "\n".join(paths)


class HelpScreen(Screen[None]):
    """Короткая навигационная подсказка поверх текущего экрана."""

    def compose(self) -> ComposeResult:
        with Center(), Container(id="help-card"):
            yield Label("Помощь", classes="page-title")
            yield Static("Enter — выбрать / подтвердить\nEsc — назад\nq — выйти\n? — эта справка")
            yield Button("Закрыть", id="close")

    @on(Button.Pressed, "#close")
    def close(self) -> None:
        self.app.pop_screen()


class DocVeilApp(App[None]):
    """Главное приложение, где только orchestration Textual, а не доменная логика."""

    TITLE = PRODUCT
    SUB_TITLE = TAGLINE
    # Тема тёмная по умолчанию и собрана из цветов логотипа: фон — тот же
    # синий щита, уведённый в глубину. Светлая панель во весь экран в
    # обычно тёмном терминале бьёт по глазам, а белый лист логотипа на
    # тёмном фоне читается лучше, чем на светлом.
    CSS = f"""
    Screen {{ background: {hex_colour(INK)}; color: {hex_colour(PAPER)}; }}
    Header, Footer {{ background: {hex_colour(SURFACE)}; color: {hex_colour(PAPER)}; }}
    .page {{ margin: 1 3; height: 1fr; }}
    .page-title {{ color: {hex_colour(PAPER)}; text-style: bold; margin-bottom: 1; }}
    .section-title {{ color: {hex_colour(FOLD)}; text-style: bold; margin-top: 1; }}
    .muted, #local-note {{ color: {hex_colour(FOLD)}; }}
    #welcome-card, #help-card {{
        width: 62; height: auto; margin: 4; padding: 2 4;
        background: {hex_colour(SURFACE)}; border: tall {hex_colour(BORDER)};
    }}
    #welcome-card > * {{ width: 1fr; content-align: center middle; }}
    #logo {{ height: 16; }}
    #product-name {{ text-style: bold; }}
    #tagline {{ color: {hex_colour(FOLD)}; margin-bottom: 1; }}
    #files, SelectionList, RichLog, DataTable {{
        height: 1fr; border: round {hex_colour(BORDER)};
        background: {hex_colour(SURFACE)}; color: {hex_colour(PAPER)};
    }}
    #selected-file, #current-stage, #run-summary, #contract-card, #artifact-paths {{
        margin: 1 0; padding: 0 1; border-left: thick {hex_colour(STEEL)};
    }}
    .actions {{ height: auto; margin-top: 1; align: right middle; }}
    .actions Button {{ margin-left: 1; }}
    Button {{ background: {hex_colour(SURFACE)}; color: {hex_colour(PAPER)}; }}
    Button.-primary, Button.-success {{
        background: {hex_colour(STEEL)}; color: {hex_colour(PAPER)};
    }}
    ProgressBar > .bar--bar {{ color: {hex_colour(STEEL)}; }}
    """
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "Выйти"),
        Binding("question_mark", "help", "Помощь", key_display="?"),
        Binding("escape", "back", "Назад", show=False),
    ]

    def __init__(self, service: RunService | None = None) -> None:
        super().__init__()
        self._service = service or TuiRunService()
        self._started_at = 0.0

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    async def action_back(self) -> None:
        if isinstance(self.screen, ProgressScreen):
            self.notify("Прогон уже выполняется; дождитесь результата", severity="warning")
        elif not isinstance(self.screen, WelcomeScreen):
            self.pop_screen()

    def begin_document(self, request: TuiRunRequest) -> None:
        """Зафиксировать время в UI-потоке и передать работу единственному worker'у."""
        self._started_at = time.monotonic()
        self.run_document(request)

    @work(exclusive=True, thread=True)
    def run_document(self, request: TuiRunRequest) -> None:
        """Не блокировать event loop, передавая наблюдения сообщениями."""
        try:
            result = self._service.run(
                request,
                _forget(
                    lambda node, status, detail: self.post_message(
                        StageUpdate(node, status, detail)
                    )
                ),
            )
        except (OSError, RuntimeError, ValueError) as error:
            self.post_message(RunFinished(None, str(error)))
        else:
            self.post_message(RunFinished(result, None))

    def on_stage_update(self, message: StageUpdate) -> None:
        if isinstance(self.screen, ProgressScreen):
            self.screen.apply_stage(message)

    def on_run_finished(self, message: RunFinished) -> None:
        if message.error is not None:
            self.notify(f"Прогон не завершён: {message.error}", severity="error", timeout=12)
            return
        assert message.result is not None
        self.push_screen(ResultScreen(message.result, time.monotonic() - self._started_at))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _strings(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _location(item: dict[str, Any]) -> str:
    return str(_mapping(item.get("anchor")).get("label") or "—")


def _party(value: object) -> str:
    party = _mapping(value)
    return str(party.get("name") or "—")


def _certificate_status(value: object) -> str:
    certificate = _mapping(value)
    if not certificate:
        return "не посчитан"
    return "пройден" if certificate.get("ok") else "НЕ ПРОЙДЕН"


def _verifier_status(value: object) -> str:
    verifier = _mapping(value)
    if not verifier:
        return "не запускался"
    return f"подтверждено {verifier.get('verified', 0)} из {verifier.get('windows', 0)} окон"


def _duration(seconds: float) -> str:
    minutes, remainder = divmod(round(seconds), 60)
    return f"{minutes} мин {remainder} с" if minutes else f"{remainder} с"
