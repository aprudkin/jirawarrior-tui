"""Direct OverviewPresentation contract tests without Jira or ReviewSession."""
import asyncio
from datetime import datetime, timezone
import os
import time
import unittest
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static
from textual.widgets.data_table import RowKey

from jira_overview.core import Issue
from jira_overview.presentation import IssueActivated, IssueTable, OverviewPresentation
from support.items import review_item


class PresentationHarness(App):
    activated: Issue

    CSS = "Screen { layout: vertical; }"

    def compose(self) -> ComposeResult:
        yield OverviewPresentation(id="presentation")
        yield Static("sidebar", id="sidebar")

    def on_mount(self):
        self.query_one("#sidebar", Static).can_focus = True
        self.activation_gate: asyncio.Event | None = None

    async def on_issue_activated(self, event: IssueActivated):
        if self.activation_gate is not None:
            await self.activation_gate.wait()
        self.activated = event.shown


class PresentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_row_selection_reports_acceptance_and_rejects_unshown_or_suspended_rows(self):
        app = PresentationHarness()
        async with app.run_test() as pilot:
            presentation = app.query_one(OverviewPresentation)
            first, second = review_item(1), review_item(2)
            presentation.present((first, second))
            table = app.query_one("#other", IssueTable)
            for key in (RowKey(), RowKey("missing")):
                self.assertIs(table.post_message(DataTable.RowSelected(table, 0, key)), False)
            await pilot.pause()
            self.assertFalse(hasattr(app, "activated"))

            self.assertIs(table.post_message(DataTable.RowSelected(table, 0, RowKey("1"))), True)
            await pilot.pause()
            self.assertIs(app.activated, first.issue)

            presentation.suspend_navigation()
            self.assertIs(table.post_message(DataTable.RowSelected(table, 1, RowKey("2"))), False)
            await pilot.pause()
            self.assertIs(app.activated, first.issue)

    async def test_empty_success_is_distinct_from_loading_and_renders_grouped_areas(self):
        async with PresentationHarness().run_test() as pilot:
            app = pilot.app
            presentation = app.query_one(OverviewPresentation)
            self.assertIn("загрузка", str(app.query_one("#sprint-heading", Static).render()).lower())
            presentation.present(())
            self.assertIn("нет задач", str(app.query_one("#sprint-heading", Static).render()).lower())
            self.assertEqual(app.query_one("#sprint", IssueTable).row_count, 0)

            items = (
                review_item(5, status="Backlog"),
                review_item(2, status="To Do", new=True),
                review_item(3, status="To Do", comments=2),
                review_item(1, status="In Progress", sprint=True),
                review_item(4, status="Open"),
            )
            presentation.present(items)
            sprint = app.query_one("#sprint", IssueTable)
            other = app.query_one("#other", IssueTable)
            self.assertEqual([sprint.get_row_at(row)[0].plain.split()[0]
                              for row in range(sprint.row_count)], ["DEMO-1"])
            self.assertEqual([other.get_row_at(row)[0].plain.split()[0]
                              for row in range(other.row_count)],
                             ["DEMO-2", "DEMO-3", "DEMO-4", "DEMO-5"])
            self.assertIn("43-я неделя", str(app.query_one("#sprint-heading", Static).render()))

    async def test_epic_context_and_mode_toggle_preserve_the_selected_issue(self):
        async with PresentationHarness().run_test() as pilot:
            presentation = pilot.app.query_one(OverviewPresentation)
            presentation.present((
                review_item(20, epic=True, tracked=False),
                review_item(21, epic=True, tracked=False),
                review_item(1, epic_key="DEMO-20", sprint=True),
                review_item(2),
            ))
            ordinary = pilot.app.query_one("#sprint", IssueTable)
            ordinary.focus()
            ordinary.move_cursor(row=0)
            presentation.toggle_epics()
            epic = pilot.app.query_one("#epic", IssueTable)
            self.assertEqual([epic.get_row_at(row)[0].plain
                              for row in range(epic.row_count)],
                             ["DEMO-20", "└─ DEMO-1", "DEMO-21"])
            self.assertEqual(epic.shown["20"].key, "DEMO-20")
            presentation.toggle_epics()
            self.assertFalse(presentation.epic_mode)
            self.assertIs(pilot.app.focused, pilot.app.query_one("#sprint", IssueTable))

    async def test_selected_issue_moves_or_disappears_and_panel_suspend_is_idempotent(self):
        async with PresentationHarness().run_test() as pilot:
            app = pilot.app
            presentation = app.query_one(OverviewPresentation)
            presentation.present((review_item(1), review_item(2)))
            other = app.query_one("#other", IssueTable)
            other.focus()
            other.move_cursor(row=1)
            presentation.suspend_navigation()
            presentation.suspend_navigation()
            app.query_one("#sidebar", Static).focus()
            presentation.present((review_item(2, sprint=True), review_item(3)))
            await pilot.pause()
            self.assertIs(app.focused, app.query_one("#sidebar", Static))
            presentation.resume_navigation()
            presentation.resume_navigation()
            await pilot.pause()
            self.assertIs(app.focused, app.query_one("#sprint", IssueTable))
            sprint = app.query_one("#sprint", IssueTable)
            self.assertEqual(sprint.get_row_at(sprint.cursor_row)[0].plain.split()[0], "DEMO-2")

            presentation.suspend_navigation()
            presentation.present((review_item(3),))
            app.query_one("#sidebar", Static).focus()
            presentation.resume_navigation()
            await pilot.pause()
            focused = app.focused
            assert isinstance(focused, IssueTable)
            selected = focused.get_row_at(focused.cursor_row)[0].plain.split()[0]
            self.assertEqual(selected, "DEMO-3")

    async def test_activation_captures_exact_shown_issue_before_later_repaint(self):
        async with PresentationHarness().run_test() as pilot:
            app = pilot.app
            assert isinstance(app, PresentationHarness)
            presentation = app.query_one(OverviewPresentation)
            original = review_item(1, summary="Shown version")
            presentation.present((original,))
            app.activation_gate = asyncio.Event()
            app.query_one("#other", IssueTable).action_select_cursor()
            await pilot.pause()
            presentation.present((review_item(1, summary="Refreshed version"),))
            app.activation_gate.set()
            await pilot.pause()
            self.assertIs(app.activated, original.issue)
            self.assertEqual(app.activated.summary, "Shown version")

    async def test_suspended_navigation_suppresses_activation_at_the_presentation_seam(self):
        async with PresentationHarness().run_test() as pilot:
            app = pilot.app
            presentation = app.query_one(OverviewPresentation)
            presentation.present((review_item(1),))
            presentation.suspend_navigation()
            app.query_one("#other", IssueTable).action_select_cursor()
            await pilot.pause()
            self.assertFalse(hasattr(app, "activated"))

    async def test_updated_column_uses_local_date_in_all_views_and_keeps_epics_by_key(self):
        try:
            with patch.dict(os.environ, {"TZ": "Etc/GMT+5"}):
                time.tzset()
                async with PresentationHarness().run_test() as pilot:
                    app = pilot.app
                    presentation = app.query_one(OverviewPresentation)
                    instant = datetime(2026, 1, 2, 2, 0, tzinfo=timezone.utc)
                    presentation.present((
                        review_item(20, epic=True, tracked=False, updated=instant),
                        review_item(21, epic=True, tracked=False, updated=instant.replace(year=2027, day=3)),
                        review_item(1, sprint=True, epic_key="DEMO-20", updated=instant),
                        review_item(2, epic_key="DEMO-20"),
                    ))
                    for area, dates in (("sprint", ["01.01.2026"]), ("other", ["—"])):
                        table = app.query_one("#" + area, IssueTable)
                        self.assertEqual([column.label.plain for column in table.ordered_columns],
                                         ["Тикет", "Название", "Статус", "Обновлено"])
                        self.assertEqual([table.get_row_at(row)[3].plain for row in range(table.row_count)],
                                         dates)
                    presentation.toggle_epics()
                    epic = app.query_one("#epic", IssueTable)
                    self.assertEqual([epic._key_at(row) for row in range(epic.row_count)],
                                     ["20", "1", "2", "21"])
                    self.assertEqual([epic.get_row_at(row)[3].plain for row in range(epic.row_count)],
                                     ["01.01.2026", "01.01.2026", "—", "02.01.2027"])
        finally:
            time.tzset()

    async def test_split_families_use_one_untracked_context_per_area_and_keep_real_counts(self):
        async with PresentationHarness().run_test() as pilot:
            app = pilot.app
            presentation = app.query_one(OverviewPresentation)
            items = (
                review_item(100, epic=True, tracked=False),
                review_item(10, epic_key="DEMO-100", new=True, comments=2),
                review_item(1, sprint=True, parent_key="DEMO-10", epic_key="DEMO-100"),
                review_item(2, sprint=True, parent_key="DEMO-10", epic_key="DEMO-100"),
                review_item(20, tracked=False, epic_key="DEMO-100", status="Done"),
                review_item(3, parent_key="DEMO-20", epic_key="DEMO-100"),
            )
            presentation.present(items)
            sprint = app.query_one("#sprint", IssueTable)
            other = app.query_one("#other", IssueTable)
            self.assertEqual([sprint.get_row_at(r)[0].plain for r in range(sprint.row_count)],
                             ["DEMO-10", "├─ DEMO-1", "└─ DEMO-2"])
            self.assertFalse(sprint.shown["10"].tracked)
            self.assertTrue(other.shown["10"].tracked)
            self.assertEqual([other.get_row_at(r)[0].plain for r in range(other.row_count)],
                             ["DEMO-10 NEW Comment +2", "DEMO-20", "└─ DEMO-3"])
            for area in ("sprint", "other"):
                self.assertIn("(2)", str(app.query_one(f"#{area}-heading", Static).render()))
            other.focus()
            other.move_cursor(row=0)
            await pilot.pause()
            presentation.present((*items, review_item(30)))
            self.assertIs(app.focused, other)
            assert presentation.selected_issue is not None
            self.assertTrue(presentation.selected_issue.tracked)
            presentation.suspend_navigation()
            app.query_one("#sidebar", Static).focus()
            await pilot.pause()
            presentation.resume_navigation()
            await pilot.pause()
            self.assertIs(app.focused, other)
            assert presentation.selected_issue is not None
            self.assertTrue(presentation.selected_issue.tracked)
            sprint.focus()
            sprint.move_cursor(row=0)
            await pilot.pause()
            presentation.present(items)
            self.assertIs(app.focused, sprint)
            assert presentation.selected_issue is not None
            self.assertFalse(presentation.selected_issue.tracked)
            presentation.toggle_epics()
            epic = app.query_one("#epic", IssueTable)
            self.assertEqual([epic.get_row_at(r)[0].plain for r in range(epic.row_count)], [
                "DEMO-100", "├─ DEMO-10 NEW Comment +2", "│  ├─ DEMO-1", "│  └─ DEMO-2",
                "└─ DEMO-20", "   └─ DEMO-3",
            ])
            self.assertEqual(epic.get_row_at(0)[1].plain, "Task 100 (4)")
            await pilot.pause()
            assert presentation.selected_issue is not None
            self.assertTrue(presentation.selected_issue.tracked)
            presentation.toggle_epics()
            await pilot.pause()
            self.assertIs(app.focused, other)

    async def test_filter_and_refresh_rebuild_visible_branches_without_changing_activation(self):
        async with PresentationHarness().run_test() as pilot:
            from textual.widgets import Input

            app = pilot.app
            assert isinstance(app, PresentationHarness)
            presentation = app.query_one(OverviewPresentation)
            items = (
                review_item(100, epic=True, tracked=False),
                review_item(10, epic_key="DEMO-100"),
                review_item(11, epic_key="DEMO-100", parent_key="DEMO-10", summary="Keep"),
                review_item(12, epic_key="DEMO-100", parent_key="DEMO-10"),
                review_item(20, epic_key="DEMO-100"),
            )
            presentation.present(items)
            presentation.toggle_epics()
            epic = app.query_one("#epic", IssueTable)
            epic.move_cursor(row=2)
            presentation.query_one("#summary-filter", Input).value = "keep"
            await pilot.pause()
            self.assertEqual([epic.get_row_at(r)[0].plain for r in range(epic.row_count)],
                             ["DEMO-100", "└─ DEMO-10", "   └─ DEMO-11"])
            self.assertFalse(epic.shown["10"].tracked)
            self.assertEqual(epic._key_at(epic.cursor_row), "11")
            added = review_item(13, epic_key="DEMO-100", parent_key="DEMO-10", summary="Keep too")
            presentation.present((*items, added))
            self.assertEqual([epic.get_row_at(r)[0].plain for r in range(epic.row_count)],
                             ["DEMO-100", "└─ DEMO-10", "   ├─ DEMO-11", "   └─ DEMO-13"])
            self.assertEqual(epic._key_at(epic.cursor_row), "11")
            epic.action_select_cursor()
            await pilot.pause()
            self.assertIs(app.activated, items[2].issue)
            presentation.query_one("#summary-filter", Input).value = ""
            await pilot.pause()
            self.assertEqual([epic.get_row_at(r)[0].plain for r in range(epic.row_count)], [
                "DEMO-100", "├─ DEMO-10", "│  ├─ DEMO-11", "│  ├─ DEMO-12",
                "│  └─ DEMO-13", "└─ DEMO-20",
            ])
            presentation.present(items)
            self.assertEqual(epic.get_row_at(3)[0].plain, "│  └─ DEMO-12")
            self.assertEqual(epic._key_at(epic.cursor_row), "11")

    async def test_shared_widths_shrink_and_long_sprint_keeps_one_row_spacing(self):
        async with PresentationHarness().run_test(size=(110, 40)) as pilot:
            app = pilot.app
            presentation = app.query_one(OverviewPresentation)
            presentation.present((review_item(1, sprint=True, new=True),
                                  review_item(2, summary="A" * 40)))
            sprint = app.query_one("#sprint", IssueTable)
            other = app.query_one("#other", IssueTable)
            self.assertEqual([column.get_render_width(sprint) for column in sprint.ordered_columns],
                             [column.get_render_width(other) for column in other.ordered_columns])
            long_width = other.ordered_columns[1].get_render_width(other)
            presentation.present((review_item(1, sprint=True), review_item(2, summary="Short")))
            self.assertLess(other.ordered_columns[1].get_render_width(other), long_width)
            await pilot.pause()
            self.assertEqual(presentation.query_one("#sprint-area").styles.margin.bottom, 1)


if __name__ == "__main__":
    unittest.main()
