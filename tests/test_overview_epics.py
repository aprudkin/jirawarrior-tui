"""Overview epics integration checks; synthetic Jira only."""
import unittest
from xml.etree import ElementTree

from support.jira import comment, issue
from support.overview import OverviewCase
from textual.widgets import Static

from jira_overview.app import IssueTable


class OverviewEpicsTests(OverviewCase):
    async def test_epic_footer_label_is_short_in_both_modes(self):
        self.epic_fixture()
        async with self.running() as (app, pilot):
            for key in (None, "e", "е"):
                if key is not None:
                    await pilot.press(key)
                await pilot.pause()
                screenshot = ElementTree.fromstring(app.export_screenshot())  # noqa: S314 — our own SVG
                visible_text = " ".join("".join(screenshot.itertext()).split())
                self.assertIn("Эпики", visible_text)
                self.assertNotIn("/ список", visible_text)

    async def test_epic_toggle_groups_across_sprints_preserves_selection_and_has_no_side_effects(self):
        self.epic_fixture()
        async with self.running(size=(45, 16)) as (app, pilot):
            self.assertEqual([r[0] for r in self.rows(app, "sprint")], ["DEMO-1"])
            self.assertEqual([r[0] for r in self.rows(app, "other")],
                             ["DEMO-2", "DEMO-3", "DEMO-300", "└─ DEMO-4"])
            saved = next(self.state_dir.glob("*.json")).read_bytes()
            requests = len(self.server.requests)
            await pilot.press("e")
            await pilot.pause()
            self.assertTrue(app.query_one("#epic-area").display)
            self.assertFalse(app.query_one("#sprint-area").display)
            self.assertFalse(app.query_one("#other-area").display)
            table = app.query_one("#epic", IssueTable)
            keys = [r[0].lstrip(" │├└─").split()[0] for r in self.rows(app, "epic")]
            self.assertEqual(keys, ["DEMO-100", "DEMO-1", "DEMO-2", "DEMO-101", "DEMO-200",
                                    "DEMO-300", "DEMO-4"])
            self.assertEqual(table._key_at(table.cursor_row), "1")
            self.assertIn("(0)", self.rows(app, "epic")[3][1])
            self.assertIn("[bold]Контекстный эпик[/bold]", str(self.rows(app, "epic")))
            await pilot.press("down", "e")
            await pilot.pause()
            self.assertIs(app.focused, app.query_one("#other", IssueTable))
            assert isinstance(app.focused, IssueTable)
            self.assertEqual(app.focused._key_at(app.focused.cursor_row), "2")
            self.assertEqual(next(self.state_dir.glob("*.json")).read_bytes(), saved)
            self.assertEqual(len(self.server.requests), requests)
            await pilot.press("е")
            await pilot.resize_terminal(110, 32)
            await pilot.pause()
            self.assertIs(app.focused, app.query_one("#epic", IssueTable))
            self.assertGreater(table.size.height, 0)
        async with self.running() as (app, pilot):
            self.assertFalse(app.query_one("#epic-area").display)
            self.assertIs(app.focused, app.query_one("#sprint", IssueTable))

    async def test_epic_open_context_and_own_markers_and_children_order(self):
        self.epic_fixture()
        async with self.running() as (app, pilot):
            self.server.issues.extend([issue(102, epic=True), issue(5, epic_key="DEMO-100")])
            self.server.issues[0]["comments"].append(comment(19))
            await self.refresh(app, pilot)
            await pilot.press("e")
            await pilot.pause()
            table = app.query_one("#epic", IssueTable)
            keys = [r[0].lstrip(" │├└─") for r in self.rows(app, "epic")]
            self.assertEqual(keys[:4], ["DEMO-100", "DEMO-5 NEW", "DEMO-1 Comment +1", "DEMO-2"])
            self.assertIn("DEMO-102 NEW", keys)
            context_row = next(n for n in range(table.row_count) if table._key_at(n) == "200")
            before = next(self.state_dir.glob("*.json")).read_bytes()
            table.move_cursor(row=context_row)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-200")
            self.assertEqual(next(self.state_dir.glob("*.json")).read_bytes(), before)
            self.assertEqual(self.notice(app), "")
            own_row = next(n for n in range(table.row_count) if table._key_at(n) == "102")
            table.move_cursor(row=own_row)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertNotIn("NEW", str(table.get_row_at(own_row)))
            self.assertEqual(table._key_at(table.cursor_row), "102")
            # Plain clicks only select; Ctrl+click also opens a context epic.
            await pilot.click("#epic", offset=(4, 1), control=True)
            await self.settled(app, pilot)
            opened = len(self.opened)
            table.scroll_to(y=0, animate=False)
            await pilot.pause()
            saved = next(self.state_dir.glob("*.json")).read_bytes()
            await pilot.click("#epic", offset=(4, 0), control=True)
            await pilot.click("#epic", offset=(4, context_row + 1))
            await self.settled(app, pilot)
            self.assertEqual(len(self.opened), opened)
            self.assertEqual(table._key_at(table.cursor_row), "200")
            self.assertEqual(next(self.state_dir.glob("*.json")).read_bytes(), saved)
            await pilot.click("#epic", offset=(4, context_row + 1), control=True)
            await self.settled(app, pilot)
            self.assertEqual(next(self.state_dir.glob("*.json")).read_bytes(), saved)
            self.assertEqual(len(self.opened), opened + 1)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-200")

    async def test_epic_refresh_regroups_selected_ticket_and_empty_mode_is_navigable(self):
        async with self.running() as (app, pilot):
            await pilot.press("e", "down", "ctrl+end", "tab")
            await pilot.pause()
            table = app.query_one("#epic", IssueTable)
            self.assertEqual(table.row_count, 0)
            self.assertIn("нет эпиков", str(app.query_one("#epic-heading", Static).render()))
            await pilot.press("enter")
            self.assertEqual(self.opened, [])
            self.epic_fixture()
            await self.refresh(app, pilot)
            table.move_cursor(row=next(n for n in range(table.row_count) if table._key_at(n) == "2"))
            self.server.issues[1]["fields"]["customfield_789"] = "DEMO-200"
            await self.refresh(app, pilot)
            self.assertEqual(table._key_at(table.cursor_row), "2")
            preceding_epics = [table._key_at(n) for n in range(table.cursor_row)
                               if table.shown[table._key_at(n)].is_epic]
            self.assertEqual(preceding_epics[-1], "200")
            await pilot.press("ctrl+home")
            self.assertEqual(table._key_at(table.cursor_row), "100")
            await pilot.press("ctrl+end")
            # The last visible family is parent 300 followed by its child 4.
            self.assertEqual(table._key_at(table.cursor_row), "4")
            self.assertEqual(table._key_at(table.cursor_row - 1), "300")
            await pilot.press("pageup", "pagedown", "e", "tab")
            await pilot.pause()
            self.assertIn(app.focused, (app.query_one("#sprint", IssueTable),
                                        app.query_one("#other", IssueTable)))


if __name__ == "__main__":
    unittest.main()
