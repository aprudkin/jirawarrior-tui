"""Overview history integration checks; synthetic Jira only."""
import asyncio
import unittest
from unittest.mock import patch

from rich.color import Color
from rich.text import Text
from support.jira import TOKEN, comment, issue
from support.overview import OverviewCase

from jira_overview.app import IssueTable, Overview
from jira_overview.core import Jira


class OverviewHistoryTests(OverviewCase):
    async def test_highlight_combinations_refresh_open_and_restart(self):
        async with self.running() as (app, pilot):
            self.assert_row_highlight(app, "sprint", 0)
            self.assert_row_highlight(app, "other", 0)
            self.server.issues.extend([issue(3, [{"id": 1}]), issue(4)])
            await self.refresh(app, pilot)
            self.server.issues[0]["comments"].append(comment(12))
            self.server.issues[-1]["comments"].append(comment(41))
            await self.refresh(app, pilot)
            expected = [("sprint", 0, True, 0), ("sprint", 1, False, 1),
                        ("other", 0, True, 1), ("other", 1, False, 0)]
            for _ in range(2):
                for table_id, row_index, new, unread in expected:
                    with self.subTest(table=table_id, row=row_index):
                        self.assert_row_highlight(app, table_id, row_index, new=new, unread=unread)
                self.assertEqual([row[0].split()[0] for row in self.issue_rows(app, "sprint")],
                                 ["DEMO-3", "DEMO-1"])
                self.assertEqual([row[0].split()[0] for row in self.issue_rows(app, "other")],
                                 ["DEMO-4", "DEMO-2"])
                await self.refresh(app, pilot)
            await pilot.press("tab", "ctrl+home")
            self.browser_ok = False
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assert_row_highlight(app, "other", 0, new=True, unread=1)
            self.assertIn("Браузер не принял", self.notice(app))
            self.browser_ok = True
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-4")
            self.assertEqual(self.notice(app), "")
            self.assert_row_highlight(app, "other", 1)
            await self.refresh(app, pilot)
            self.assert_row_highlight(app, "other", 1)
        async with self.running() as (app, pilot):
            self.assert_row_highlight(app, "sprint", 0, new=True)
            self.assert_row_highlight(app, "sprint", 1, unread=1)
            self.assert_row_highlight(app, "other", 0)
            self.assert_row_highlight(app, "other", 1)

    async def test_marker_colors_survive_cursor_and_focus(self):
        async with self.running() as (app, pilot):
            self.server.issues.append(issue(4))
            await self.refresh(app, pilot)
            self.server.issues[-1]["comments"].append(comment(41))
            await self.refresh(app, pilot)
            await pilot.press("tab", "ctrl+home")
            table = app.query_one("#other", IssueTable)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-4 NEW Comment +1")
            for focused in (True, False):
                with self.subTest(focused=focused):
                    if not focused:
                        await pilot.press("tab")
                    self.assertEqual(table.has_focus, focused)
                    rendered = Text.assemble(*[(segment.text, segment.style or "") for segment in
                                              table.render_line(table.header_height + table.cursor_row)])
                    self.assertIn("DEMO-4 NEW Comment +1", rendered.plain)
                    for label, color in (("NEW", "green"), ("Comment +1", "yellow")):
                        start = rendered.plain.index(label)
                        for offset in range(start, start + len(label)):
                            style = rendered.get_style_at_offset(app.console, offset)
                            self.assertTrue(style.bold)
                            self.assertEqual(style.color, Color.parse(color))
                    if focused:
                        style = rendered.get_style_at_offset(app.console, rendered.plain.index("DEMO-4"))
                        self.assertEqual(style.bgcolor,
                                         table.get_component_rich_style("datatable--cursor").bgcolor)
            self.assertFalse(self.opened)
            self.assert_row_highlight(app, "other", 0, new=True, unread=1)

    async def test_highlight_follows_selected_issue_between_status_groups(self):
        async with self.running() as (app, pilot):
            self.server.issues[1]["fields"]["status"]["name"] = "To Do"
            self.server.issues.append(issue(3))
            self.server.issues[-1]["fields"]["status"]["name"] = "Hold"
            await self.refresh(app, pilot)
            self.server.issues[-1]["comments"].append(comment(31))
            await self.refresh(app, pilot)
            await pilot.press("tab", "ctrl+home")
            table = app.query_one("#other", IssueTable)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-3 NEW Comment +1")
            self.assert_row_highlight(app, "other", 0, new=True, unread=1)
            self.server.issues[-1]["fields"]["status"]["name"] = "In Progress"
            await self.refresh(app, pilot)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-3 NEW Comment +1")
            self.assertTrue(all(row[2] for row in self.rows(app, "other")))
            self.assert_row_highlight(app, "other", 0, new=True, unread=1)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-3"])
            self.assert_row_highlight(app, "other", 0)

    async def test_browser_race_acknowledges_only_displayed_snapshot(self):
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            self.browser_gate = asyncio.Event()
            await pilot.press("enter")
            await pilot.pause(0.05)
            self.assertTrue(app.opening)
            self.server.issues[0]["comments"].append(comment(13))
            await pilot.press("r")
            for _ in range(100):
                await pilot.pause(0.01)
                if not app.refreshing:
                    break
            self.assertIn("Comment +2", self.visible(app))
            self.browser_gate.set()
            await self.settled(app, pilot)
            self.assertIn("Comment +1", self.visible(app))

    async def test_delayed_row_event_opens_issue_captured_before_repaint(self):
        entered, release = asyncio.Event(), asyncio.Event()
        class DelayedOverview(Overview):
            def on_issue_activated(self, event):
                if not hasattr(self, "captured"):
                    self.captured = event
                    entered.set()
                    asyncio.create_task(self.open_captured(event))
            async def open_captured(self, event):
                await release.wait()
                super().on_issue_activated(event)
        app = DelayedOverview(Jira(self.server.url, TOKEN, allow_local_http=True), self.state_dir,
                              interval=3600, browser=self.browser)
        async with app.run_test() as pilot:
            await self.settled(app, pilot)
            await pilot.press("enter")
            await asyncio.wait_for(entered.wait(), 2)
            selected = app.captured.shown
            self.assertEqual(selected.key, "DEMO-1")
            self.server.issues = [item for item in self.server.issues if item["id"] != selected.id]
            await self.refresh(app, pilot)
            release.set()
            await self.settled(app, pilot)
            self.assertTrue(self.opened)
            self.assertTrue(all(url == self.server.url + "/browse/DEMO-1" for url in self.opened))
            self.server.issues.append(issue(1, [{"id": 1}], [comment(10)]))
            await self.refresh(app, pilot)
            self.assertNotIn("NEW", self.visible(app))

    async def test_profile_isolation_and_identity_change(self):
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            self.server.user = "another"
            await self.refresh(app, pilot)
            self.assertIn("Учётная запись изменилась", self.status(app))
            self.assertIn("Comment +1", self.visible(app))
        async with self.running() as (app, pilot):
            self.assertNotIn("Comment", self.visible(app))
            self.assertEqual(len(list(self.state_dir.glob("*.json"))), 2)

    async def test_corruption_second_instance_and_save_failure(self):
        async with self.running() as (app, pilot):
            state_path = next(self.state_dir.glob("*.json"))
            second = self.make_app()
            async with second.run_test() as second_pilot:
                await self.settled(second, second_pilot)
                self.assertIn("Другой экземпляр", self.status(second))
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            before = state_path.read_bytes()
            with patch("jira_overview.core.os.replace", side_effect=OSError("private path")):
                await pilot.press("enter")
                await self.settled(app, pilot)
                self.assertIn("НЕ сохранены", self.notice(app))
                self.assertIn("Comment +1", self.visible(app))
                self.assertEqual(state_path.read_bytes(), before)
                self.assertNotIn("private path", self.notice(app))
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertNotIn("Comment", self.visible(app))
        state_path.write_text("broken state")
        async with self.running() as (app, pilot):
            self.assertIn("повреждено", self.status(app))
            self.assertEqual(state_path.read_text(), "broken state")

    async def test_new_clears_on_open_and_later_comment_remains_new(self):
        async with self.running() as (app, pilot):
            self.server.issues.append(issue(4))
            await self.refresh(app, pilot)
            await pilot.press("tab", "ctrl+home", "enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-4")
            self.assertNotIn("NEW", self.visible(app))
            self.server.issues[-1]["comments"].append(comment(41))
            await self.refresh(app, pilot)
            self.assertIn("DEMO-4 Comment +1", self.visible(app))
        async with self.running() as (app, pilot):
            self.assertNotIn("NEW", self.visible(app))
            self.assertIn("Comment +1", self.visible(app))

    async def test_context_parent_open_never_acknowledges_original_or_children_during_refresh(self):
        self.server.issues = [issue(10), issue(1, [{"id": 1}], parent="DEMO-10"),
                              issue(2, [{"id": 1}], parent="DEMO-10")]
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"].append(comment(109))
            self.server.issues[1]["comments"].append(comment(19))
            await self.refresh(app, pilot)
            sprint = app.query_one("#sprint", IssueTable)
            other = app.query_one("#other", IssueTable)
            self.assertEqual([row[0] for row in self.rows(app, "sprint")],
                             ["DEMO-10", "├─ DEMO-1 Comment +1", "└─ DEMO-2"])
            self.assertEqual(other.get_row_at(0)[0].plain, "DEMO-10 Comment +1")
            before = next(self.state_dir.glob("*.json")).read_bytes()
            await pilot.click("#sprint", offset=(4, 1))
            await self.settled(app, pilot)
            self.assertFalse(self.opened)
            self.browser_gate = asyncio.Event()
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(app.opening)
            self.server.issues[0]["comments"].append(comment(110))
            self.server.issues[2]["comments"].append(comment(29))
            app.session.refresh()
            for _ in range(300):
                await pilot.pause(0.01)
                if not app.refreshing:
                    break
            self.assertFalse(app.refreshing)
            self.browser_gate.set()
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-10"])
            self.assertEqual(next(self.state_dir.glob("*.json")).read_bytes(), before)
            self.assertEqual(other.get_row_at(0)[0].plain, "DEMO-10 Comment +2")
            self.assertEqual(sprint.get_row_at(1)[0].plain, "├─ DEMO-1 Comment +1")
            self.assertEqual(sprint.get_row_at(2)[0].plain, "└─ DEMO-2 Comment +1")
            await pilot.click("#sprint", offset=(4, 1), control=True)
            await self.settled(app, pilot)
            self.assertEqual(len(self.opened), 2)
            self.assertEqual(next(self.state_dir.glob("*.json")).read_bytes(), before)
            # An actual child open confirms only that child, not the family.
            await pilot.press("down", "enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-1")
            self.assertNotIn("Comment", sprint.get_row_at(sprint.cursor_row)[0].plain)
            self.assertEqual(other.get_row_at(0)[0].plain, "DEMO-10 Comment +2")
            self.assertIn("Comment +1", str(self.rows(app, "sprint")))

    async def test_epic_context_open_race_never_clears_a_later_observed_epic(self):
        self.epic_fixture()
        async with self.running() as (app, pilot):
            await pilot.press("e")
            await pilot.pause()
            table = app.query_one("#epic", IssueTable)
            table.move_cursor(row=next(n for n in range(table.row_count) if table._key_at(n) == "200"))
            self.browser_gate = asyncio.Event()
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(app.opening)
            context = self.server.context_issues.pop(0)
            self.server.issues.append(context)
            await pilot.press("r")
            for _ in range(300):
                await pilot.pause(0.01)
                if not app.refreshing:
                    break
            observed = next(item for item in app.session.view.items if item.issue.id == "200")
            self.assertTrue(observed.new)
            self.browser_gate.set()
            await self.settled(app, pilot)
            self.assertTrue(next(item for item in app.session.view.items if item.issue.id == "200").new)
            # A subsequent open captured as observed does clear the marker.
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertFalse(next(item for item in app.session.view.items if item.issue.id == "200").new)


if __name__ == "__main__":
    unittest.main()
