"""Textual UI; refresh and browser handoff never block terminal input."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Awaitable, Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Static

from .core import Issue, Jira, plain
from .session import ReviewSession


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
        self.session = ReviewSession(jira, state_dir, interval, browser, self.session_changed)
        self._painted_items = None

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
        self.run_worker(self.session.start(), group="session", exit_on_error=False)

    @property
    def refreshing(self):
        return self.session.view.refreshing

    @property
    def opening(self):
        return self.session.view.opening

    @property
    def snapshot(self):
        return self.session.view.snapshot

    def session_changed(self):
        if self.is_mounted:
            self.paint_view()

    def action_noop(self):
        pass

    def action_refresh(self):
        self.session.refresh()

    def paint_view(self):
        view = self.session.view
        if view.closed or not self.is_mounted:
            return
        if view.snapshot is not None and self._painted_items != view.items:
            self.paint_snapshot()
            self._painted_items = view.items
        if view.display_name is not None:
            freshness = (f"УСТАРЕЛО: {view.updated_at} | {view.refresh_error}"
                         if view.refresh_error else f"Обновлено {view.updated_at}")
            self.query_one("#connection", Static).update(
                f"{view.display_name} ({plain(view.user_id or '')}) | {freshness}")
        elif view.refresh_error:
            self.query_one("#connection", Static).update(f"НЕТ УСПЕШНОЙ ЗАГРУЗКИ | {view.refresh_error}")
        self.query_one("#notice", Static).update(view.open_notice or "")

    def paint_snapshot(self):
        if not self.session.view.snapshot:
            return
        tables = list(self.query(IssueTable))
        focused = self.focused if isinstance(self.focused, IssueTable) else None
        selected = None
        if focused and focused.row_count:
            selected = list(focused.shown)[focused.cursor_row]
        for table in tables:
            old_row = table.cursor_row
            old_key = list(table.shown)[old_row] if table.row_count else None
            issues = [item.issue for item in self.session.view.items
                      if bool(item.issue.sprints) == (table.id == "sprint")]
            table.clear()
            table.shown = {i.id: i for i in issues}
            names = sorted({name for i in issues for name in i.sprints})
            title = "Текущий спринт" if table.id == "sprint" else "Остальные мои задачи"
            self.query_one(f"#{table.id}-heading", Static).update(
                f"{title} ({len(issues)})" + (" — " + "; ".join(names) if names else "") +
                (" — нет задач" if not issues else ""))
            for issue in issues:
                item = next(item for item in self.session.view.items if item.issue.id == issue.id)
                marker = (" NEW" if item.new else "") + (
                    f" +{item.unread_comments} комм." if item.unread_comments else "")
                table.add_row(Text(issue.key + marker), Text(issue.summary), Text(issue.status),
                              Text("; ".join(issue.sprints)), key=issue.id)
            keys = list(table.shown)
            target = selected if selected in keys else old_key
            table.move_cursor(row=keys.index(target) if target in keys else min(old_row, max(0, len(keys) - 1)))
            if selected in keys:
                table.focus()

    def on_data_table_row_selected(self, event: IssueTable.RowSelected):
        shown = event.shown
        if shown is not None:
            self.session.open(shown)

    async def on_unmount(self):
        await self.session.aclose()
