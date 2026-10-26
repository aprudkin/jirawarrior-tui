"""Summary filtering through real keys, synthetic HTTP, and temporary state."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
import unittest

from textual.widgets import Input, OptionList, Static

from jira_overview.app import Overview
from jira_overview.core import Jira
from jira_overview.presentation import IssueTable, OverviewPresentation
from test_overview import Server, TOKEN, comment, issue


class FilterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = Server()
        self.temp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp.name)
        self.opened = []

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.close)
        self.temp.cleanup()

    async def browser(self, url):
        self.opened.append(url)
        return True

    @asynccontextmanager
    async def running(self, *, size=(110, 32)):
        app = Overview(Jira(self.server.url, TOKEN, allow_local_http=True), self.state_dir,
                       interval=3600, browser=self.browser)
        async with app.run_test(size=size) as pilot:
            await self.settled(app, pilot)
            self.assertIsNotNone(app.snapshot)
            yield app, pilot

    async def settled(self, app, pilot):
        for _ in range(300):
            await pilot.pause(0.01)
            if not app.refreshing and not app.opening:
                return
        self.fail("TUI did not settle")

    def keys(self, app, area):
        table = app.query_one("#" + area, IssueTable)
        return [table.shown[table._key_at(row)].key for row in range(table.row_count)]

    def history(self):
        return {p.name: p.read_bytes() for p in self.state_dir.glob("*.json")}

    async def test_slash_filters_both_areas_on_each_character_and_backspace(self):
        self.server.issues = [issue(1, [{"id": 1}], summary="An API failure"),
                              issue(2, summary="Another api failure"),
                              issue(3, summary="Application"),
                              issue(4, [{"id": 1}], summary="Other work")]
        async with self.running() as (app, pilot):
            await pilot.press("/")
            self.assertIsInstance(app.focused, Input)
            await pilot.press("a", "p")
            self.assertEqual(self.keys(app, "sprint"), ["DEMO-1"])
            self.assertEqual(self.keys(app, "other"), ["DEMO-2", "DEMO-3"])
            await pilot.press("i")
            self.assertEqual(self.keys(app, "other"), ["DEMO-2"])
            await pilot.press("backspace")
            self.assertEqual(self.keys(app, "other"), ["DEMO-2", "DEMO-3"])
            await pilot.press("backspace", "backspace")
            self.assertEqual(self.keys(app, "sprint"), ["DEMO-1", "DEMO-4"])
            self.assertEqual(self.keys(app, "other"), ["DEMO-2", "DEMO-3"])

    async def test_casefold_literal_summary_only_and_clear_empty_state(self):
        self.server.issues = [issue(1, [{"id": 1}], summary="Есть ошибка API"),
                              issue(2, summary="Другая Ошибка api"),
                              issue(3, summary="Fix [a.*] literally"),
                              issue(4, summary="Not a match")]
        async with self.running() as (app, pilot):
            await pilot.press("/")
            for query in ("ошиб", "ОШИБ", "ОшИб", "api", "API"):
                with self.subTest(query=query):
                    await pilot.press("ctrl+u", *query)
                    self.assertEqual(self.keys(app, "sprint"), ["DEMO-1"])
                    self.assertEqual(self.keys(app, "other"), ["DEMO-2"])
            await pilot.press("ctrl+u", *"[a.*]")
            self.assertEqual(self.keys(app, "other"), ["DEMO-3"])
            for query in ("DEMO", "In Progress", "private-comment", "no match"):
                with self.subTest(query=query):
                    await pilot.press("ctrl+u", *query)
                    self.assertEqual(self.keys(app, "sprint"), [])
                    self.assertEqual(self.keys(app, "other"), [])
                    self.assertIn("нет совпадений", str(app.query_one("#other-heading", Static).render()))
            await pilot.press("escape")
            self.assertIsInstance(app.focused, IssueTable)
            self.assertFalse(app.query_one("#summary-filter", Input).display)
            self.assertEqual(self.keys(app, "sprint"), ["DEMO-1"])
            self.assertEqual(self.keys(app, "other"), ["DEMO-2", "DEMO-3", "DEMO-4"])

    async def test_epics_keep_parent_context_but_only_matching_children(self):
        self.server.issues = [issue(20, epic=True, summary="Parent context"),
                              issue(21, epic=True, summary="API roadmap"),
                              issue(22, epic=True, summary="Unrelated empty epic"),
                              issue(1, [{"id": 1}], summary="Fix API", epic_key="DEMO-20"),
                              issue(2, summary="Other child", epic_key="DEMO-20"),
                              issue(3, summary="Standalone API"),
                              issue(4, summary="Unmatched child", epic_key="DEMO-21")]
        async with self.running() as (app, pilot):
            await pilot.press("e", "/", *"api")
            self.assertEqual(self.keys(app, "epic"), ["DEMO-20", "DEMO-1", "DEMO-21"])
            epic = app.query_one("#epic", IssueTable)
            self.assertEqual(epic.get_row_at(0)[1].plain, "Parent context (1)")
            self.assertEqual(epic.get_row_at(2)[1].plain, "API roadmap (0)")
            await pilot.press("enter", "e")
            self.assertEqual(self.keys(app, "sprint"), ["DEMO-1"])
            self.assertEqual(self.keys(app, "other"), ["DEMO-3"])
            await pilot.press("e", "/", "ctrl+u", *"missing")
            self.assertEqual(self.keys(app, "epic"), [])
            self.assertIn("нет совпадений", str(app.query_one("#epic-heading", Static).render()))
            await pilot.press("escape")
            self.assertEqual(self.keys(app, "epic"),
                             ["DEMO-20", "DEMO-1", "DEMO-2", "DEMO-21", "DEMO-4", "DEMO-22"])

    async def test_subtask_filter_retains_only_parent_context_not_unmatched_siblings(self):
        self.server.issues = [issue(100, epic=True), issue(10, epic_key="DEMO-100", summary="Parent"),
                              issue(1, [{"id": 1}], parent="DEMO-10", summary="API fix"),
                              issue(2, [{"id": 1}], parent="DEMO-10", summary="Other child")]
        async with self.running() as (app, pilot):
            before = self.history()
            requests = len(self.server.requests)
            await pilot.press("/", *"api")
            self.assertEqual(self.keys(app, "sprint"), ["DEMO-10", "DEMO-1"])
            self.assertEqual(self.keys(app, "other"), [])
            sprint = app.query_one("#sprint", IssueTable)
            self.assertFalse(sprint.shown["10"].tracked)
            self.assertIn("(1)", str(app.query_one("#sprint-heading", Static).render()))
            await pilot.press("enter", "e")
            self.assertEqual(self.keys(app, "epic"), ["DEMO-100", "DEMO-10", "DEMO-1"])
            epic = app.query_one("#epic", IssueTable)
            self.assertEqual(epic.get_row_at(0)[1].plain, "Synthetic task 100 (1)")
            self.assertFalse(epic.shown["10"].tracked)
            await pilot.press("/", "ctrl+u", *"parent", "enter")
            self.assertEqual(self.keys(app, "epic"), ["DEMO-100", "DEMO-10"])
            self.assertTrue(epic.shown["10"].tracked)
            self.assertEqual(self.history(), before)
            self.assertEqual(len(self.server.requests), requests)
            self.assertFalse(self.opened)

    async def test_shortcut_letters_are_text_without_http_browser_or_history_changes(self):
        text = "qretspQRETSPе/"
        async with self.running() as (app, pilot):
            self.server.issues.append(issue(3, summary="Literal " + text))
            self.server.issues[0]["comments"].append(comment(11))
            await pilot.press("r")
            await self.settled(app, pilot)
            history = self.history()
            requests = len(self.server.requests)
            await pilot.press("/", *text)
            self.assertEqual(app.query_one("#summary-filter", Input).value, text)
            self.assertIs(app.focused, app.query_one("#summary-filter", Input))
            self.assertEqual(self.keys(app, "other"), ["DEMO-3"])
            self.assertFalse(app.query_one(OverviewPresentation).epic_mode)
            self.assertFalse(app.query_one("#themes").display)
            self.assertFalse(app.query_one("#settings").display)
            await pilot.press("enter")
            self.assertIsInstance(app.focused, IssueTable)
            self.assertEqual(self.opened, [])
            await pilot.press("escape")
            self.assertIn("NEW", app.query_one("#other", IssueTable).get_row_at(0)[0].plain)
            self.assertIn("Comment +1", app.query_one("#sprint", IssueTable).get_row_at(0)[0].plain)
            self.assertEqual(self.history(), history)
            self.assertEqual(len(self.server.requests), requests)

    async def test_refresh_reapplies_filter_without_stealing_input_and_error_keeps_snapshot(self):
        self.server.issues = [issue(1, [{"id": 1}], summary="Keep API"),
                              issue(2, summary="Not matching")]
        async with self.running() as (app, pilot):
            await pilot.press("/", *"api")
            self.server.issues = [issue(1, summary="Moved API", comments=[comment(10), comment(11)]),
                                  issue(3, [{"id": 1}], summary="New API"),
                                  issue(4, summary="Another task")]
            app.session.refresh()
            await self.settled(app, pilot)
            editor = app.query_one("#summary-filter", Input)
            self.assertIs(app.focused, editor)
            self.assertEqual(editor.value, "api")
            self.assertEqual(self.keys(app, "sprint"), ["DEMO-3"])
            self.assertEqual(self.keys(app, "other"), ["DEMO-1"])
            self.assertIn("NEW", app.query_one("#sprint", IssueTable).get_row_at(0)[0].plain)
            self.assertIn("Comment +1", app.query_one("#other", IssueTable).get_row_at(0)[0].plain)
            history = self.history()
            self.server.status = 503
            await pilot.press("enter", "r")
            await self.settled(app, pilot)
            self.assertIn("УСТАРЕЛО", str(app.query_one("#connection", Static).render()))
            self.assertEqual(editor.value, "api")
            self.assertEqual(self.keys(app, "sprint"), ["DEMO-3"])
            self.assertEqual(self.keys(app, "other"), ["DEMO-1"])
            await pilot.press("/", "backspace")
            self.assertIs(app.focused, editor)
            self.assertEqual(self.history(), history)
            self.assertEqual(self.opened, [])

    async def test_filtered_order_selection_and_navigation_are_preserved(self):
        self.server.issues = [issue(1, [{"id": 1}], summary="API later"),
                              issue(2, [{"id": 1}], summary="API first"),
                              issue(3, summary="API open"),
                              issue(4, summary="API working")]
        self.server.issues[0]["fields"]["status"]["name"] = "To Do"
        self.server.issues[2]["fields"]["status"]["name"] = "Open"
        async with self.running() as (app, pilot):
            self.server.issues[3]["comments"].append(comment(41))
            self.server.issues.append(issue(5, summary="API new"))
            await pilot.press("r")
            await self.settled(app, pilot)
            await pilot.press("tab", "down", "down")
            other = app.query_one("#other", IssueTable)
            self.assertEqual(other.get_row_at(other.cursor_row)[0].plain, "DEMO-3")
            await pilot.press("/", *"api", "enter")
            self.assertEqual(self.keys(app, "sprint"), ["DEMO-2", "DEMO-1"])
            self.assertEqual(self.keys(app, "other"), ["DEMO-5", "DEMO-4", "DEMO-3"])
            self.assertIs(app.focused, other)
            self.assertEqual(other.get_row_at(other.cursor_row)[0].plain, "DEMO-3")
            await pilot.press("up", "enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-4"])

    async def test_panels_keep_filter_and_restore_focus_in_small_terminal(self):
        self.server.issues = [issue(1, [{"id": 1}], summary="API work"), issue(2)]
        async with self.running(size=(45, 16)) as (app, pilot):
            await pilot.press("/", *"api", "enter", "t", "/")
            self.assertIs(app.focused, app.query_one("#theme-list", OptionList))
            await pilot.press("escape", "s", "enter", "/")
            self.assertIs(app.focused, app.query_one("#refresh-minutes", Input))
            editor = app.query_one("#summary-filter", Input)
            self.assertEqual(editor.value, "api")
            await pilot.press("escape", "/")
            self.assertIs(app.focused, editor)
            self.assertGreater(app.query_one("#sprint", IssueTable).size.height, 1)
            self.assertGreater(app.query_one("#other", IssueTable).size.height, 1)
            # Footer actions can open a panel even when a letter key is input text.
            app.action_toggle_themes()
            app.session.refresh()
            await self.settled(app, pilot)
            self.assertIs(app.focused, app.query_one("#theme-list", OptionList))
            await pilot.press("escape")
            self.assertIs(app.focused, editor)
            self.assertEqual(editor.value, "api")
            self.assertEqual(self.keys(app, "sprint"), ["DEMO-1"])
            self.assertEqual(self.keys(app, "other"), [])
            self.assertEqual(self.opened, [])

    async def test_ctrl_c_still_exits_while_shortcut_letters_are_input(self):
        async with self.running() as (app, pilot):
            history = self.history()
            await pilot.press("/", "q", "ctrl+c")
            await pilot.pause()
            self.assertFalse(app.is_running)
            self.assertEqual(self.history(), history)
            self.assertEqual(self.opened, [])
        self.assertTrue(app.session.view.closed)


if __name__ == "__main__":
    unittest.main()
