"""Textual UI; refresh and browser handoff never block terminal input."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Awaitable, Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Footer, Static

from .core import Issue, Jira, plain
from .session import ReviewSession


_STATUS_PRIORITIES = (
    frozenset(("in progress", "в работе")),
    frozenset(("to do", "к выполнению")),
    frozenset(("hold", "on hold")),
    frozenset(("backlog", "бэклог")),
)


def _status_sort_key(status: str) -> tuple[int, str, str]:
    folded = status.casefold()
    rank = next((index for index, names in enumerate(_STATUS_PRIORITIES)
                 if folded in names), len(_STATUS_PRIORITIES))
    return rank, folded, status


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
    """Capture displayed issues and navigate among issue rows."""
    def post_message(self, message):
        if isinstance(message, DataTable.RowSelected):
            message.shown = self.shown.get(message.row_key.value)
        return super().post_message(message)

    def __init__(self, **kwargs):
        # Keep marker colors on the cursor row without replacing its background.
        super().__init__(cursor_type="row", zebra_stripes=True,
                         cursor_foreground_priority="renderable", **kwargs)
        self.shown: dict[str, Issue] = {}

    def on_resize(self):
        if self.id == "sprint":
            self.call_after_refresh(self.app.fit_sprint_area)

    def _key_at(self, row: int) -> str:
        return self.coordinate_to_cell_key(Coordinate(row, 0)).row_key.value

    def _issue_rows(self) -> list[int]:
        return [row for row in range(self.row_count) if self._key_at(row) in self.shown]

    def _move_issue_cursor(self, direction: int, *, page: bool = False, edge: bool = False):
        rows = self._issue_rows()
        if not rows:
            return
        if edge:
            target = rows[0] if direction < 0 else rows[-1]
        else:
            current = self.cursor_row
            if current in rows:
                index = rows.index(current) + direction
            else:
                candidates = [index for index, row in enumerate(rows)
                              if row < current] if direction < 0 else [
                                  index for index, row in enumerate(rows) if row > current]
                if not candidates:
                    return
                index = candidates[-1] if direction < 0 else candidates[0]
            if page:
                index += direction * max(0, self.size.height - 3)
            target = rows[min(max(index, 0), len(rows) - 1)]
        self.move_cursor(row=target)

    def action_cursor_up(self):
        self._move_issue_cursor(-1)

    def action_cursor_down(self):
        self._move_issue_cursor(1)

    def action_page_up(self):
        self._move_issue_cursor(-1, page=True)

    def action_page_down(self):
        self._move_issue_cursor(1, page=True)

    def action_scroll_top(self):
        self._move_issue_cursor(-1, edge=True)

    def action_scroll_bottom(self):
        self._move_issue_cursor(1, edge=True)


class Overview(App):
    TITLE = "Jira — мои задачи"
    CSS = """
    Screen { layout: vertical; }
    #connection, #notice { height: auto; max-height: 4; }
    #notice { display: none; }
    #areas { height: 1fr; }
    .area { height: 1fr; min-height: 4; }
    #sprint-area {
        height: 3;
        min-height: 0;
        margin-bottom: 3;
    }
    .heading { height: auto; max-height: 3; text-style: bold; }
    IssueTable { height: 1fr; }
    Footer { height: 1; }
    """
    BINDINGS = [("q", "quit", "Выход"), ("r", "refresh", "Обновить"),
                ("tab", "focus_next", "Область"), ("enter", "noop", "Открыть")]

    def __init__(self, jira: Jira, state_dir: Path, interval: float = 60,
                 browser: Callable[[str], Awaitable[bool]] = open_browser):
        super().__init__()
        self.session = ReviewSession(jira, state_dir, interval, browser, self.session_changed)
        self._painted_items = None

    def compose(self) -> ComposeResult:
        yield Static("Загрузка Jira…", id="connection", markup=False)
        yield Static("", id="notice", markup=False)
        with Vertical(id="areas"):
            for area in ("sprint", "other"):
                with Vertical(id=area + "-area", classes="area"):
                    yield Static("Текущий спринт — загрузка…" if area == "sprint" else
                                 "Остальные мои задачи — загрузка…", id=area + "-heading",
                                 classes="heading", markup=False)
                    yield IssueTable(id=area)
        yield Footer()

    def on_mount(self):
        for table in self.query(IssueTable):
            table.add_columns("Тикет", "Название", "Статус", "Спринт")
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

    def on_resize(self):
        self.call_after_refresh(self.fit_sprint_area)

    def fit_sprint_area(self):
        table = self.query_one("#sprint", IssueTable)
        heading = self.query_one("#sprint-heading", Static)
        other = self.query_one("#other", IssueTable)
        other_heading = self.query_one("#other-heading", Static)
        available = max(0, self.query_one("#areas", Vertical).size.height - 3)
        # Prefer half the space for a long sprint, but allow a wrapped heading
        # plus one issue and reserve at least one visible issue in the other area.
        minimum = (heading.size.height + table.header_height + min(1, table.row_count) +
                   table.scrollbar_size_horizontal)
        other_minimum = max(4, other_heading.size.height + other.header_height +
                            min(1, other.row_count) + other.scrollbar_size_horizontal)
        self.query_one("#sprint-area", Vertical).styles.height = min(
            heading.size.height + table.virtual_size.height + table.scrollbar_size_horizontal,
            max(available // 2, minimum), max(0, available - other_minimum))

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
        notice = self.query_one("#notice", Static)
        notice.update(view.open_notice or "")
        notice.display = bool(view.open_notice)
        self.call_after_refresh(self.fit_sprint_area)

    def paint_snapshot(self):
        if not self.session.view.snapshot:
            return
        tables = list(self.query(IssueTable))
        focused = self.focused if isinstance(self.focused, IssueTable) else None
        selected = None
        if focused and focused.row_count:
            selected = focused._key_at(focused.cursor_row)
            if selected not in focused.shown:
                selected = None
        for table in tables:
            old_row = table.cursor_row
            old_cursor_key = table._key_at(old_row) if table.row_count else None
            old_key = old_cursor_key if old_cursor_key in table.shown else None
            old_issue_index = sum(
                table._key_at(row) in table.shown for row in range(old_row))
            issues = [item.issue for item in self.session.view.items
                      if bool(item.issue.sprints) == (table.id == "sprint")]
            grouped: dict[str, list[Issue]] = {}
            for issue in issues:
                grouped.setdefault(issue.status, []).append(issue)
            table.clear()
            table.shown = {i.id: i for i in issues}
            names = sorted({name for i in issues for name in i.sprints})
            title = "Текущий спринт" if table.id == "sprint" else "Остальные мои задачи"
            self.query_one(f"#{table.id}-heading", Static).update(
                f"{title} ({len(issues)})" + (" — " + "; ".join(names) if names else "") +
                (" — нет задач" if not issues else ""))
            items_by_id = {item.issue.id: item for item in self.session.view.items}
            for status in sorted(grouped, key=_status_sort_key):
                members = grouped[status]
                for issue in members:
                    item = items_by_id[issue.id]
                    emphasis = "bold" if item.new or item.unread_comments else ""
                    key = Text(issue.key, style=emphasis)
                    if item.new:
                        key.append(" NEW", style="bold green")
                    if item.unread_comments:
                        key.append(f" +{item.unread_comments} комм.", style="bold yellow")
                    table.add_row(key, Text(issue.summary, style=emphasis), Text(issue.status),
                                  Text("; ".join(issue.sprints)), key=issue.id)
            row_by_key = {table._key_at(row): row for row in range(table.row_count)
                          if table._key_at(row) in table.shown}
            target = selected if selected in row_by_key else old_key
            if target in row_by_key:
                table.move_cursor(row=row_by_key[target])
            elif row_by_key:
                nearest_index = min(old_issue_index, len(row_by_key) - 1)
                table.move_cursor(row=list(row_by_key.values())[nearest_index])
            else:
                table.move_cursor(row=0)
            if selected in row_by_key:
                table.focus()

    def on_data_table_row_selected(self, event: IssueTable.RowSelected):
        shown = event.shown
        if shown is not None:
            self.session.open(shown)

    async def on_unmount(self):
        await self.session.aclose()
