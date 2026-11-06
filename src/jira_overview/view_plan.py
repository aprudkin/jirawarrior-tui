"""Pure overview rows, headings and widths; no Textual widgets or focus state."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from rich.text import Text

from .core import Issue
from .session import ReviewItem

_COLUMN_LABELS = ("Тикет", "Название", "Статус", "Обновлено")
_SORT_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
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


def _family_rows(items: list[ReviewItem], by_key: dict[str, ReviewItem], *,
                 depth: int = 0, open_first: bool = False) -> list[tuple[ReviewItem, int]]:
    """Order blocks by the parent, retaining only matching own children."""
    selected = {item.issue.key: item for item in items}
    roots: dict[str, ReviewItem] = {}
    children: dict[str, list[ReviewItem]] = {}
    for item in items:
        parent = by_key.get(item.issue.parent_key) if item.issue.parent_key is not None else None
        if parent is None or parent.issue.is_epic:
            roots[item.issue.key] = item
            continue
        key = parent.issue.key
        if key not in roots:
            # A parent outside this area/filter is context, even if tracked in
            # another area. Capture that fact in the activated immutable Issue.
            roots[key] = selected.get(key) or ReviewItem(
                replace(parent.issue, tracked=False), False, 0)
        children.setdefault(key, []).append(item)
    rows = []
    for root in sorted(roots.values(), key=lambda item: _item_sort_key(item, open_first=open_first)):
        rows.append((root, depth))
        rows.extend((child, depth + 1) for child in sorted(
            children.get(root.issue.key, ()), key=lambda item: _item_sort_key(item, open_first=open_first)))
    return rows


def _tree_prefixes(rows: list[tuple[ReviewItem, int]]) -> list[str]:
    """Connect only the visible siblings, resetting at each top-level root."""
    prefixes = []
    later_siblings: set[int] = set()
    for _, depth in reversed(rows):
        later_siblings = {level for level in later_siblings if level <= depth}
        if depth == 0:
            prefixes.append("")
        else:
            ancestors = "".join("│  " if level in later_siblings else "   "
                                for level in range(1, depth))
            prefixes.append(ancestors + ("├─ " if depth in later_siblings else "└─ "))
        later_siblings.add(depth)
    return list(reversed(prefixes))


def _issue_cells(item: ReviewItem, *, epic_count: int | None = None,
                 prefix: str = "") -> tuple[Text, Text, Text, Text]:
    issue = item.issue
    emphasis = "bold" if issue.is_epic or item.new or item.unread_comments else ""
    key = Text()
    key.append(prefix, style="dim")
    key.append(issue.key, style="bold cyan" if issue.is_epic else emphasis)
    if item.new:
        key.append(" NEW", style="bold green")
    if item.unread_comments:
        key.append(f" Comment +{item.unread_comments}", style="bold yellow")
    summary = issue.summary + (f" ({epic_count})" if epic_count is not None else "")
    updated = issue.updated.astimezone().strftime("%d.%m.%Y") if issue.updated is not None else "—"
    return key, Text(summary, style=emphasis), Text(issue.status), Text(updated)


@dataclass(frozen=True)
class TablePlan:
    area: str
    heading: str
    rows: tuple[tuple[Issue, tuple[Text, Text, Text, Text]], ...]


@dataclass(frozen=True)
class OverviewPlan:
    tables: tuple[TablePlan, ...]
    column_widths: tuple[int, ...]


def build_plan(items: tuple[ReviewItem, ...], *, epic_mode: bool = False,
               query: str = "") -> OverviewPlan:
    query = query.casefold()
    matching_items = tuple(item for item in items if query in item.issue.summary.casefold())
    by_key = {item.issue.key: item for item in items}
    epic_counts: dict[str, int] = {}
    tables = []
    column_widths = [Text(label).cell_len for label in _COLUMN_LABELS]
    for area in (("epic",) if epic_mode else ("sprint", "other")):
        if area == "epic":
            epics = sorted((item for item in items if item.issue.is_epic),
                           key=lambda item: item.issue.key)
            children = {item.issue.key: [] for item in epics}
            for item in matching_items:
                if item.issue.tracked and not item.issue.is_epic and item.issue.epic_key in children:
                    children[item.issue.epic_key].append(item)
            rows: list[tuple[ReviewItem, int]] = []
            for epic in epics:
                tickets = children[epic.issue.key]
                if not tickets and query not in epic.issue.summary.casefold():
                    continue
                epic_counts[epic.issue.key] = len(tickets)
                rows.append((epic, 0))
                rows.extend(_family_rows(tickets, by_key, depth=1))
            heading = (f"Эпики ({len(epic_counts)}) — мои открытые тикеты ({sum(epic_counts.values())})" +
                       ((" — нет совпадений" if query else " — нет эпиков") if not epic_counts else ""))
        else:
            tickets = [item for item in matching_items
                       if item.issue.tracked and not item.issue.is_epic
                       and bool(item.issue.sprints) == (area == "sprint")]
            rows = _family_rows(tickets, by_key, open_first=area == "other")
            own_issues = [item.issue for item, _ in rows if item.issue.tracked and not item.issue.is_epic]
            names = [_sprint_label(name) for name in sorted({name for i in own_issues for name in i.sprints})]
            title = "Текущий спринт" if area == "sprint" else "Остальные мои задачи"
            heading = (f"{title} ({len(own_issues)})" +
                       (" — " + "; ".join(names) if names else "") +
                       ((" — нет совпадений" if query else " — нет задач") if not own_issues else ""))
        planned_rows = []
        for (item, _), prefix in zip(rows, _tree_prefixes(rows), strict=True):
            cells = _issue_cells(item, epic_count=epic_counts.get(item.issue.key), prefix=prefix)
            column_widths = [max(width, cell.cell_len) for width, cell in zip(column_widths, cells, strict=True)]
            planned_rows.append((item.issue, cells))
        tables.append(TablePlan(area, heading, tuple(planned_rows)))
    return OverviewPlan(tuple(tables), tuple(column_widths))
