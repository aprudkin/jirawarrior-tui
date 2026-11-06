"""Overview layout integration checks; synthetic Jira only."""
import unittest
from xml.etree import ElementTree

from rich.text import Text
from support.jira import comment, issue
from support.overview import OverviewCase
from textual.widgets import Static

from jira_overview.app import IssueTable


class OverviewLayoutTests(OverviewCase):
    async def test_status_columns_share_widths_for_content_markers_and_empty_areas(self):
        self.server.issues[0]["fields"]["summary"] = "Коротко"
        self.server.issues[1]["key"] = "LONG_PROJECT-200"
        summary = "Название с широкими 界界 и e\u0301"
        self.server.issues[1]["fields"]["summary"] = summary
        self.server.issues[1]["fields"]["status"]["name"] = "Awaiting Verification"
        async with self.running(size=(180, 36)) as (app, pilot):
            await pilot.pause()
            self.assert_status_columns_aligned(app)
            sprint = app.query_one("#sprint", IssueTable)
            self.assertEqual(sprint.ordered_columns[1].width, Text(summary).cell_len)
            initial_width = sprint.virtual_size.width
            self.server.issues.append(issue(300, [{"id": 1}], summary="Новая"))
            self.server.issues[0]["comments"].append(comment(19))
            await self.refresh(app, pilot)
            self.assert_status_columns_aligned(app)
            self.assertIn("DEMO-300 NEW", str(self.rows(app, "sprint")))
            self.assertIn("DEMO-1 Comment +1", str(self.rows(app, "sprint")))
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assert_status_columns_aligned(app)
            self.assertEqual(sprint._key_at(sprint.cursor_row), "1")
            self.server.issues = [self.server.issues[0]]
            await self.refresh(app, pilot)
            self.assert_status_columns_aligned(app)
            self.assertLess(sprint.virtual_size.width, initial_width)
            self.server.issues[0]["fields"]["customfield_123"] = None
            await self.refresh(app, pilot)
            self.assert_status_columns_aligned(app)
            self.assertEqual(sprint.row_count, 0)
            self.assertIs(app.focused, app.query_one("#other", IssueTable))
            self.server.issues = []
            await self.refresh(app, pilot)
            self.assert_status_columns_aligned(app)
            self.assertEqual([column.width for column in sprint.ordered_columns],
                             [Text(label).cell_len for label in ("Тикет", "Название", "Статус", "Обновлено")])

    async def test_status_columns_stay_aligned_on_resize_scroll_and_return_from_epics(self):
        self.epic_fixture()
        self.server.issues[1]["fields"]["summary"] = "Synthetic longer summary " * 3
        # Hidden epic headers must not inflate the ordinary column widths.
        self.server.issues[-1]["fields"]["summary"] = "Hidden epic " * 50
        async with self.running(size=(180, 36)) as (app, pilot):
            for width, height in ((180, 36), (45, 16), (140, 32)):
                await pilot.resize_terminal(width, height)
                await pilot.pause()
                self.assert_status_columns_aligned(app, rendered=width == 180)
                sprint = app.query_one("#sprint", IssueTable)
                other = app.query_one("#other", IssueTable)
                self.assertLess(sprint.virtual_size.width, 150)
                if width == 45:
                    self.assertTrue(sprint.show_horizontal_scrollbar)
                    self.assertTrue(other.show_horizontal_scrollbar)
                    for table in (sprint, other):
                        table.scroll_to(x=table.max_scroll_x, animate=False)
                    await pilot.pause()
                    self.assert_status_columns_aligned(app)
                self.assertEqual(app.query_one("#other-heading", Static).region.y - sprint.region.bottom, 1)
            await pilot.press("e")
            self.server.issues[1]["fields"]["summary"] = "Ещё одно название после обновления"
            await self.refresh(app, pilot)
            await pilot.press("e")
            await pilot.pause()
            self.assert_status_columns_aligned(app)
            self.assertIs(app.focused, app.query_one("#sprint", IssueTable))

    async def test_four_columns_without_sprint_in_both_areas(self):
        async with self.running() as (app, pilot):
            for _ in range(2):
                for table_id, number in (("sprint", 1), ("other", 2)):
                    with self.subTest(table=table_id):
                        table = app.query_one("#" + table_id, IssueTable)
                        self.assertEqual(
                            [column.label.plain for column in table.ordered_columns],
                            ["Тикет", "Название", "Статус", "Обновлено"],
                        )
                        self.assertEqual(self.rows(app, table_id), [
                            [f"DEMO-{number}", f"Synthetic task {number}", "In Progress", "—"],
                        ])
                await self.refresh(app, pilot)

    async def test_single_status_group_is_compact_in_both_areas(self):
        async with self.running() as (app, pilot):
            for _ in range(2):
                await pilot.pause()
                for area, key in (("sprint", "DEMO-1"), ("other", "DEMO-2")):
                    with self.subTest(area=area):
                        table = app.query_one("#" + area, IssueTable)
                        rows = self.rows(app, area)
                        self.assertEqual(len(rows), 1)
                        self.assertEqual(rows[0][0], key)
                        self.assertEqual(rows[0][2], "In Progress")
                        self.assertEqual(table.cursor_row, 0)
                        rendered = "".join(segment.text for segment in
                                           table.render_line(table.header_height))
                        self.assertIn(key, rendered)
                        heading = str(app.query_one("#" + area + "-heading", Static).render())
                        self.assertIn("(1)", heading)
                await self.refresh(app, pilot)

    async def test_compact_sprint_rows_render_and_navigate_without_gaps(self):
        self.server.issues = [issue(i, [{"id": 1}]) for i in range(1, 7)]
        for item, status in zip(self.server.issues,
                                ["In Progress", "On Hold", "On Hold", "Backlog",
                                 "Review", "Review"], strict=True):
            item["fields"]["status"]["name"] = status
        async with self.running() as (app, pilot):
            table = app.query_one("#sprint", IssueTable)
            expected = [f"DEMO-{i}" for i in range(1, 7)]
            await pilot.pause()
            self.assertEqual(table.row_count, len(expected))
            self.assertEqual([row[0] for row in self.rows(app, "sprint")], expected)
            for index, key in enumerate(expected):
                rendered = "".join(segment.text for segment in
                                   table.render_line(table.header_height + index))
                self.assertIn(key, rendered)
                self.assertEqual(table.cursor_row, index)
                await pilot.press("down")
            await pilot.press("ctrl+home", "down", "down", "down")
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-4")
            self.server.issues[3]["fields"]["status"]["name"] = "In Progress"
            self.server.issues[3]["comments"].append(comment(41))
            await self.refresh(app, pilot)
            self.assertEqual(table.row_count, len(expected))
            self.assertEqual(table.cursor_row, 0)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-4 Comment +1")
            self.assert_row_highlight(app, "sprint", 0, unread=1)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-4"])
            await pilot.press("ctrl+home")
            await pilot.click("#sprint", offset=(5, table.header_height), control=True)
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-1")

    async def test_sprint_height_tracks_rows_with_one_blank_line_between_areas(self):
        self.server.page_size = 100
        async with self.running(size=(110, 40)) as (app, pilot):
            sprint = app.query_one("#sprint", IssueTable)
            other_heading = app.query_one("#other-heading", Static)

            async def assert_layout(count):
                await pilot.pause()
                self.assertEqual(sprint.row_count, count)
                self.assertEqual(sprint.size.height, sprint.header_height + count)
                self.assertEqual(other_heading.region.y - sprint.region.bottom, 1)
                return other_heading.region.y

            initial_y = await assert_layout(1)
            self.server.issues.extend([issue(3, [{"id": 1}]), issue(4, [{"id": 1}])])
            await self.refresh(app, pilot)
            self.assertEqual(await assert_layout(3), initial_y + 2)
            self.server.issues[0]["fields"]["customfield_123"] = None
            await self.refresh(app, pilot)
            self.assertEqual(await assert_layout(2), initial_y + 1)
            for item in self.server.issues:
                item["fields"]["customfield_123"] = None
            await self.refresh(app, pilot)
            self.assertEqual(await assert_layout(0), initial_y - 1)
            self.assertIn("нет задач", str(app.query_one("#sprint-heading", Static).render()))
            self.server.issues[0]["fields"]["customfield_123"] = [{"id": 1}]
            await self.refresh(app, pilot)
            self.assertEqual(await assert_layout(1), initial_y)
            self.server.issues.extend(issue(i, [{"id": 1}]) for i in range(5, 35))
            await self.refresh(app, pilot)
            await pilot.pause()
            self.assertLess(sprint.size.height, sprint.header_height + sprint.row_count)
            self.assertEqual(other_heading.region.y - sprint.region.bottom, 1)
            await pilot.press("ctrl+end")
            self.server.issues = self.server.issues[:2]
            await self.refresh(app, pilot)
            self.assertEqual(await assert_layout(1), initial_y)
            self.assertEqual(sprint.scroll_y, 0)

    async def test_sprint_gap_survives_wrapped_heading_and_horizontal_scrollbar(self):
        self.server.issues[0]["fields"]["summary"] = "Synthetic long task " * 8
        self.server.issues[0]["fields"]["customfield_123"] = [
            {"id": sid} for sid in (1, 2, 4, 5, 6, 7, 8)]
        async with self.running(size=(45, 16)) as (app, pilot):
            sprint = app.query_one("#sprint", IssueTable)
            heading = app.query_one("#sprint-heading", Static)
            other = app.query_one("#other", IssueTable)
            other_heading = app.query_one("#other-heading", Static)
            for width, height in ((45, 16), (160, 45), (45, 16)):
                with self.subTest(size=(width, height)):
                    await pilot.resize_terminal(width, height)
                    await pilot.pause()
                    if width == 45:
                        self.assertEqual(heading.size.height, 3)
                        self.assertTrue(sprint.show_horizontal_scrollbar)
                    self.assertEqual(sprint.size.height, sprint.header_height + sprint.row_count +
                                     (sprint.scrollbar_size_horizontal
                                      if sprint.show_horizontal_scrollbar else 0))
                    self.assertEqual(other_heading.region.y - sprint.region.bottom, 1)
                    self.assertGreater(other.scrollable_content_region.height, other.header_height)
                    self.assertLessEqual(other.region.bottom, height - 1)
                    await pilot.click(offset=(3, sprint.region.bottom))
                    await self.settled(app, pilot)
                    self.assertEqual(self.opened, [])

    async def test_long_sprint_keeps_both_areas_visible_and_independently_scrollable(self):
        self.server.page_size = 100
        self.server.issues = ([issue(i, [{"id": 1}]) for i in range(1, 31)] +
                              [issue(i) for i in range(31, 61)])
        async with self.running(size=(110, 32)) as (app, pilot):
            sprint = app.query_one("#sprint", IssueTable)
            other = app.query_one("#other", IssueTable)
            other_heading = app.query_one("#other-heading", Static)
            for width, height in ((110, 32), (45, 16), (160, 45), (45, 16)):
                with self.subTest(size=(width, height)):
                    await pilot.resize_terminal(width, height)
                    await pilot.pause()
                    self.assertEqual(other_heading.region.y - sprint.region.bottom, 1)
                    self.assertGreater(sprint.scrollable_content_region.height, sprint.header_height)
                    self.assertGreater(other.scrollable_content_region.height, other.header_height)
                    self.assertLessEqual(other.region.bottom, height - 1)
                    self.assertGreater(sprint.max_scroll_y, 0)
                    self.assertGreater(other.max_scroll_y, 0)
                    sprint.focus()
                    await pilot.press("ctrl+end")
                    await pilot.pause()
                    self.assertGreater(sprint.scroll_y, 0)
                    before = sprint.scroll_y
                    await pilot.press("tab", "ctrl+end")
                    await pilot.pause()
                    self.assertIs(app.focused, app.query_one("#other", IssueTable))
                    self.assertGreater(other.scroll_y, 0)
                    self.assertEqual(sprint.scroll_y, before)
                    self.assertEqual(self.opened, [])

    async def test_long_status_is_plain_and_safe_at_minimum_size(self):
        status = "[bold]" + ("Synthetic Status " * 80) + "\x1b\u202e"
        self.server.issues[0]["fields"]["status"]["name"] = status
        async with self.running(size=(45, 16)) as (app, pilot):
            self.assertIn("Synthetic Status", str(self.rows(app, "sprint")))
            self.assertNotIn("\x1b", str(self.rows(app, "sprint")))
            self.assertNotIn("\u202e", str(self.rows(app, "sprint")))
            self.assertIn("[bold]", str(self.rows(app, "sprint")))
            self.assertEqual(self.rows(app, "sprint")[0][0], "DEMO-1")
            # Snapshot acceptance precedes the DataTable idle pass that measures columns.
            await pilot.pause()
            screenshot = ElementTree.fromstring(app.export_screenshot())  # noqa: S314 — our own SVG
            visible_text = " ".join("".join(screenshot.itertext()).split())
            self.assertIn("DEMO-1", visible_text)
            self.assertIn("Synthetic task 1", visible_text)
            await pilot.resize_terminal(160, 45)
            await pilot.resize_terminal(45, 16)

    async def test_resize_controls_markup_and_narrow_screen(self):
        self.server.issues[0]["fields"]["summary"] = "[bold]literal[/bold]\x1b\x07\n\u202e$(touch /tmp/never)"
        async with self.running(size=(45, 16)) as (app, pilot):
            row = self.issue_rows(app, "sprint")[0]
            self.assertIn("[bold]literal[/bold]", row[1])
            self.assertNotIn("\x1b", row[1])
            self.assertNotIn("\u202e", row[1])
            await pilot.resize_terminal(160, 45)
            await pilot.resize_terminal(45, 16)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-1"])
            await pilot.press("q")
            self.assertFalse(app.is_running)

    async def test_family_layout_widths_resize_and_selection_survive_area_moves_and_mode_changes(self):
        self.server.issues = [issue(100, epic=True), issue(10, [{"id": 1}], epic_key="DEMO-100"),
                              issue(123456, [{"id": 1}], parent="DEMO-10"),
                              issue(2, parent="DEMO-10")]
        async with self.running(size=(180, 40)) as (app, pilot):
            sprint = app.query_one("#sprint", IssueTable)
            other = app.query_one("#other", IssueTable)
            self.assertEqual([row[0] for row in self.rows(app, "sprint")], ["DEMO-10", "└─ DEMO-123456"])
            self.assertEqual([row[0] for row in self.rows(app, "other")], ["DEMO-10", "└─ DEMO-2"])
            self.assertEqual(sprint.ordered_columns[0].width, Text("└─ DEMO-123456").cell_len)
            self.assert_status_columns_aligned(app)
            await pilot.press("down")
            self.assertEqual(sprint._key_at(sprint.cursor_row), "123456")
            before = next(self.state_dir.glob("*.json")).read_bytes()
            requests = len(self.server.requests)
            for width, height in ((45, 16), (180, 40)):
                await pilot.resize_terminal(width, height)
                await pilot.pause()
                self.assert_status_columns_aligned(app, rendered=width == 180)
                if width == 45:
                    self.assertTrue(sprint.show_horizontal_scrollbar)
                    await pilot.press("right", "end", "home")
                else:
                    last_row_y = sprint.region.y + sprint.header_height + sprint.row_count
                    self.assertEqual(app.query_one("#other-heading", Static).region.y - last_row_y, 1)
            await pilot.press("e")
            epic = app.query_one("#epic", IssueTable)
            self.assertEqual([row[0] for row in self.rows(app, "epic")],
                             ["DEMO-100", "└─ DEMO-10", "   ├─ DEMO-123456", "   └─ DEMO-2"])
            self.assertEqual(epic._key_at(epic.cursor_row), "123456")
            self.assertEqual(epic.ordered_columns[0].width, Text("   ├─ DEMO-123456").cell_len)
            await pilot.press("up", "down", "ctrl+end", "ctrl+home", "down", "down", "e")
            self.assertEqual(sprint._key_at(sprint.cursor_row), "123456")
            self.assertEqual(next(self.state_dir.glob("*.json")).read_bytes(), before)
            self.assertEqual(len(self.server.requests), requests)
            self.server.issues[2]["fields"]["customfield_123"] = None
            await self.refresh(app, pilot)
            self.assertIs(app.focused, other)
            self.assertEqual(other._key_at(other.cursor_row), "123456")
            self.assertEqual([row[0] for row in self.rows(app, "other")],
                             ["DEMO-10", "├─ DEMO-123456", "└─ DEMO-2"])
            assert app.snapshot is not None
            self.assertEqual(len({item.id for item in app.snapshot.issues if item.tracked}), 4)
            self.assertIn("(2)", str(app.query_one("#other-heading", Static).render()))
            self.assertFalse(self.opened)


if __name__ == "__main__":
    unittest.main()
