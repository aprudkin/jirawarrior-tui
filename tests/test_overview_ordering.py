"""Overview ordering integration checks; synthetic Jira only."""
import unittest
from datetime import datetime
from unittest.mock import patch

from support.jira import comment, issue
from support.overview import OverviewCase
from textual.widgets import Static

from jira_overview.app import IssueTable


class OverviewOrderingTests(OverviewCase):
    async def test_updated_sorts_inside_status_in_all_views_and_preserves_selection_on_refresh(self):
        self.server.page_size = 100
        self.server.issues = [issue(1000, epic=True), issue(2000, epic=True)]
        dates = ["2026-01-01T09:00:00Z", "2026-01-02T12:00:00.500+0300",
                 "2026-01-02T09:00:00.500Z", "2026-01-02T09:00:00.501+00:00",
                 None, "invalid", "2026-01-05T09:00:00",
                 "2027-01-01T09:00:00Z", "2000-01-01T09:00:00Z"]
        for base, sprints in ((0, [{"id": 1}]), (100, None)):
            for number, updated in enumerate(dates, 1):
                item = issue(base + number, sprints, epic_key="DEMO-1000", updated=updated)
                item["fields"]["status"]["name"] = (
                    "Backlog" if number == 8 else "Open" if number == 9 else "In Progress")
                self.server.issues.append(item)
        async with self.running() as (app, pilot):
            for area, numbers in (("sprint", (4, 2, 3, 1, 5, 6, 7, 8, 9)),
                                  ("other", (109, 104, 102, 103, 101, 105, 106, 107, 108))):
                self.assertEqual([row[0] for row in self.rows(app, area)],
                                 [f"DEMO-{number}" for number in numbers])
                by_key = {row[0]: row for row in self.rows(app, area)}
                base = 0 if area == "sprint" else 100
                for number in (5, 6, 7):
                    self.assertEqual(by_key[f"DEMO-{base + number}"][3], "—")
                self.assertEqual(by_key[f"DEMO-{base + 4}"][3],
                                 datetime.fromisoformat(dates[3]).astimezone().strftime("%d.%m.%Y"))
            await pilot.press("e")
            self.assertEqual([row[0].lstrip(" │├└─") for row in self.rows(app, "epic")], [
                "DEMO-1000", "DEMO-104", "DEMO-4", "DEMO-102", "DEMO-103", "DEMO-2", "DEMO-3",
                "DEMO-1", "DEMO-101", "DEMO-105", "DEMO-106", "DEMO-107", "DEMO-5", "DEMO-6",
                "DEMO-7", "DEMO-108", "DEMO-8", "DEMO-109", "DEMO-9", "DEMO-2000",
            ])
            await pilot.press("e")
            table = app.query_one("#sprint", IssueTable)
            table.focus()
            table.move_cursor(row=3)
            selected = next(item for item in self.server.issues if item["id"] == "1")
            selected["fields"]["updated"] = "2026-01-03T09:00:00Z"
            await self.refresh(app, pilot)
            self.assertEqual(table._key_at(table.cursor_row), "1")
            self.assertEqual(table.cursor_row, 0)
            await pilot.press("e")
            epic = app.query_one("#epic", IssueTable)
            self.assertEqual(epic._key_at(epic.cursor_row), "1")
            self.assertEqual(epic.cursor_row, 1)
            selected["fields"]["updated"] = "2025-01-03T09:00:00Z"
            await self.refresh(app, pilot)
            self.assertEqual(epic._key_at(epic.cursor_row), "1")
            self.assertEqual(epic.cursor_row, 8)
            before = self.rows(app, "epic")
            snapshot = app.snapshot
            self.server.status = 500
            selected["fields"]["updated"] = "2028-01-01T09:00:00Z"
            await self.refresh(app, pilot)
            self.assertIs(app.snapshot, snapshot)
            self.assertEqual(self.rows(app, "epic"), before)
            self.assertIn("УСТАРЕЛО", self.status(app))
            self.server.status = 200
            await self.refresh(app, pilot)
            self.assertEqual(epic._key_at(epic.cursor_row), "1")
            self.assertEqual(epic.cursor_row, 1)
            await pilot.press("e")
            self.assertEqual(table._key_at(table.cursor_row), "1")
            self.assertEqual(table.cursor_row, 0)
            self.assertFalse(self.opened)

    async def test_updated_keeps_marker_priority_in_each_area_after_acknowledgment_and_restart(self):
        self.server.page_size = 100
        self.server.issues = []
        for base, sprints in ((0, [{"id": 1}]), (100, None)):
            self.server.issues.extend([
                issue(base + 1, sprints, updated="2024-01-01T00:00:00Z"),
                issue(base + 2, sprints, updated="2026-01-01T00:00:00Z"),
                issue(base + 3, sprints, updated="2027-01-01T00:00:00Z"),
            ])
            self.server.issues[-1]["fields"]["status"]["name"] = "Backlog"
        async with self.running() as (app, pilot):
            for item in self.server.issues:
                if int(item["id"]) % 100 in (1, 3):
                    item["comments"].append(comment(10000 + int(item["id"])))
            for base, sprints in ((0, [{"id": 1}]), (100, None)):
                self.server.issues.extend([
                    issue(base + 4, sprints),
                    issue(base + 5, sprints, updated="1999-01-01T00:00:00Z"),
                    issue(base + 6, sprints, updated="2000-01-01T00:00:00Z"),
                ])
            await self.refresh(app, pilot)
            for item in self.server.issues:
                if int(item["id"]) % 100 == 5:
                    item["comments"].append(comment(20000 + int(item["id"])))
            await self.refresh(app, pilot)
            for area, base in (("sprint", 0), ("other", 100)):
                self.assertEqual([row[0] for row in self.rows(app, area)], [
                    f"DEMO-{base + 6} NEW", f"DEMO-{base + 5} NEW Comment +1", f"DEMO-{base + 4} NEW",
                    f"DEMO-{base + 1} Comment +1", f"DEMO-{base + 3} Comment +1", f"DEMO-{base + 2}",
                ])
                table = app.query_one("#" + area, IssueTable)
                table.focus()
                await pilot.press("ctrl+home", "enter")
                await self.settled(app, pilot)
                self.assertEqual(table._key_at(table.cursor_row), str(base + 6))
                self.assertEqual(table.cursor_row, 5)
                self.assertEqual([row[0] for row in self.rows(app, area)], [
                    f"DEMO-{base + 5} NEW Comment +1", f"DEMO-{base + 4} NEW",
                    f"DEMO-{base + 1} Comment +1", f"DEMO-{base + 3} Comment +1",
                    f"DEMO-{base + 2}", f"DEMO-{base + 6}",
                ])
            before = {area: self.rows(app, area) for area in ("sprint", "other")}
            state = next(self.state_dir.glob("*.json")).read_text()
            self.assertNotIn("updated", state)
            self.assertNotIn("2026-", state)
        async with self.running() as (app, pilot):
            self.assertEqual({area: self.rows(app, area) for area in before}, before)

    async def test_local_markers_sort_before_status_in_each_area_and_survive_restart(self):
        self.server.page_size = 100
        self.server.issues = []
        for base, sprints in ((0, [{"id": 1}]), (100, None)):
            for number, status in ((1, "In Progress"), (2, "To Do"), (3, "In Progress"),
                                   (4, "Backlog"), (5, "In Progress")):
                item = issue(base + number, sprints)
                item["fields"]["status"]["name"] = status
                self.server.issues.append(item)
        async with self.running() as (app, pilot):
            for item in self.server.issues:
                if int(item["id"]) % 100 in (2, 3):
                    item["comments"].append(comment(10000 + int(item["id"])))
            for base, sprints in ((0, [{"id": 1}]), (100, None)):
                for number, status in ((6, "Zulu"), (7, "Backlog"), (8, "To Do"), (9, "To Do")):
                    item = issue(base + number, sprints)
                    item["fields"]["status"]["name"] = status
                    if number == 9:
                        item["key"] = f"OTHER-{base + number}"
                    self.server.issues.append(item)
            await self.refresh(app, pilot)
            for item in self.server.issues:
                if int(item["id"]) % 100 == 7:
                    item["comments"].extend([comment(10000 + int(item["id"])),
                                              comment(20000 + int(item["id"]))])
            await self.refresh(app, pilot)
            before = {area: self.rows(app, area) for area in ("sprint", "other")}
            for area, base in (("sprint", 0), ("other", 100)):
                with self.subTest(area=area):
                    rows = before[area]
                    self.assertEqual([row[0] for row in rows], [
                        f"DEMO-{base + 8} NEW", f"OTHER-{base + 9} NEW",
                        f"DEMO-{base + 7} NEW Comment +2", f"DEMO-{base + 6} NEW",
                        f"DEMO-{base + 3} Comment +1", f"DEMO-{base + 2} Comment +1",
                        f"DEMO-{base + 1}", f"DEMO-{base + 5}", f"DEMO-{base + 4}",
                    ])
                    self.assertEqual([row[2] for row in rows], [
                        "To Do", "To Do", "Backlog", "Zulu", "In Progress", "To Do",
                        "In Progress", "In Progress", "Backlog",
                    ])
                    self.assertEqual(len({row[0].split()[0] for row in rows}), 9)
                    self.assertIn("(9)", str(app.query_one("#" + area + "-heading", Static).render()))
                    for index in range(9):
                        self.assert_row_highlight(app, area, index, new=index < 4,
                                                  unread=2 if index == 2 else int(index in (4, 5)))
                    app.query_one("#" + area, IssueTable).focus()
                    await pilot.press("ctrl+home")
                    for row in rows:
                        table = app.query_one("#" + area, IssueTable)
                        self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, row[0])
                        await pilot.press("down")
            self.assertFalse(self.opened)
            self.server.status = 500
            await self.refresh(app, pilot)
            self.assertIn("УСТАРЕЛО", self.status(app))
            self.assertEqual({area: self.rows(app, area) for area in before}, before)
            self.server.status = 200
            await self.refresh(app, pilot)
            self.assertEqual({area: self.rows(app, area) for area in before}, before)
        async with self.running() as (app, pilot):
            self.assertEqual({area: self.rows(app, area) for area in before}, before)
            self.assertFalse(self.opened)

    async def test_selection_follows_marker_promotion_and_acknowledgment_in_each_area(self):
        self.server.page_size = 100
        self.server.issues = [issue(1, [{"id": 1}]), issue(2, [{"id": 1}]),
                              issue(101), issue(102)]
        for item in self.server.issues:
            if int(item["id"]) % 100 == 2:
                item["fields"]["status"]["name"] = "To Do"
        async with self.running() as (app, pilot):
            for area, base, sprints in (("sprint", 0, [{"id": 1}]), ("other", 100, None)):
                with self.subTest(area=area):
                    table = app.query_one("#" + area, IssueTable)
                    table.focus()
                    await pilot.press("ctrl+end")
                    self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, f"DEMO-{base + 2}")
                    added = issue(base + 3, sprints)
                    added["fields"]["status"]["name"] = "Backlog"
                    self.server.issues.append(added)
                    await self.refresh(app, pilot)
                    self.assertEqual(table.cursor_row, 2)
                    self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, f"DEMO-{base + 2}")
                    existing = next(item for item in self.server.issues if item["id"] == str(base + 2))
                    existing["comments"].append(comment(10000 + base))
                    added["comments"].append(comment(20000 + base))
                    await self.refresh(app, pilot)
                    self.assertEqual(table.cursor_row, 1)
                    self.assertEqual(table.get_row_at(table.cursor_row)[0].plain,
                                     f"DEMO-{base + 2} Comment +1")
                    await pilot.press("ctrl+home")
                    before = self.rows(app, area)
                    self.browser_ok = False
                    await pilot.press("enter")
                    await self.settled(app, pilot)
                    self.assertEqual(self.rows(app, area), before)
                    self.assertEqual(table.cursor_row, 0)
                    self.browser_ok = True
                    with patch("jira_overview.core.os.replace", side_effect=OSError("synthetic failure")):
                        await pilot.press("enter")
                        await self.settled(app, pilot)
                    self.assertEqual(self.rows(app, area), before)
                    self.assertEqual(table.cursor_row, 0)
                    self.assertIn("НЕ сохранены", self.notice(app))
                    await pilot.press("enter")
                    await self.settled(app, pilot)
                    self.assertEqual(self.opened[-1], self.server.url + f"/browse/DEMO-{base + 3}")
                    self.assertEqual(table.cursor_row, 2)
                    self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, f"DEMO-{base + 3}")
                    self.assertEqual([row[0] for row in self.rows(app, area)], [
                        f"DEMO-{base + 2} Comment +1", f"DEMO-{base + 1}", f"DEMO-{base + 3}",
                    ])
                    await pilot.press("ctrl+home", "enter")
                    await self.settled(app, pilot)
                    self.assertEqual(table.cursor_row, 1)
                    self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, f"DEMO-{base + 2}")
                    self.assertEqual([row[0] for row in self.rows(app, area)],
                                     [f"DEMO-{base + number}" for number in (1, 2, 3)])

    async def test_open_sorts_first_only_outside_sprint_and_keeps_selection(self):
        statuses = ["Review", "Open", "Backlog", "In Progress", "To Do",
                    "open", "OPEN", "Open", "Opening"]
        self.server.issues = [issue(999, epic=True)]
        for base, sprints in ((0, [{"id": 1}]), (100, None)):
            for number, status in enumerate(statuses, 1):
                item = issue(base + number, sprints, epic_key="DEMO-999")
                item["fields"]["status"]["name"] = status
                self.server.issues.append(item)
        async with self.running() as (app, pilot):
            self.assertEqual([row[0] for row in self.rows(app, "sprint")],
                             [f"DEMO-{i}" for i in (4, 5, 3, 7, 2, 8, 6, 9, 1)])
            self.assertEqual([row[0] for row in self.rows(app, "other")],
                             [f"DEMO-{i}" for i in (107, 102, 108, 106, 104, 105, 103, 109, 101)])
            await pilot.press("e")
            self.assertEqual([row[2] for row in self.rows(app, "epic")[1:]],
                             ["In Progress"] * 2 + ["To Do"] * 2 + ["Backlog"] * 2 +
                             ["OPEN"] * 2 + ["Open"] * 4 + ["open"] * 2 +
                             ["Opening"] * 2 + ["Review"] * 2)
            await pilot.press("e", "tab", "ctrl+home", "down")
            table = app.query_one("#other", IssueTable)
            self.assertEqual(table._key_at(table.cursor_row), "102")
            selected = next(item for item in self.server.issues if item["id"] == "102")
            selected["fields"]["status"]["name"] = "In Progress"
            await self.refresh(app, pilot)
            self.assertEqual(table._key_at(table.cursor_row), "102")
            self.assertEqual(table.cursor_row, 3)
            selected["fields"]["customfield_123"] = [{"id": 1}]
            selected["fields"]["status"]["name"] = "Open"
            await self.refresh(app, pilot)
            sprint = app.query_one("#sprint", IssueTable)
            self.assertIs(app.focused, sprint)
            self.assertEqual(sprint._key_at(sprint.cursor_row), "102")
            self.assertEqual(self.rows(app, "sprint")[0][2], "In Progress")
            self.assertNotIn("DEMO-102", [row[0] for row in self.rows(app, "other")])

    async def test_open_priority_preserves_local_marker_blocks_and_restart(self):
        self.server.issues = [issue(i) for i in range(1, 5)]
        for item in self.server.issues[::2]:
            item["fields"]["status"]["name"] = "Open"
        async with self.running() as (app, pilot):
            for item in self.server.issues[:2]:
                item["comments"].append(comment(999))
            self.server.issues.extend((issue(5), issue(6)))
            self.server.issues[-1]["fields"]["status"]["name"] = "Open"
            await self.refresh(app, pilot)
            self.server.issues[-1]["comments"].append(comment(1000))
            await self.refresh(app, pilot)
            expected = ["DEMO-6 NEW Comment +1", "DEMO-5 NEW", "DEMO-1 Comment +1",
                        "DEMO-2 Comment +1", "DEMO-3", "DEMO-4"]
            self.assertEqual([row[0] for row in self.rows(app, "other")], expected)
            await pilot.press("tab", "ctrl+home", "enter")
            await self.settled(app, pilot)
            table = app.query_one("#other", IssueTable)
            self.assertEqual(table._key_at(table.cursor_row), "6")
            expected = ["DEMO-5 NEW", "DEMO-1 Comment +1", "DEMO-2 Comment +1",
                        "DEMO-3", "DEMO-6", "DEMO-4"]
            self.assertEqual([row[0] for row in self.rows(app, "other")], expected)
            self.assertEqual(table.cursor_row, 4)
        async with self.running() as (app, pilot):
            self.assertEqual([row[0] for row in self.rows(app, "other")], expected)

    async def test_status_groups_are_exact_ordered_and_keep_issue_order_and_markers(self):
        self.server.issues = [
            issue(1, [{"id": 1}]), issue(2, [{"id": 1}]), issue(3), issue(4),
            issue(5), issue(6), issue(7), issue(8), issue(9), issue(10), issue(11),
            issue(12), issue(13),
        ]
        statuses = ["Open", "In Progress", "To Do", "Hold", "On Hold", "Backlog",
                    "Бэклог", "Review", "review"]
        for item, status in zip(self.server.issues, statuses, strict=False):
            item["fields"]["status"]["name"] = status
        for item, status in zip(self.server.issues[9:],
                                ["В работе", "К выполнению", "in progress", "к выполнению"], strict=True):
            item["fields"]["status"]["name"] = status
        async with self.running() as (app, pilot):
            for _ in range(300):
                if "Обновлено" in self.status(app):
                    break
                await pilot.pause(0.01)
            self.server.issues.append(issue(14))
            self.server.issues[-1]["fields"]["status"]["name"] = "In Progress"
            cross_project = issue(15)
            cross_project["key"] = "OTHER-15"
            cross_project["fields"]["status"]["name"] = "In Progress"
            self.server.issues.append(cross_project)
            await self.refresh(app, pilot)
            other_table = app.query_one("#other", IssueTable)
            for _ in range(100):
                if other_table.row_count:
                    break
                await pilot.pause(0.01)
            sprint = self.rows(app, "sprint")
            other = self.rows(app, "other")
            self.assertEqual([r[0] or r[1] for r in sprint], [
                "DEMO-2", "DEMO-1",
            ])
            self.assertEqual([r[0] for r in other], [
                "DEMO-14 NEW", "OTHER-15 NEW", "DEMO-12", "DEMO-10", "DEMO-3",
                "DEMO-11", "DEMO-13", "DEMO-4", "DEMO-5", "DEMO-6", "DEMO-7",
                "DEMO-8", "DEMO-9",
            ])
            for rows in (sprint, other):
                self.assertTrue(all(row[2] for row in rows))
            self.assertEqual([r[2] for r in other if r[0].startswith(("DEMO-", "OTHER-"))],
                             ["In Progress", "In Progress", "in progress", "В работе", "To Do",
                              "К выполнению", "к выполнению", "Hold", "On Hold",
                              "Backlog", "Бэклог", "Review", "review"])


if __name__ == "__main__":
    unittest.main()
