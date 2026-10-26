"""Own the overview's tables, ordering, selection, and presentation geometry."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable, Input, Static

from .core import Issue
from .session import ReviewItem


_COLUMN_LABELS = ("Тикет", "Название", "Статус", "Обновлено")
_SORT_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
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


def _item_sort_key(item: ReviewItem, *, open_first=False):
    updated = item.issue.updated
    return (0 if item.new else 1 if item.unread_comments else 2,
            0 if open_first and item.issue.status.casefold() == "open" else 1,
            _status_sort_key(item.issue.status), updated is None,
            _SORT_EPOCH - updated if updated is not None else timedelta(), item.issue.key)


def _issue_cells(item: ReviewItem, *, epic_count: int | None = None,
                 indent: bool = False) -> tuple[Text, Text, Text, Text]:
    issue = item.issue
    emphasis = "bold" if issue.is_epic or item.new or item.unread_comments else ""
    key = Text(("  " if indent else "") + issue.key,
               style="bold cyan" if issue.is_epic else emphasis)
    if item.new:
        key.append(" NEW", style="bold green")
    if item.unread_comments:
        key.append(f" Comment +{item.unread_comments}", style="bold yellow")
    summary = issue.summary + (f" ({epic_count})" if epic_count is not None else "")
    updated = issue.updated.astimezone().strftime("%d.%m.%Y") if issue.updated is not None else "—"
    return key, Text(summary, style=emphasis), Text(issue.status), Text(updated)


class IssueActivated(Message):
    """A row activation with the exact immutable issue shown at activation time."""

    def __init__(self, shown: Issue):
        super().__init__()
        self.shown = shown


class IssueTable(DataTable):
    """Table navigation; its containing presentation owns shown issues."""

    def post_message(self, message):
        if isinstance(message, DataTable.RowSelected):
            shown = self.shown.get(message.row_key.value)
            presentation = next((ancestor for ancestor in self.ancestors
                                if isinstance(ancestor, OverviewPresentation)), None)
            if (shown is not None and presentation is not None
                    and not presentation.navigation_suspended):
                self.post_message(IssueActivated(shown))
            return None
        return super().post_message(message)

    def __init__(self, **kwargs):
        # Keep marker colors on the cursor row without replacing its background.
        super().__init__(cursor_type="row", zebra_stripes=True,
                         cursor_foreground_priority="renderable", **kwargs)
        self.shown: dict[str, Issue] = {}

    def _on_click(self, event: events.Click) -> None:
        # Selection is not activation: only Ctrl+left-click opens an issue.
        event.stop()
        event.prevent_default()
        meta = event.style.meta
        if event.button != 1 or "row" not in meta or "column" not in meta:
            return
        coordinate = Coordinate(meta["row"], meta["column"])
        if not self.is_valid_coordinate(coordinate):
            return
        self.move_cursor(row=coordinate.row, column=coordinate.column)
        if event.ctrl:
            self.action_select_cursor()

    def on_resize(self):
        presentation = next((ancestor for ancestor in self.ancestors
                            if isinstance(ancestor, OverviewPresentation)), None)
        if self.id == "sprint" and presentation is not None:
            self.call_after_refresh(presentation.fit_sprint_area)

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


class SummaryFilterInput(Input):
    """Keep an explicit exit available while all printable shortcuts are text."""

    BINDINGS = [Binding("ctrl+c", "app.quit", show=False, priority=True)]


class OverviewPresentation(Vertical):
    """Render successful review items and own mode, selection, and focus policy."""

    BINDINGS = [Binding("/", "focus_filter", "Фильтр"),
                Binding("escape", "clear_filter", "Очистить фильтр", show=False)]
    DEFAULT_CSS = """
    OverviewPresentation { height: 1fr; }
    #summary-filter { display: none; height: 3; }
    #areas { height: 1fr; }
    .area { height: 1fr; min-height: 4; }
    #sprint-area { height: 3; min-height: 0; margin-bottom: 1; }
    #epic-area { display: none; }
    .heading { height: auto; max-height: 3; text-style: bold; }
    IssueTable { height: 1fr; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.epic_mode = False
        self._items: tuple[ReviewItem, ...] | None = None
        self._suspended = False
        self._filter_query = ""
        self._filter_table: IssueTable | None = None

    def compose(self) -> ComposeResult:
        yield SummaryFilterInput(placeholder="Название · Enter — к задачам · Esc — очистить",
                                 id="summary-filter")
        with Vertical(id="areas"):
            for area, title in (("sprint", "Текущий спринт"), ("other", "Остальные мои задачи"),
                                ("epic", "Эпики")):
                with Vertical(id=area + "-area", classes="area"):
                    yield Static(title + " — загрузка…", id=area + "-heading",
                                 classes="heading", markup=False)
                    yield IssueTable(id=area)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        if action == "clear_filter":
            return not self._suspended and self.query_one("#summary-filter", Input).display
        return not self._suspended

    def action_focus_filter(self) -> None:
        editor = self.query_one("#summary-filter", Input)
        if isinstance(self.app.focused, IssueTable):
            self._filter_table = self.app.focused
        editor.display = True
        editor.focus()
        self.call_after_refresh(self.fit_sprint_area)

    @on(Input.Changed, "#summary-filter")
    def filter_changed(self, event: Input.Changed) -> None:
        self._filter_query = event.value.casefold()
        self._paint(None)

    @on(Input.Submitted, "#summary-filter")
    def finish_filter(self, event: Input.Submitted) -> None:
        event.stop()
        self._focus_tasks()

    def action_clear_filter(self) -> None:
        editor = self.query_one("#summary-filter", Input)
        editor.value = ""
        editor.display = False
        self._filter_query = ""
        self._paint(None)
        self._focus_tasks()

    def _focus_tasks(self) -> None:
        tables = self._visible_tables()
        target = self._filter_table
        if target not in tables or not target.row_count:
            target = next((table for table in tables if table.row_count), tables[0])
        target.focus()
        self.call_after_refresh(self.fit_sprint_area)

    @property
    def selected_issue(self) -> Issue | None:
        """The immutable shown row under the cursor, only while tables own focus."""
        table = self.app.focused
        if self._suspended or not isinstance(table, IssueTable) or not table.row_count:
            return None
        return table.shown.get(table._key_at(table.cursor_row))

    @property
    def navigation_suspended(self) -> bool:
        return self._suspended

    def present(self, items: tuple[ReviewItem, ...]) -> None:
        """Show this successful snapshot; an empty tuple is a successful empty view."""
        if not self.is_mounted:
            self._items = items
            return
        if self._items == items:
            return
        selected = self._selected_key()
        self._items = items
        self._paint(selected)

    def toggle_epics(self) -> None:
        if self._suspended:
            return
        selected = self._selected_key()
        self.epic_mode = not self.epic_mode
        for area in ("sprint", "other", "epic"):
            self.query_one(f"#{area}-area").display = (area == "epic") == self.epic_mode
        self._paint(selected)
        tables = self._visible_tables()
        target = next((table for table in tables if selected in table.shown), None)
        if target is None:
            target = next((table for table in tables if table.row_count), tables[0])
        target.focus()
        self.call_after_refresh(self.fit_sprint_area)

    def suspend_navigation(self) -> None:
        if self._suspended:
            return
        self._suspend_focus = self.app.focused
        self._suspend_selected = self._selected_key()
        self._suspended = True
        for table in self.query(IssueTable):
            table.can_focus = False
        self.query_one("#summary-filter", Input).can_focus = False

    def resume_navigation(self) -> None:
        if not self._suspended:
            return
        self._suspended = False
        selected, target = self._suspend_selected, self._suspend_focus
        for table in self.query(IssueTable):
            table.can_focus = True
        self.query_one("#summary-filter", Input).can_focus = True
        if selected is not None:
            target_table = next((table for table in self._visible_tables()
                                 if selected in table.shown), None)
            if target_table is not None:
                self._move_to(target_table, selected)
                target = target_table
        if isinstance(target, IssueTable) and not target.row_count:
            target = next((table for table in self._visible_tables() if table.row_count), target)
        if target is not None:
            target.focus()
        self._suspend_selected = None
        self._suspend_focus = None
        self.call_after_refresh(self.fit_sprint_area)

    def _visible_tables(self) -> list[IssueTable]:
        return ([self.query_one("#epic", IssueTable)] if self.epic_mode else
                [self.query_one("#sprint", IssueTable), self.query_one("#other", IssueTable)])

    def _selected_key(self) -> str | None:
        focused = self.app.focused
        if isinstance(focused, IssueTable) and focused.row_count:
            key = focused._key_at(focused.cursor_row)
            if key in focused.shown:
                return key
        if self._suspended:
            return self._suspend_selected
        return None

    @staticmethod
    def _move_to(table: IssueTable, key: str) -> None:
        for row in range(table.row_count):
            if table._key_at(row) == key:
                table.move_cursor(row=row)
                return

    def on_mount(self) -> None:
        for table in self.query(IssueTable):
            table.add_columns(*_COLUMN_LABELS)
        self.query_one("#sprint", IssueTable).focus()
        if self._items is not None:
            self._paint(None)

    def on_resize(self) -> None:
        self.call_after_refresh(self.fit_sprint_area)

    def fit_sprint_area(self) -> None:
        if not self.is_running or self.epic_mode:
            return
        table = self.query_one("#sprint", IssueTable)
        heading = self.query_one("#sprint-heading", Static)
        other = self.query_one("#other", IssueTable)
        other_heading = self.query_one("#other-heading", Static)
        available = max(0, self.query_one("#areas", Vertical).size.height - 1)
        minimum = (heading.size.height + table.header_height + min(1, table.row_count) +
                   table.scrollbar_size_horizontal)
        # Prefer half the space for a long sprint, but allow a wrapped heading
        # plus one issue and reserve at least one visible issue in the other area.
        other_minimum = max(4, other_heading.size.height + other.header_height +
                            min(1, other.row_count) + other.scrollbar_size_horizontal)
        self.query_one("#sprint-area", Vertical).styles.height = min(
            heading.size.height + table.virtual_size.height + table.scrollbar_size_horizontal,
            max(available // 2, minimum), max(0, available - other_minimum))

    def _paint(self, selected: str | None) -> None:
        if self._items is None:
            return
        if selected is None:
            selected = self._selected_key()
        tables = self._visible_tables()
        matching_items = tuple(item for item in self._items
                               if self._filter_query in item.issue.summary.casefold())
        ordinary_cells: dict[str, tuple[Text, Text, Text, Text]] = {}
        column_widths = [Text(label).cell_len for label in _COLUMN_LABELS]
        if not self.epic_mode:
            ordinary_cells = {item.issue.id: _issue_cells(item) for item in matching_items
                              if item.issue.tracked and not item.issue.is_epic}
            # Both areas share one content grid, measured in terminal cells rather
            # than code points. Explicit widths also shrink when long rows leave.
            for cells in ordinary_cells.values():
                column_widths = [max(width, cell.cell_len) for width, cell in zip(column_widths, cells)]
        for table in tables:
            old_row = table.cursor_row
            old_cursor_key = table._key_at(old_row) if table.row_count else None
            old_key_for_table = old_cursor_key if old_cursor_key in table.shown else None
            old_issue_index = sum(table._key_at(row) in table.shown for row in range(old_row))
            epic_counts: dict[str, int] = {}
            if table.id == "epic":
                epics = sorted((item for item in self._items if item.issue.is_epic),
                               key=lambda item: item.issue.key)
                children = {item.issue.key: [] for item in epics}
                for item in matching_items:
                    if item.issue.tracked and not item.issue.is_epic and item.issue.epic_key in children:
                        children[item.issue.epic_key].append(item)
                items: list[ReviewItem] = []
                for epic in epics:
                    tickets = sorted(children[epic.issue.key], key=_item_sort_key)
                    if not tickets and self._filter_query not in epic.issue.summary.casefold():
                        continue
                    epic_counts[epic.issue.key] = len(tickets)
                    items.extend((epic, *tickets))
            else:
                items = sorted((item for item in matching_items
                                if item.issue.tracked and not item.issue.is_epic
                                and bool(item.issue.sprints) == (table.id == "sprint")),
                               key=lambda item: _item_sort_key(item, open_first=table.id == "other"))
            issues = [item.issue for item in items]
            table.clear(columns=not self.epic_mode)
            if not self.epic_mode:
                for label, width in zip(_COLUMN_LABELS, column_widths):
                    table.add_column(label, width=width)
            table.shown = {issue.id: issue for issue in issues}
            names = [_sprint_label(name) for name in sorted({name for i in issues for name in i.sprints})]
            if table.id == "epic":
                heading = (f"Эпики ({len(epic_counts)}) — мои открытые тикеты ({sum(epic_counts.values())})" +
                           ((" — нет совпадений" if self._filter_query else " — нет эпиков")
                            if not epic_counts else ""))
            else:
                title = "Текущий спринт" if table.id == "sprint" else "Остальные мои задачи"
                heading = (f"{title} ({len(issues)})" +
                           (" — " + "; ".join(names) if names else "") +
                           ((" — нет совпадений" if self._filter_query else " — нет задач")
                            if not issues else ""))
            self.query_one(f"#{table.id}-heading", Static).update(heading)
            for item in items:
                issue = item.issue
                cells = (_issue_cells(item, epic_count=epic_counts.get(issue.key),
                                      indent=not issue.is_epic) if self.epic_mode else
                         ordinary_cells[issue.id])
                table.add_row(*cells, key=issue.id)
            row_by_key = {table._key_at(row): row for row in range(table.row_count)
                          if table._key_at(row) in table.shown}
            target = selected if selected in row_by_key else old_key_for_table
            if target in row_by_key:
                table.move_cursor(row=row_by_key[target])
            elif row_by_key:
                nearest_index = min(old_issue_index, len(row_by_key) - 1)
                table.move_cursor(row=list(row_by_key.values())[nearest_index])
            else:
                table.move_cursor(row=0)
            if not self._suspended and selected in row_by_key:
                table.focus()
        self.call_after_refresh(self.fit_sprint_area)
