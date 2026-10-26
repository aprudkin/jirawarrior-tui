"""Textual UI; refresh and browser handoff never block terminal input."""
from __future__ import annotations

import asyncio
from pathlib import Path
import re
import sys
import time
from typing import Awaitable, Callable

from rich.spinner import Spinner
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.widgets import Button, DataTable, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from .core import Issue, Jira, OverviewError
from .session import ReviewItem, ReviewSession
from .settings import (DEFAULT_REFRESH_SECONDS, read_refresh_seconds,
                       validate_refresh_seconds, write_refresh_seconds)
from .themes import ThemePanel, read_theme, write_theme


_COLUMN_LABELS = ("Тикет", "Название", "Статус")
_STATUS_PRIORITIES = (
    frozenset(("in progress", "в работе")),
    frozenset(("to do", "к выполнению")),
    frozenset(("hold", "on hold")),
    frozenset(("backlog", "бэклог")),
)


def _sprint_label(name: str) -> str:
    match = re.fullmatch(r".+-[0-9]{4}-W([0-9]{1,2}) \(#[0-9]+\)", name)
    if match and 1 <= (week := int(match[1])) <= 53:
        return f"{week}-я неделя"
    return name


def _status_sort_key(status: str) -> tuple[int, str, str]:
    folded = status.casefold()
    rank = next((index for index, names in enumerate(_STATUS_PRIORITIES)
                 if folded in names), len(_STATUS_PRIORITIES))
    return rank, folded, status


def _item_sort_key(item, *, open_first=False):
    return (0 if item.new else 1 if item.unread_comments else 2,
            0 if open_first and item.issue.status.casefold() == "open" else 1,
            _status_sort_key(item.issue.status), item.issue.key)


def _issue_cells(item: ReviewItem, *, epic_count: int | None = None,
                 indent: bool = False) -> tuple[Text, Text, Text]:
    issue = item.issue
    emphasis = "bold" if issue.is_epic or item.new or item.unread_comments else ""
    key = Text(("  " if indent else "") + issue.key,
               style="bold cyan" if issue.is_epic else emphasis)
    if item.new:
        key.append(" NEW", style="bold green")
    if item.unread_comments:
        key.append(f" Comment +{item.unread_comments}", style="bold yellow")
    summary = issue.summary + (f" ({epic_count})" if epic_count is not None else "")
    return key, Text(summary, style=emphasis), Text(issue.status)


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


class IntervalInput(Input):
    """Keep the sidebar's shortcuts available while entering a number."""
    def check_consume_key(self, key: str, character: str | None) -> bool:
        return key not in {"q", "r", "s", "S", "t", "T"} and super().check_consume_key(key, character)


class SettingsPanel(Vertical):
    """Docked settings list with an explicit, cancellable interval editor."""
    BINDINGS = [Binding("escape", "app.cancel_settings", "Отменить", priority=True),
                Binding("s", "app.toggle_settings", "Настройки", priority=True),
                Binding("S", "app.toggle_settings", show=False, priority=True),
                Binding("t", "app.toggle_themes", "Темы", priority=True),
                Binding("T", "app.toggle_themes", show=False, priority=True),
                Binding("r", "app.refresh", "Обновить", priority=True),
                Binding("q", "app.quit", "Выход", priority=True),
                Binding("ctrl+c", "app.quit", show=False, priority=True)]
    DEFAULT_CSS = """
    SettingsPanel {
        display: none;
        width: 32;
        max-width: 55%;
        height: 1fr;
        border-left: solid $border;
        background: $surface;
        padding: 0 1;
    }
    #settings-heading { height: 1; margin-bottom: 1; }
    #settings-title { width: 1fr; text-style: bold; }
    #settings-close { width: 3; min-width: 3; height: 1; border: none; padding: 0; }
    #settings-list { height: auto; border: none; padding: 0; }
    #interval-editor { display: none; height: auto; }
    #interval-label, #settings-error { height: auto; }
    #settings-error { display: none; color: $error; }
    #settings-hints { height: auto; margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="settings-heading"):
            yield Static("Настройки", id="settings-title")
            yield Button("×", id="settings-close", tooltip="Закрыть настройки")
        yield OptionList(id="settings-list", markup=False, compact=True)
        with Vertical(id="interval-editor"):
            yield Static("Интервал в минутах (1/12–1440)", id="interval-label")
            yield IntervalInput(id="refresh-minutes", placeholder="60", select_on_focus=True)
            yield Static("", id="settings-error", markup=False)
        yield Static("Enter изменить / сохранить\nEsc / s / × отменить", id="settings-hints")


class Overview(App):
    TITLE = "Jira — мои задачи"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    #overview { width: 1fr; }
    #connection, #notice { height: auto; max-height: 4; }
    #notice { display: none; }
    #areas { height: 1fr; }
    .area { height: 1fr; min-height: 4; }
    #sprint-area {
        height: 3;
        min-height: 0;
        margin-bottom: 1;
    }
    #epic-area { display: none; }
    .heading { height: auto; max-height: 3; text-style: bold; }
    IssueTable { height: 1fr; }
    Footer { height: 1; }
    """
    BINDINGS = [("q", "quit", "Выход"), ("r", "refresh", "Обновить"),
                ("e", "toggle_epics", "Эпики"),
                Binding("е", "toggle_epics", show=False),
                ("t", "toggle_themes", "Темы"),
                Binding("T", "toggle_themes", show=False),
                ("s", "toggle_settings", "Настройки"),
                Binding("S", "toggle_settings", show=False),
                ("tab", "focus_next", "Область"), ("enter", "noop", "Открыть")]

    def __init__(self, jira: Jira, state_dir: Path, interval: float = DEFAULT_REFRESH_SECONDS,
                 browser: Callable[[str], Awaitable[bool]] = open_browser):
        super().__init__()
        self.session = ReviewSession(jira, state_dir, interval, browser, self.session_changed)
        self._painted_items = None
        self._refresh_spinner = Spinner("dots", text="Updating", style="magenta")
        self.epic_mode = False
        self._theme_path = state_dir / "theme.json"
        self._theme_before_preview = None
        self._panel_return_focus = None
        self._panel_selected = None
        self._settings_open = False
        self._settings_path = state_dir / "settings.json"

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="overview"):
                yield Static("Загрузка Jira…", id="connection", markup=False)
                yield Static("", id="notice", markup=False)
                with Vertical(id="areas"):
                    for area, title in (("sprint", "Текущий спринт"), ("other", "Остальные мои задачи"),
                                        ("epic", "Эпики")):
                        with Vertical(id=area + "-area", classes="area"):
                            yield Static(title + " — загрузка…", id=area + "-heading",
                                         classes="heading", markup=False)
                            yield IssueTable(id=area)
            yield ThemePanel(self.available_themes, id="themes")
            yield SettingsPanel(id="settings")
        yield Footer()

    def on_mount(self):
        try:
            saved_theme = read_theme(self._theme_path, self.available_themes)
            if saved_theme is not None:
                self.theme = saved_theme
        except OverviewError as error:
            self.notify(str(error), title="Темы", severity="warning")
        try:
            saved_interval = read_refresh_seconds(self._settings_path)
            if saved_interval is not None:
                self.session.set_interval(saved_interval)
        except OverviewError as error:
            self.notify(str(error), title="Настройки", severity="warning")
        for table in self.query(IssueTable):
            table.add_columns(*_COLUMN_LABELS)
        self.query_one("#sprint", IssueTable).focus()
        self.set_interval(0.08, self.animate_refresh)
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
        if self.epic_mode:
            return
        table = self.query_one("#sprint", IssueTable)
        heading = self.query_one("#sprint-heading", Static)
        other = self.query_one("#other", IssueTable)
        other_heading = self.query_one("#other-heading", Static)
        available = max(0, self.query_one("#areas", Vertical).size.height - 1)
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

    @property
    def _panel_open(self):
        return self._theme_before_preview is not None or self._settings_open

    def check_action(self, action, parameters):
        if action == "toggle_epics" and self._panel_open:
            return False
        return True

    def action_change_theme(self):
        # Replace Textual's other palette-based entry point as well.
        self.action_toggle_themes()

    def action_toggle_themes(self):
        if self._theme_before_preview is not None:
            self.action_cancel_theme()
            return
        if self._settings_open:
            self.query_one("#settings").display = False
            self._settings_open = False
        else:
            self._capture_panel_focus()
        self._theme_before_preview = self.theme
        self.query_one("#themes").display = True
        choices = self.query_one("#theme-list", OptionList)
        choices.highlighted = choices.get_option_index(self.current_theme.name)
        choices.focus()
        self.call_after_refresh(choices.scroll_to_highlight)

    @on(OptionList.OptionHighlighted, "#theme-list")
    def preview_theme(self, event: OptionList.OptionHighlighted):
        if self._theme_before_preview is not None and event.option_id is not None:
            self.theme = event.option_id

    @on(Button.Pressed, "#theme-close")
    def cancel_theme_button(self):
        self.action_cancel_theme()

    def action_confirm_theme(self):
        if self._theme_before_preview is None:
            return
        option = self.query_one("#theme-list", OptionList).highlighted_option
        if option is None or option.id is None:
            return
        try:
            write_theme(self._theme_path, option.id)
        except OverviewError as error:
            self.notify(str(error), title="Темы", severity="error")
            return
        self.theme = option.id
        self._close_themes()

    def action_cancel_theme(self):
        if self._theme_before_preview is not None:
            self.theme = self._theme_before_preview
            self._close_themes()

    def _close_themes(self):
        self.query_one("#themes").display = False
        self._theme_before_preview = None
        self._restore_panel_focus()

    def _capture_panel_focus(self):
        self._panel_return_focus = self.focused
        focused = self.focused if isinstance(self.focused, IssueTable) else None
        self._panel_selected = (focused._key_at(focused.cursor_row)
                                if focused and focused.row_count else None)
        for table in self.query(IssueTable):
            # Preserve overview colors while keeping input inside the panel.
            table.can_focus = False

    def _restore_panel_focus(self):
        target = self._panel_return_focus
        for table in self.query(IssueTable):
            table.can_focus = True
            if table.display and table.parent.display and self._panel_selected in table.shown:
                row = next(row for row in range(table.row_count)
                           if table._key_at(row) == self._panel_selected)
                table.move_cursor(row=row)
                target = table
        if target is not None:
            target.focus()
        self._panel_return_focus = None
        self._panel_selected = None
        self.call_after_refresh(self.fit_sprint_area)

    def action_toggle_settings(self):
        if self._settings_open:
            self.action_cancel_settings()
            return
        if self._theme_before_preview is not None:
            self.theme = self._theme_before_preview
            self._theme_before_preview = None
            self.query_one("#themes").display = False
        else:
            self._capture_panel_focus()
        self._settings_open = True
        self.query_one("#settings").display = True
        self.query_one("#interval-editor").display = False
        self.query_one("#settings-error").display = False
        choices = self.query_one("#settings-list", OptionList)
        choices.clear_options()
        choices.add_option(Option(f"Интервал обновления: {self.session.interval / 60:g} мин",
                                  id="refresh-interval"))
        choices.highlighted = 0
        choices.focus()

    @on(Button.Pressed, "#settings-close")
    def close_settings_button(self):
        self.action_cancel_settings()

    def action_cancel_settings(self):
        if self._settings_open:
            self.query_one("#settings").display = False
            self._settings_open = False
            self._restore_panel_focus()

    @on(OptionList.OptionSelected, "#settings-list")
    def edit_interval(self, event: OptionList.OptionSelected):
        if not self._settings_open:
            return
        self.query_one("#interval-editor").display = True
        editor = self.query_one("#refresh-minutes", Input)
        editor.value = str(self.session.interval / 60).removesuffix(".0")
        editor.focus()

    @on(Input.Submitted, "#refresh-minutes")
    def save_interval(self, event: Input.Submitted):
        if not self._settings_open:
            return
        error = self.query_one("#settings-error", Static)
        try:
            minutes = float(event.value)
            # Keep an unchanged legacy value exact despite float division/multiplication.
            interval = validate_refresh_seconds(
                self.session.interval if minutes == self.session.interval / 60 else minutes * 60)
        except ValueError:
            error.update("Введите число от 0.08333333333333333 до 1440 минут.")
            error.display = True
            return
        try:
            write_refresh_seconds(self._settings_path, interval)
        except OverviewError as exc:
            error.update(str(exc))
            error.display = True
            return
        self.session.set_interval(interval)
        self.action_cancel_settings()

    def action_refresh(self):
        self.session.refresh()

    def action_toggle_epics(self):
        if self._panel_open:
            return
        focused = self.focused if isinstance(self.focused, IssueTable) else None
        selected = focused._key_at(focused.cursor_row) if focused and focused.row_count else None
        self.epic_mode = not self.epic_mode
        for area in ("sprint", "other", "epic"):
            self.query_one(f"#{area}-area").display = (area == "epic") == self.epic_mode
        self.paint_snapshot(selected)
        tables = [self.query_one("#epic", IssueTable)] if self.epic_mode else [
            self.query_one("#sprint", IssueTable), self.query_one("#other", IssueTable)]
        if self.focused not in tables:
            target = next((table for table in tables if selected in table.shown), None)
            (target or next((table for table in tables if table.row_count), tables[0])).focus()
        self.call_after_refresh(self.fit_sprint_area)

    def paint_view(self):
        view = self.session.view
        if view.closed or not self.is_mounted:
            return
        if view.snapshot is not None and self._painted_items != view.items:
            self.paint_snapshot()
            self._painted_items = view.items
        self.paint_connection()
        notice = self.query_one("#notice", Static)
        notice.update(view.open_notice or "")
        notice.display = bool(view.open_notice)
        self.call_after_refresh(self.fit_sprint_area)

    def animate_refresh(self):
        if self.session.view.refreshing:
            self.paint_connection()

    def paint_connection(self):
        view = self.session.view
        if view.closed or not self.is_mounted:
            return
        if view.display_name is not None:
            freshness = (f"УСТАРЕЛО: {view.updated_at} | {view.refresh_error}"
                         if view.refresh_error else f"Обновлено {view.updated_at}")
            status = Text(f"Jira Warrior: {view.display_name} | {freshness}")
        elif view.refresh_error:
            status = Text(f"НЕТ УСПЕШНОЙ ЗАГРУЗКИ | {view.refresh_error}")
        else:
            status = Text("Загрузка Jira…")
        if view.refreshing:
            status.append(" | ")
            status.append_text(self._refresh_spinner.render(time.monotonic()))
        elif view.next_refresh_at is not None:
            status.append(f" | Следующее обновление {view.next_refresh_at}")
        self.query_one("#connection", Static).update(status)

    def paint_snapshot(self, selected=None):
        if not self.session.view.snapshot:
            return
        if selected is None and self._panel_open:
            selected = self._panel_selected
        tables = [self.query_one("#epic", IssueTable)] if self.epic_mode else [
            self.query_one("#sprint", IssueTable), self.query_one("#other", IssueTable)]
        focused = self.focused if isinstance(self.focused, IssueTable) else None
        if selected is None and focused and focused.row_count:
            selected = focused._key_at(focused.cursor_row)
            if selected not in focused.shown:
                selected = None
        ordinary_cells = {}
        column_widths = [Text(label).cell_len for label in _COLUMN_LABELS]
        if not self.epic_mode:
            ordinary_cells = {item.issue.id: _issue_cells(item) for item in self.session.view.items
                              if item.issue.tracked and not item.issue.is_epic}
            # Both areas share one content grid, measured in terminal cells rather
            # than code points. Explicit widths also shrink when long rows leave.
            for cells in ordinary_cells.values():
                column_widths = [max(width, cell.cell_len) for width, cell in zip(column_widths, cells)]
        for table in tables:
            old_row = table.cursor_row
            old_cursor_key = table._key_at(old_row) if table.row_count else None
            old_key = old_cursor_key if old_cursor_key in table.shown else None
            old_issue_index = sum(
                table._key_at(row) in table.shown for row in range(old_row))
            epic_counts = {}
            if table.id == "epic":
                epics = sorted((item for item in self.session.view.items if item.issue.is_epic),
                               key=lambda item: item.issue.key)
                children = {item.issue.key: [] for item in epics}
                for item in self.session.view.items:
                    if item.issue.tracked and not item.issue.is_epic and item.issue.epic_key in children:
                        children[item.issue.epic_key].append(item)
                items = []
                for epic in epics:
                    tickets = sorted(children[epic.issue.key], key=_item_sort_key)
                    epic_counts[epic.issue.key] = len(tickets)
                    items.extend((epic, *tickets))
            else:
                items = sorted((item for item in self.session.view.items
                                if item.issue.tracked and not item.issue.is_epic
                                and bool(item.issue.sprints) == (table.id == "sprint")),
                               key=lambda item: _item_sort_key(item, open_first=table.id == "other"))
            issues = [item.issue for item in items]
            table.clear(columns=not self.epic_mode)
            if not self.epic_mode:
                for label, width in zip(_COLUMN_LABELS, column_widths):
                    table.add_column(label, width=width)
            table.shown = {i.id: i for i in issues}
            names = [_sprint_label(name) for name in sorted({name for i in issues for name in i.sprints})]
            if table.id == "epic":
                heading = (f"Эпики ({len(epic_counts)}) — мои открытые тикеты ({sum(epic_counts.values())})" +
                           (" — нет эпиков" if not epic_counts else ""))
            else:
                title = "Текущий спринт" if table.id == "sprint" else "Остальные мои задачи"
                heading = (f"{title} ({len(issues)})" + (" — " + "; ".join(names) if names else "") +
                           (" — нет задач" if not issues else ""))
            self.query_one(f"#{table.id}-heading", Static).update(heading)
            for item in items:
                issue = item.issue
                cells = (_issue_cells(item, epic_count=epic_counts.get(issue.key),
                                      indent=not issue.is_epic) if self.epic_mode else ordinary_cells[issue.id])
                table.add_row(*cells, key=issue.id)
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
        if self._panel_open:
            return
        shown = event.shown
        if shown is not None:
            self.session.open(shown)

    async def on_unmount(self):
        await self.session.aclose()
