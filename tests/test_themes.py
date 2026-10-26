"""Theme selection through real Textual input, loopback Jira and temporary state."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from rich.color import Color
from rich.text import Text
from textual.color import Color as UIColour
from textual.widgets import OptionList

from jira_overview.app import IssueTable, Overview
from jira_overview.presentation import OverviewPresentation
from jira_overview.core import Jira
from jira_overview.themes import ADDITIONAL_THEMES
from test_overview import Server, TOKEN, comment, issue


# Independent expectations: names, mode and upstream base/text colours.
EXTRA_THEMES = {
    "rose-pine": (True, "#191724", "#e0def4"),
    "rose-pine-dawn": (False, "#faf4ed", "#464261"),
    "everforest-dark": (True, "#2d353b", "#d3c6aa"),
    "everforest-light": (False, "#fdf6e3", "#5c6a72"),
    "kanagawa-wave": (True, "#1f1f28", "#dcd7ba"),
    "gruvbox-light": (False, "#fbf1c7", "#3c3836"),
    "one-dark": (True, "#282c34", "#abb2bf"),
    "solarized-dark": (True, "#002b36", "#93a1a1"),
    "ayu-dark": (True, "#0d1017", "#bfbdb6"),
    "ayu-mirage": (True, "#1f2430", "#cccac2"),
    "night-owl": (True, "#011627", "#d6deeb"),
    "github-dark": (True, "#24292e", "#e1e4e8"),
    "catppuccin-frappe": (True, "#303446", "#c6d0f5"),
    "catppuccin-macchiato": (True, "#24273a", "#cad3f5"),
    "rose-pine-moon": (True, "#232136", "#e0def4"),
    "kanagawa-dragon": (True, "#181616", "#c5c9c5"),
}

BASE16_THEMES = {
    "atlas": (True, "#002635", "#a1a19a"),
    "ashes": (True, "#1c2023", "#c7ccd1"),
    "bespin": (True, "#28211c", "#9d9b97"),
    "brewer": (True, "#0c0d0e", "#b7b8b9"),
    "chalk": (True, "#151515", "#d0d0d0"),
    "darcula": (True, "#2b2b2b", "#a9b7c6"),
    "eighties": (True, "#2d2d2d", "#d3d0c8"),
    "embers": (True, "#16130f", "#a39a90"),
    "espresso": (True, "#2d2d2d", "#cccccc"),
    "flat": (True, "#2c3e50", "#e0e0e0"),
    "github-dark-dimmed": (True, "#0d1117", "#d1d7e0"),
    "gruvbox-material-dark-medium": (True, "#292828", "#ddc7a1"),
    "horizon-dark": (True, "#1c1e26", "#cbced0"),
    "material": (True, "#263238", "#eeffff"),
    "material-darker": (True, "#212121", "#eeffff"),
    "material-palenight": (True, "#292d3e", "#ffffff"),
    "oceanicnext": (True, "#1b2b34", "#c0c5ce"),
    "spaceduck": (True, "#16172d", "#ecf0c1"),
    "tomorrow-night": (True, "#1d1f21", "#c5c8c6"),
    "zenburn": (True, "#383838", "#dcdccc"),
    "ayu-light": (False, "#f8f9fa", "#5c6166"),
    "github-light": (False, "#ffffff", "#454c54"),
    "gruvbox-material-light-medium": (False, "#fbf1c7", "#654735"),
    "horizon-light": (False, "#fdf0ed", "#403c3d"),
    "material-lighter": (False, "#fafafa", "#000000"),
    "one-light": (False, "#fafafa", "#383a42"),
    "papercolor-light": (False, "#eeeeee", "#444444"),
    "selenized-light": (False, "#fbf3db", "#53676d"),
    "tomorrow": (False, "#ffffff", "#373b41"),
    "atelier-sulphurpool-light": (False, "#f5f7ff", "#293256"),
}
EXTRA_THEMES.update(BASE16_THEMES)


def contrast(foreground, background):
    def luminance(color):
        channels = [component / 255 for component in color.get_truecolor()]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


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

    async def select_theme(self, app, pilot, name):
        choices = app.query_one("#theme-list", OptionList)
        names = [option.id for option in choices.options if not option.disabled]
        index = names.index(name)
        current = names.index(choices.highlighted_option.id)
        # Keep real keyboard input, taking the shortest path from the current
        # row or either end; disabled group headings must still be skipped.
        keys = min((["home"] + ["down"] * index,
                    ["end"] + ["up"] * (len(names) - 1 - index),
                    ["down" if index > current else "up"] * abs(index - current)), key=len)
        if keys:
            await pilot.press(*keys)
        self.assertEqual(self.highlighted(app), name)
        self.assertEqual(app.theme, name)

    async def test_extra_theme_inventory_and_default(self):
        async with self.running() as (app, pilot):
            self.assertEqual(app.theme, "textual-dark")
            themes = {name: theme for name, theme in app.available_themes.items() if name != "textual-ansi"}
            self.assertEqual(len(themes), 57)
            self.assertEqual(sum(theme.dark for theme in themes.values()), 41)
            self.assertEqual(sum(not theme.dark for theme in themes.values()), 16)
            self.assertEqual(len(ADDITIONAL_THEMES), 46)
            self.assertEqual({theme.name for theme in ADDITIONAL_THEMES}, set(EXTRA_THEMES))
            self.assertEqual(len(BASE16_THEMES), 30)
            self.assertEqual(sum(dark for dark, _, _ in BASE16_THEMES.values()), 20)
            for name, (dark, background, foreground) in EXTRA_THEMES.items():
                with self.subTest(theme=name):
                    theme = themes[name]
                    self.assertEqual(theme.dark, dark)
                    self.assertEqual(theme.background.lower(), background)
                    self.assertEqual(theme.foreground.lower(), foreground)
                    for role in ("background", "surface", "panel"):
                        self.assertGreaterEqual(contrast(Color.parse(foreground),
                                                         Color.parse(getattr(theme, role))), 4.5)
                        if name in BASE16_THEMES:
                            self.assertGreaterEqual(contrast(Color.parse(theme.error),
                                                             Color.parse(getattr(theme, role))), 4.5)

    async def test_each_extra_theme_previews_cancels_saves_and_restarts(self):
        for name in EXTRA_THEMES:
            with self.subTest(theme=name):
                async with self.running() as (app, pilot):
                    original = app.theme
                    table = app.query_one("#other", IssueTable)
                    table.focus()
                    before_history, before_requests = self.history(), list(self.server.requests)
                    await pilot.press("t")
                    await self.select_theme(app, pilot, name)
                    self.assertEqual(app.screen.styles.background, UIColour.parse(EXTRA_THEMES[name][1]))
                    await pilot.press("escape")
                    self.assertEqual(app.theme, original)
                    self.assertIs(app.focused, table)
                    await pilot.press("t")
                    await self.select_theme(app, pilot, name)
                    await pilot.press("enter")
                    self.assertEqual(json.loads(self.preference.read_text()), {"version": 1, "theme": name})
                    self.assertEqual(self.preference.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(self.history(), before_history)
                    self.assertEqual(self.server.requests, before_requests)
                    self.assertFalse(self.opened)
                async with self.running() as (app, pilot):
                    self.assertEqual(app.theme, name)
                    await pilot.press("t")
                    self.assertEqual(self.highlighted(app), name)
                    await pilot.press("escape", "s")
                    self.assertTrue(app.query_one("#settings").display)
                    self.assertIn("Интервал обновления", self.screenshot_text(app))
                    await pilot.press("enter", "ctrl+shift+a", "0", "enter")
                    # The rendered sidebar wraps this message across lines.
                    self.assertRegex(self.screenshot_text(app), r"до 1440.*минут\.")
                    if name in BASE16_THEMES:
                        error = app.query_one("#settings-error")
                        rendered = Text.assemble(*[(s.text, s.style) for s in error.render_line(0)])
                        start = next(i for i, char in enumerate(rendered.plain) if not char.isspace())
                        style = rendered.get_style_at_offset(app.console, start)
                        self.assertGreaterEqual(contrast(style.color, style.bgcolor), 4.5, name)
                    self.assertFalse((self.state_dir / "settings.json").exists())
                    await pilot.press("escape")
                    self.assertEqual(app.theme, name)

    async def test_extra_themes_keep_table_text_markers_and_cursor_readable(self):
        async with self.running() as (app, pilot):
            self.server.issues.append(issue(4))
            for add_comment in (False, True):
                if add_comment:
                    self.server.issues[-1]["comments"].append(comment(41))
                await pilot.press("r")
                for _ in range(300):
                    await pilot.pause(0.01)
                    if not app.refreshing:
                        break
                self.assertFalse(app.refreshing)
            table = app.query_one("#other", IssueTable)
            before_history, before_requests = self.history(), list(self.server.requests)
            for name in EXTRA_THEMES:
                with self.subTest(theme=name):
                    await pilot.press("t")
                    await self.select_theme(app, pilot, name)
                    await pilot.press("enter")
                    self.assertIn("Synthetic task 4", self.screenshot_text(app))
                    for cursor_row in (0, 1):
                        for focused in (True, False):
                            table.move_cursor(row=cursor_row)
                            (table if focused else app.query_one("#sprint")).focus()
                            await pilot.pause()
                            rendered = Text.assemble(*[(s.text, s.style) for s in table.render_line(table.header_height)])
                            self.assertIn("DEMO-4 NEW Comment +1", rendered.plain)
                            key_style = rendered.get_style_at_offset(app.console, rendered.plain.index("DEMO-4"))
                            self.assertGreaterEqual(contrast(key_style.color, key_style.bgcolor), 4.5, name)
                            for label, color in (("NEW", "green"), ("Comment +1", "yellow")):
                                start = rendered.plain.index(label)
                                for offset in range(start, start + len(label)):
                                    style = rendered.get_style_at_offset(app.console, offset)
                                    self.assertTrue(style.bold)
                                    self.assertEqual(style.color, Color.parse(color))
                                    # Named ANSI marker colours belong to the terminal palette;
                                    # retain their colour/bold/text contract, not a universal
                                    # contrast claim based on Rich's fallback ANSI RGB values.
                                    self.assertNotEqual(style.color.get_truecolor(), style.bgcolor.get_truecolor())
                            if focused and cursor_row == 0:
                                self.assertEqual(key_style.bgcolor, table.get_component_rich_style("datatable--cursor").bgcolor)
                    self.assertEqual(self.history(), before_history)
                    self.assertEqual(self.server.requests, before_requests)
                    self.assertFalse(self.opened)

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
            self.assertEqual(self.highlighted(app), "tomorrow")
            self.assertEqual(app.theme, "tomorrow")
            self.assertNotEqual(app.screen.styles.background, original_background)
            await pilot.press("home")
            self.assertEqual(self.highlighted(app), "ashes")
            await pilot.press("pagedown", "pageup", "down", "up")
            self.assertEqual(app.theme, self.highlighted(app))
            self.assertFalse(app.query_one("#theme-list", OptionList).highlighted_option.disabled)
            light_count = sum(not theme.dark for name, theme in app.available_themes.items()
                              if name != "textual-ansi")
            await pilot.press("end", *(["up"] * light_count))
            self.assertEqual(app.theme, "zenburn")  # skips the light-group heading
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
            await pilot.press("t")
            await self.select_theme(app, pilot, "ayu-dark")
            choices = app.query_one("#theme-list", OptionList)
            # Account for the header having scrolled out of the viewport.
            row = choices.get_option_index("ayu-mirage") - int(choices.scroll_y)
            await pilot.click("#theme-list", offset=(3, row))
            self.assertEqual(app.theme, "ayu-mirage")
            self.assertTrue(app.query_one("#themes").display)
            self.assertFalse(self.preference.exists())
            await pilot.press("enter")
            self.assertFalse(app.query_one("#themes").display)
            self.assertEqual(json.loads(self.preference.read_text()), {"version": 1, "theme": "ayu-mirage"})
            self.assertEqual(self.preference.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.history(), before)
            self.assertEqual(self.opened, [])
        async with self.running() as (app, pilot):
            self.assertEqual(app.theme, "ayu-mirage")
            await pilot.press("t")
            self.assertEqual(self.highlighted(app), "ayu-mirage")
            await pilot.press("end", "escape")
            self.assertEqual(app.theme, "ayu-mirage")
            self.assertEqual(json.loads(self.preference.read_text())["theme"], "ayu-mirage")

    async def test_background_refresh_preserves_preview_and_selected_issue(self):
        async with self.running() as (app, pilot):
            sprint = app.query_one("#sprint", IssueTable)
            await pilot.press("t")
            await self.select_theme(app, pilot, "textual-light")
            await pilot.press("e")
            self.assertFalse(app.query_one("#presentation", OverviewPresentation).epic_mode)
            # Moving the original task between areas must not steal panel focus.
            self.server.issues[0]["fields"]["customfield_123"] = []
            await pilot.press("r")
            for _ in range(300):
                await pilot.pause(0.01)
                if not app.refreshing:
                    break
            self.assertEqual(app.theme, "textual-light")
            self.assertIsInstance(app.focused, OptionList)
            for control in (False, True):
                await pilot.click("#other", offset=(4, 1), control=control)
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
            self.assertTrue(app.query_one("#presentation", OverviewPresentation).epic_mode)
            self.assertIs(app.focused, epic)
            self.assertEqual(epic._key_at(epic.cursor_row), selected)

    async def test_save_failure_keeps_panel_and_previous_preference(self):
        self.preference.write_text('{"version":1,"theme":"dracula"}')
        async with self.running() as (app, pilot):
            await pilot.press("t")
            await self.select_theme(app, pilot, "textual-light")
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
