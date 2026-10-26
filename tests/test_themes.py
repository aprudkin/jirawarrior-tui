"""Theme selection through real Textual input, loopback Jira and temporary state."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from textual.widgets import OptionList

from jira_overview.app import IssueTable, Overview
from jira_overview.core import Jira
from test_overview import Server, TOKEN, issue


class ThemeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = Server()
        self.temp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp.name)
        self.preference = self.state_dir / "theme.json"
        self.opened = []

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.close)
        self.temp.cleanup()

    async def browser(self, url):
        self.opened.append(url)
        return True

    @asynccontextmanager
    async def running(self, size=(110, 32)):
        app = Overview(Jira(self.server.url, TOKEN, allow_local_http=True), self.state_dir,
                       interval=3600, browser=self.browser)
        async with app.run_test(size=size, notifications=True) as pilot:
            for _ in range(300):
                await pilot.pause(0.01)
                if app.snapshot and not app.refreshing:
                    break
            self.assertIsNotNone(app.snapshot)
            yield app, pilot

    def history(self):
        return {path.name: path.read_bytes() for path in self.state_dir.glob("*.json")
                if path != self.preference}

    def highlighted(self, app):
        return app.query_one("#theme-list", OptionList).highlighted_option.id

    def screenshot_text(self, app):
        root = ElementTree.fromstring(app.export_screenshot())
        return " ".join("".join(node.text or "" for node in root.iter("{http://www.w3.org/2000/svg}text")).split())

    async def test_palette_is_gone_from_bindings_footer_and_actions(self):
        async with self.running() as (app, pilot):
            self.assertFalse(app.use_command_palette)
            self.assertNotIn("ctrl+p", app.active_bindings)
            self.assertIn("t", app.active_bindings)
            self.assertEqual(app.active_bindings["t"].binding.description, "Темы")
            before = tuple(app.screen_stack)
            await pilot.press("ctrl+p")
            app.action_command_palette()
            await pilot.pause()
            self.assertEqual(tuple(app.screen_stack), before)
            self.assertFalse(app.query("CommandPalette"))
            self.assertNotIn("palette", self.screenshot_text(app).lower())
            # The inherited change-theme action must also use our sidebar, not
            # Textual's separate CommandPalette-based theme picker.
            app.action_change_theme()
            await pilot.pause()
            self.assertTrue(app.query_one("#themes").display)
            self.assertEqual(tuple(app.screen_stack), before)

    async def test_groups_are_dark_then_light_sorted_with_current_selected(self):
        async with self.running() as (app, pilot):
            original = app.theme
            await pilot.press("t")
            choices = app.query_one("#theme-list", OptionList)
            expected = []
            for dark, title in ((True, "Тёмные"), (False, "Светлые")):
                expected.append((title, None, True))
                expected.extend((name, name, False) for name, theme in sorted(app.available_themes.items())
                                if theme.dark == dark and name != "textual-ansi")
            self.assertEqual([(str(o.prompt), o.id, o.disabled) for o in choices.options], expected)
            self.assertEqual(self.highlighted(app), original)
            self.assertEqual(app.theme, original)
            self.assertIs(app.focused, choices)

    async def test_navigation_previews_actual_colors_without_jira_or_history_writes(self):
        async with self.running() as (app, pilot):
            await pilot.press("t")
            before_history = self.history()
            before_requests = list(self.server.requests)
            original_background = app.screen.styles.background
            await pilot.press("end")
            self.assertEqual(self.highlighted(app), "textual-light")
            self.assertEqual(app.theme, "textual-light")
            self.assertNotEqual(app.screen.styles.background, original_background)
            await pilot.press("home")
            self.assertEqual(self.highlighted(app), "catppuccin-mocha")
            await pilot.press("pagedown", "pageup", "down", "up")
            self.assertEqual(app.theme, self.highlighted(app))
            self.assertFalse(app.query_one("#theme-list", OptionList).highlighted_option.disabled)
            await pilot.press("end", "up", "up", "up")
            self.assertEqual(app.theme, "tokyo-night")  # skips the light-group heading
            self.assertEqual(self.server.requests, before_requests)
            self.assertEqual(self.history(), before_history)
            self.assertFalse(self.preference.exists())
            self.assertEqual(self.opened, [])

    async def test_escape_repeat_t_and_close_button_cancel_and_restore_focus(self):
        async with self.running() as (app, pilot):
            table = app.query_one("#other", IssueTable)
            table.focus()
            original = app.theme
            for close in ("escape", "t", "button"):
                with self.subTest(close=close):
                    await pilot.press("t", "end")
                    self.assertNotEqual(app.theme, original)
                    if close == "button":
                        await pilot.click("#theme-close")
                    else:
                        await pilot.press(close)
                    await pilot.pause()
                    self.assertFalse(app.query_one("#themes").display)
                    self.assertEqual(app.theme, original)
                    self.assertIs(app.focused, table)
                    self.assertEqual(table._key_at(table.cursor_row), "2")
                    self.assertFalse(self.preference.exists())

    async def test_mouse_previews_but_only_enter_commits_and_survives_restart(self):
        async with self.running() as (app, pilot):
            before = self.history()
            await pilot.press("t", "home")
            await pilot.click("#theme-list", offset=(3, 2))
            self.assertEqual(app.theme, "dracula")
            self.assertTrue(app.query_one("#themes").display)
            self.assertFalse(self.preference.exists())
            await pilot.press("enter")
            self.assertFalse(app.query_one("#themes").display)
            self.assertEqual(json.loads(self.preference.read_text()), {"version": 1, "theme": "dracula"})
            self.assertEqual(self.preference.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.history(), before)
            self.assertEqual(self.opened, [])
        async with self.running() as (app, pilot):
            self.assertEqual(app.theme, "dracula")
            await pilot.press("t")
            self.assertEqual(self.highlighted(app), "dracula")
            await pilot.press("end", "escape")
            self.assertEqual(app.theme, "dracula")
            self.assertEqual(json.loads(self.preference.read_text())["theme"], "dracula")

    async def test_background_refresh_preserves_preview_and_selected_issue(self):
        async with self.running() as (app, pilot):
            sprint = app.query_one("#sprint", IssueTable)
            await pilot.press("t", "end", "e")
            self.assertFalse(app.epic_mode)
            # Moving the original task between areas must not steal panel focus.
            self.server.issues[0]["fields"]["customfield_123"] = []
            await pilot.press("r")
            for _ in range(300):
                await pilot.pause(0.01)
                if not app.refreshing:
                    break
            self.assertEqual(app.theme, "textual-light")
            self.assertIsInstance(app.focused, OptionList)
            await pilot.click("#other", offset=(4, 1))
            self.assertEqual(self.opened, [])
            await pilot.press("escape")
            other = app.query_one("#other", IssueTable)
            self.assertIs(app.focused, other)
            self.assertEqual(other._key_at(other.cursor_row), "1")
            self.assertTrue(sprint.can_focus)
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(0.01)
                if self.opened:
                    break
            self.assertEqual(len(self.opened), 1)

    async def test_epic_mode_and_selection_survive_panel(self):
        self.server.issues = [issue(10, epic=True), issue(1, epic_key="DEMO-10")]
        async with self.running() as (app, pilot):
            await pilot.press("e", "down")
            epic = app.query_one("#epic", IssueTable)
            selected = epic._key_at(epic.cursor_row)
            await pilot.press("t", "end", "escape")
            self.assertTrue(app.epic_mode)
            self.assertIs(app.focused, epic)
            self.assertEqual(epic._key_at(epic.cursor_row), selected)

    async def test_save_failure_keeps_panel_and_previous_preference(self):
        self.preference.write_text('{"version":1,"theme":"dracula"}')
        async with self.running() as (app, pilot):
            await pilot.press("t", "end")
            with patch("jira_overview.themes.os.replace", side_effect=PermissionError("private path")):
                await pilot.press("enter")
                await pilot.pause()
            self.assertTrue(app.query_one("#themes").display)
            self.assertEqual(app.theme, "textual-light")
            self.assertEqual(json.loads(self.preference.read_text())["theme"], "dracula")
            self.assertEqual(list(self.state_dir.glob(".theme-*")), [])
            screenshot = self.screenshot_text(app)
            self.assertIn("Не удалось сохранить тему", screenshot)
            self.assertNotIn("private path", screenshot)
            await pilot.press("escape")
            self.assertEqual(app.theme, "dracula")

    async def test_invalid_preferences_do_not_block_jira_or_get_overwritten(self):
        for content in ('broken private content', '[]', '{"version":2,"theme":"dracula"}',
                        '{"version":1,"theme":[]}', '{"version":1,"theme":"missing"}',
                        '{"version":1,"theme":"textual-ansi"}'):
            with self.subTest(content=content):
                self.preference.write_text(content)
                async with self.running() as (app, pilot):
                    self.assertEqual(app.theme, "textual-dark")
                    await pilot.press("t", "end", "escape")
                    self.assertEqual(self.preference.read_text(), content)
                    self.assertNotIn("broken private content", self.screenshot_text(app))

    async def test_panel_resizes_without_covering_overview_or_footer(self):
        async with self.running(size=(140, 40)) as (app, pilot):
            await pilot.press("t")
            for width, height in ((45, 16), (80, 24), (140, 40)):
                with self.subTest(size=(width, height)):
                    await pilot.resize_terminal(width, height)
                    await pilot.pause()
                    panel = app.query_one("#themes")
                    areas = app.query_one("#areas")
                    self.assertGreater(areas.size.width, 0)
                    self.assertLessEqual(areas.region.right, panel.region.x)
                    self.assertEqual(panel.region.right, width)
                    self.assertLessEqual(panel.region.bottom, height - 1)
                    self.assertGreater(app.query_one("#theme-list").size.height, 0)
                    await pilot.press("end", "home")
            await pilot.press("t")
            await pilot.pause()
            self.assertEqual(app.query_one("#areas").size.width, 140)

    async def test_quitting_during_preview_does_not_save_it(self):
        async with self.running() as (app, pilot):
            await pilot.press("t", "end", "q")
        self.assertFalse(self.preference.exists())


if __name__ == "__main__":
    unittest.main()
