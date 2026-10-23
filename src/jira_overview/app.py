"""Textual UI; refresh and browser handoff never block terminal input."""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import sys
from typing import Awaitable, Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Static

from .core import Issue, Jira, OverviewError, Snapshot, State, plain


async def open_browser(url: str) -> bool:
    command = ["/usr/bin/open", url] if sys.platform == "darwin" else ["xdg-open", url]
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        return await asyncio.wait_for(process.wait(), timeout=10) == 0
    except (OSError, TimeoutError):
        return False
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()


class IssueTable(DataTable):
    """Capture the displayed issue at event creation, not after an async refresh."""
    def post_message(self, message):
        if isinstance(message, DataTable.RowSelected):
            message.shown = self.shown.get(message.row_key.value)
        return super().post_message(message)

    def __init__(self, **kwargs):
        super().__init__(cursor_type="row", zebra_stripes=True, **kwargs)
        self.shown: dict[str, Issue] = {}


class Overview(App):
    TITLE = "Jira — мои задачи"
    CSS = """
    Screen { layout: vertical; }
    #connection, #notice { height: auto; max-height: 4; }
    .area { height: 1fr; min-height: 4; }
    .heading { height: auto; max-height: 3; text-style: bold; }
    IssueTable { height: 1fr; }
    Footer { height: 1; }
    """
    BINDINGS = [("q", "quit", "Выход"), ("r", "refresh", "Обновить"),
                ("tab", "focus_next", "Область"), ("enter", "noop", "Открыть"),
                ("up,down", "noop", "↑↓ выбор")]

    def __init__(self, jira: Jira, state_dir: Path, interval: float = 60,
                 browser: Callable[[str], Awaitable[bool]] = open_browser):
        super().__init__()
        self.jira, self.state_dir, self.interval, self.browser = jira, state_dir, interval, browser
        self.state: State | None = None
        self.snapshot: Snapshot | None = None
        self.refreshing = False
        self.opening = False
        self.last_success: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("Загрузка Jira…", id="connection", markup=False)
        yield Static("", id="notice", markup=False)
        for area in ("sprint", "other"):
            with Vertical(classes="area"):
                yield Static("Текущий спринт — загрузка…" if area == "sprint" else
                             "Остальные мои задачи — загрузка…", id=area + "-heading",
                             classes="heading", markup=False)
                yield IssueTable(id=area)
        yield Footer()

    def on_mount(self):
        for table in self.query(IssueTable):
            table.add_columns("Ключ / метки", "Название", "Статус", "Спринт")
        self.query_one("#sprint", IssueTable).focus()
        self.set_interval(self.interval, self.action_refresh)
        self.action_refresh()

    def action_noop(self):
        pass

    def action_refresh(self):
        if not self.refreshing:
            self.refreshing = True
            self.run_worker(self.refresh_data(), group="refresh", exit_on_error=False)

    async def refresh_data(self):
        try:
            snapshot = await self.jira.snapshot()
            if self.state and self.state.user != snapshot.user_id:
                raise OverviewError("Учётная запись изменилась; перезапустите приложение для нового профиля.")
            if self.state is None:
                self.state = State(self.state_dir, self.jira.url, snapshot.user_id)
            self.state.ingest(snapshot)
            self.snapshot = snapshot
            self.last_success = datetime.now().astimezone().strftime("%H:%M:%S %Z")
            self.paint_snapshot()
            self.query_one("#connection", Static).update(
                f"{snapshot.display_name} ({plain(snapshot.user_id)}) | Обновлено {self.last_success}")
        except OverviewError as error:
            freshness = f"УСТАРЕЛО: {self.last_success}" if self.last_success else "НЕТ УСПЕШНОЙ ЗАГРУЗКИ"
            self.query_one("#connection", Static).update(f"{freshness} | {error}")
        finally:
            self.refreshing = False

    def paint_snapshot(self):
        if not self.snapshot or not self.state:
            return
        tables = list(self.query(IssueTable))
        focused = self.focused if isinstance(self.focused, IssueTable) else None
        selected = None
        if focused and focused.row_count:
            selected = list(focused.shown)[focused.cursor_row]
        for table in tables:
            old_row = table.cursor_row
            old_key = list(table.shown)[old_row] if table.row_count else None
            issues = [i for i in self.snapshot.issues if bool(i.sprints) == (table.id == "sprint")]
            table.clear()
            table.shown = {i.id: i for i in issues}
            names = sorted({name for i in issues for name in i.sprints})
            title = "Текущий спринт" if table.id == "sprint" else "Остальные мои задачи"
            self.query_one(f"#{table.id}-heading", Static).update(
                f"{title} ({len(issues)})" + (" — " + "; ".join(names) if names else "") +
                (" — нет задач" if not issues else ""))
            for issue in issues:
                new, count = self.state.markers(issue)
                marker = (" NEW" if new else "") + (f" +{count} комм." if count else "")
                table.add_row(Text(issue.key + marker), Text(issue.summary), Text(issue.status),
                              Text("; ".join(issue.sprints)), key=issue.id)
            keys = list(table.shown)
            target = selected if selected in keys else old_key
            table.move_cursor(row=keys.index(target) if target in keys else min(old_row, max(0, len(keys) - 1)))
            if selected in keys:
                table.focus()

    def on_data_table_row_selected(self, event: IssueTable.RowSelected):
        shown = event.shown
        if shown is not None and not self.opening:
            self.opening = True
            self.run_worker(self.open_issue(shown), group="browser", exit_on_error=False)

    async def open_issue(self, shown: Issue):
        try:
            if not await self.browser(self.jira.browser_url(shown)):
                raise OverviewError("Браузер не принял ссылку; отметки сохранены.")
            assert self.state is not None
            self.state.acknowledge(shown)
            self.paint_snapshot()
            self.query_one("#notice", Static).update(
                "Ссылка передана браузеру. Отмечен только показанный снимок, не чтение страницы.")
        except OverviewError as error:
            self.query_one("#notice", Static).update(str(error))
        finally:
            self.opening = False

    async def on_unmount(self):
        if self.state:
            self.state.close()
        await self.jira.close()
