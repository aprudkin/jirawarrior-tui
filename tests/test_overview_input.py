"""Overview input integration checks; synthetic Jira only."""
import unittest

from support.jira import comment, issue
from support.overview import OverviewCase
from textual.widgets import Static

from jira_overview.app import IssueTable


class OverviewInputTests(OverviewCase):
    async def test_compact_other_rows_render_navigate_and_ignore_clicks_outside_issues(self):
        self.server.issues = [issue(i) for i in range(1, 8)]
        for item, status in zip(self.server.issues,
                                ["In Progress", "To Do", "Hold", "Backlog", "Open", "Review", "Zulu"], strict=True):
            item["fields"]["status"]["name"] = status
        async with self.running() as (app, pilot):
            table = app.query_one("#other", IssueTable)
            await pilot.press("tab", "ctrl+home")
            expected = [f"DEMO-{i}" for i in (5, 1, 2, 3, 4, 6, 7)]
            self.assertEqual(table.row_count, len(expected))
            self.assertEqual([row[0] for row in self.rows(app, "other")], expected)
            for index, key in enumerate(expected):
                rendered = "".join(segment.text for segment in
                                   table.render_line(table.header_height + index))
                self.assertIn(key, rendered)
            self.assertEqual(table.cursor_row, 0)
            await pilot.press("down")
            self.assertEqual(table.cursor_row, 1)
            await pilot.press("up")
            self.assertEqual(table.cursor_row, 0)
            await pilot.press("pagedown")
            self.assertEqual(table.cursor_row, len(expected) - 1)
            await pilot.press("pageup")
            self.assertEqual(table.cursor_row, 0)
            await pilot.press("ctrl+end", "enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-7"])
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            self.assertEqual(table.cursor_row, len(expected) - 1)
            self.assertIn("Comment +1", self.visible(app))
            await pilot.press("ctrl+home")
            for control in (False, True):
                for y in (0, table.header_height + table.row_count):
                    await pilot.click("#other", offset=(5, y), control=control)
                    await self.settled(app, pilot)
                    self.assertEqual(len(self.opened), 1)
                    self.assertIn("Comment +1", self.visible(app))
            await pilot.click("#other", offset=(5, table.header_height), control=True)
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-1")
            self.assertNotIn("Comment +1", self.visible(app))
            self.assertEqual(table.cursor_row, 1)

    async def test_mouse_requires_control_in_both_areas(self):
        async with self.running() as (app, pilot):
            self.server.issues.extend([issue(3, [{"id": 1}]), issue(4)])
            await self.refresh(app, pilot)
            profile = next(self.state_dir.glob("*.json"))
            requests = len(self.server.requests)
            for area, iid in (("sprint", "3"), ("other", "4")):
                table = app.query_one("#" + area, IssueTable)
                row = next(n for n in range(table.row_count) if table._key_at(n) == iid)
                saved = profile.read_bytes()
                for times, shift, meta in ((1, False, False), (2, False, False),
                                           (1, True, False), (1, False, True)):
                    table.move_cursor(row=table.row_count - 1)
                    await pilot.click("#" + area, offset=(5, table.header_height + row),
                                      times=times, shift=shift, meta=meta)
                    await self.settled(app, pilot)
                    self.assertIs(app.focused, table)
                    self.assertEqual(table._key_at(table.cursor_row), iid)
                    self.assertIn("NEW", str(table.get_row_at(table.cursor_row)))
                    self.assertEqual(profile.read_bytes(), saved)
                    self.assertEqual(len(self.opened), 0 if area == "sprint" else 2)
                # Browser refusal on Ctrl+click must not acknowledge the shown issue.
                self.browser_ok = False
                await pilot.click("#" + area, offset=(5, table.header_height + row), control=True)
                await self.settled(app, pilot)
                self.assertEqual(profile.read_bytes(), saved)
                self.assertIn("NEW", str(table.get_row_at(table.cursor_row)))
                self.browser_ok = True
                await pilot.click("#" + area, offset=(5, table.header_height + row), control=True)
                await self.settled(app, pilot)
                self.assertEqual(self.opened[-2:], [self.server.url + "/browse/DEMO-" + iid] * 2)
                self.assertEqual(table._key_at(table.cursor_row), iid)
                self.assertNotIn("NEW", str(table.get_row_at(table.cursor_row)))
                self.assertEqual(len(self.server.requests), requests)

    async def test_enter_and_control_click_acknowledge(self):
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-1"])
            self.assertNotIn("Comment", self.visible(app))
            self.assertEqual(self.notice(app), "")
            self.server.issues[1]["comments"].append(comment(21))
            await self.refresh(app, pilot)
            await pilot.click("#other", offset=(5, 1))
            await self.settled(app, pilot)
            self.assertEqual(len(self.opened), 1)
            self.assertIn("Comment +1", self.visible(app))
            await pilot.click("#other", offset=(5, 1), control=True)
            await self.settled(app, pilot)
            self.assertNotIn("Comment", self.visible(app))
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-2")
            self.assertEqual(len(self.opened), 2)
            self.assertEqual(self.notice(app), "")

    async def test_multiple_sprints_move_selection_and_no_duplicate(self):
        self.server.issues[0]["fields"]["customfield_123"] = [
            {"id": 1}, "com.atlassian.Sprint@a[id=2,state=ACTIVE,name=legacy]", {"id": 3}]
        async with self.running() as (app, pilot):
            heading = str(app.query_one("#sprint-heading", Static).render())
            self.assertIn("Sprint 1 (#1)", heading)
            self.assertIn("Sprint 2 (#2)", heading)
            self.assertNotIn("Sprint 3", heading)
            self.assertEqual(self.rows(app, "sprint"), [
                ["DEMO-1", "Synthetic task 1", "In Progress", "—"],
            ])
            self.server.issues[0]["fields"]["customfield_123"] = None
            await self.refresh(app, pilot)
            self.assertEqual(len(self.rows(app, "sprint")), 0)
            self.assertEqual(len(self.rows(app, "other")), 2)
            self.assertTrue(all(len(row) == 4 for row in self.rows(app, "other")))
            self.assertNotIn("NEW", self.visible(app))
            self.assertIs(app.focused, app.query_one("#other", IssueTable))
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-1"])

    async def test_selection_tracks_issue_across_status_area_move_and_removal(self):
        self.server.issues = [issue(1, [{"id": 1}]), issue(2), issue(3)]
        async with self.running() as (app, pilot):
            await pilot.press("tab")
            table = app.query_one("#other", IssueTable)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-2")
            self.server.issues[1]["fields"]["status"]["name"] = "To Do"
            self.server.issues[1]["fields"]["customfield_123"] = [{"id": 1}]
            await self.refresh(app, pilot)
            table = app.query_one("#sprint", IssueTable)
            self.assertIs(app.focused, app.query_one("#sprint", IssueTable))
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-2")
            self.server.issues.pop(1)
            await self.refresh(app, pilot)
            self.assertIs(app.focused, app.query_one("#sprint", IssueTable))
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-1")
            self.assertTrue(table.get_row_at(table.cursor_row)[2])

    async def test_empty_and_long_lists_selection_survives_and_nearest_on_removal(self):
        self.server.issues = []
        async with self.running() as (app, pilot):
            self.assertIn("нет задач", str(app.query_one("#other-heading", Static).render()))
            await pilot.press("enter")
            self.assertFalse(self.opened)
            self.server.issues = [issue(i) for i in range(1, 31)]
            await self.refresh(app, pilot)
            await pilot.press("tab", "down", "down", "pagedown")
            table = app.query_one("#other", IssueTable)
            key = table.get_row_at(table.cursor_row)[0].plain.split()[0]
            await self.refresh(app, pilot)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain.split()[0], key)
            self.server.issues = [i for i in self.server.issues if i["key"] != key]
            row = table.cursor_row
            await self.refresh(app, pilot)
            self.assertEqual(table.cursor_row, min(row, 28))
            self.assertFalse(self.opened)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertNotEqual(self.opened[-1].rsplit("/", 1)[1], key)


if __name__ == "__main__":
    unittest.main()
