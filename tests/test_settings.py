"""Settings sidebar through real Textual input and synthetic HTTP/state."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from textual.widgets import Input, OptionList, Static

from jira_overview.app import IssueTable, Overview
from jira_overview.core import Jira
from test_overview import Server, TOKEN


class SettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = Server()
        self.temp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp.name)
        self.preference = self.state_dir / "settings.json"
        self.opened = []

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.close)
        self.temp.cleanup()

    async def browser(self, url):
        self.opened.append(url)
        return True

    @asynccontextmanager
    async def running(self, *, size=(110, 32), interval=3600):
        app = Overview(Jira(self.server.url, TOKEN, allow_local_http=True), self.state_dir,
                       interval=interval, browser=self.browser)
        async with app.run_test(size=size, notifications=True) as pilot:
            await self.settled(app, pilot)
            self.assertIsNotNone(app.snapshot)
            yield app, pilot

    async def settled(self, app, pilot):
        for _ in range(300):
            await pilot.pause(0.01)
            if not app.refreshing:
                return
        self.fail("Refresh did not settle")

    def history(self):
        return {p.name: p.read_bytes() for p in self.state_dir.glob("*.json")
                if p != self.preference}

    def screenshot_text(self, app):
        root = ElementTree.fromstring(app.export_screenshot())
        return " ".join("".join(node.text or "" for node in root.iter(
            "{http://www.w3.org/2000/svg}text")).split())

    def seconds_until(self, stamp):
        scheduled = datetime.strptime(stamp.rsplit(" ", 1)[0], "%H:%M:%S")
        now = datetime.now().astimezone()
        return ((scheduled.hour - now.hour) * 3600 + (scheduled.minute - now.minute) * 60 +
                scheduled.second - now.second - now.microsecond / 1_000_000) % 86400

    async def test_s_opens_single_setting_without_network_or_history_changes(self):
        async with self.running() as (app, pilot):
            before, requests = self.history(), list(self.server.requests)
            self.assertEqual(app.active_bindings["s"].binding.description, "Настройки")
            await pilot.press("s")
            choices = app.query_one("#settings-list", OptionList)
            self.assertTrue(app.query_one("#settings").display)
            self.assertFalse(app.query_one("#themes").display)
            self.assertIs(app.focused, choices)
            self.assertEqual(len(choices.options), 1)
            self.assertEqual(str(choices.options[0].prompt), "Интервал обновления: 60 мин")
            self.assertFalse(app.query_one("#interval-editor").display)
            self.assertEqual(self.history(), before)
            self.assertEqual(self.server.requests, requests)
            self.assertEqual(self.opened, [])

    async def test_keyboard_save_applies_immediately_and_survives_restart_over_toml(self):
        async with self.running() as (app, pilot):
            before, requests = self.history(), list(self.server.requests)
            table = app.query_one("#other", IssueTable)
            table.focus()
            await pilot.press("s", "enter")
            self.assertIsInstance(app.focused, Input)
            self.assertEqual(app.focused.value, "60")
            self.assertIn("минутах", str(app.query_one("#interval-label", Static).render()))
            await pilot.press("ctrl+shift+a", "2", "enter")
            self.assertFalse(app.query_one("#settings").display)
            self.assertEqual(app.session.interval, 120)
            self.assertTrue(116 < self.seconds_until(app.session.view.next_refresh_at) <= 120)
            self.assertIs(app.focused, table)
            self.assertEqual(json.loads(self.preference.read_text()),
                             {"version": 1, "refresh_seconds": 120})
            self.assertEqual(self.preference.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.history(), before)
            self.assertEqual(self.server.requests, requests)
        async with self.running(interval=600) as (app, pilot):
            self.assertEqual(app.session.interval, 120)
            await pilot.press("s")
            self.assertIn("2 мин", str(app.query_one("#settings-list", OptionList).options[0].prompt))

    async def test_cancel_via_escape_repeat_s_and_close_discards_input_and_restores_focus(self):
        async with self.running() as (app, pilot):
            table = app.query_one("#other", IssueTable)
            table.focus()
            selected = table._key_at(table.cursor_row)
            schedule = app.session.view.next_refresh_at
            for close in ("escape", "s", "button"):
                with self.subTest(close=close):
                    await pilot.press("s", "enter", "ctrl+shift+a", "3", "0")
                    if close == "button":
                        await pilot.click("#settings-close")
                    else:
                        await pilot.press(close)
                    await pilot.pause()
                    self.assertFalse(app.query_one("#settings").display)
                    self.assertEqual(app.session.interval, 3600)
                    self.assertEqual(app.session.view.next_refresh_at, schedule)
                    self.assertIs(app.focused, table)
                    self.assertEqual(table._key_at(table.cursor_row), selected)
                    self.assertFalse(self.preference.exists())

    async def test_invalid_input_does_not_change_interval_schedule_or_file(self):
        async with self.running() as (app, pilot):
            schedule = app.session.view.next_refresh_at
            await pilot.press("s", "enter")
            editor = app.query_one("#refresh-minutes", Input)
            for value in ("", "0", "-1", "0.08", "1440.01", "nan", "inf", "1e309",
                          "not-a-number"):
                with self.subTest(value=value):
                    editor.value = value
                    await pilot.press("enter")
                    self.assertTrue(app.query_one("#settings").display)
                    self.assertTrue(app.query_one("#settings-error").display)
                    self.assertIn("до 1440 минут", str(app.query_one("#settings-error", Static).render()))
                    self.assertEqual(app.session.interval, 3600)
                    self.assertEqual(app.session.view.next_refresh_at, schedule)
                    self.assertFalse(self.preference.exists())
            editor.value = "1.5"
            await pilot.press("enter")
            self.assertEqual(app.session.interval, 90)
            self.assertEqual(json.loads(self.preference.read_text())["refresh_seconds"], 90)

    async def test_minute_boundaries_are_saved_as_seconds(self):
        for value, seconds in (("0.08333333333333333", 5), ("1440", 86400)):
            with self.subTest(minutes=value):
                async with self.running() as (app, pilot):
                    await pilot.press("s", "enter")
                    app.query_one("#refresh-minutes", Input).value = value
                    await pilot.press("enter")
                    self.assertFalse(app.query_one("#settings").display)
                    self.assertEqual(app.session.interval, seconds)
                    self.assertEqual(json.loads(self.preference.read_text())["refresh_seconds"],
                                     seconds)

    async def test_existing_fractional_seconds_round_trip_without_precision_loss(self):
        for seconds in (5, 5.5, 1234.5678901234567, 421.0610084243126, 86400):
            with self.subTest(seconds=seconds):
                self.preference.write_text(json.dumps({"version": 1, "refresh_seconds": seconds}))
                async with self.running(interval=600) as (app, pilot):
                    self.assertEqual(app.session.interval, seconds)
                    await pilot.press("s", "enter")
                    editor = app.query_one("#refresh-minutes", Input)
                    self.assertAlmostEqual(float(editor.value), seconds / 60)
                    await pilot.press("enter")
                    self.assertFalse(app.query_one("#settings").display)
                    self.assertEqual(app.session.interval, seconds)
                    self.assertEqual(json.loads(self.preference.read_text())["refresh_seconds"],
                                     seconds)

    async def test_mouse_edit_refresh_and_moving_selection_do_not_open_jira(self):
        async with self.running() as (app, pilot):
            await pilot.press("s", "e")
            self.assertFalse(app.epic_mode)
            await pilot.click("#settings-list", offset=(3, 0))
            editor = app.query_one("#refresh-minutes", Input)
            self.assertIs(app.focused, editor)
            editor.value = "2"
            self.server.issues[0]["fields"]["customfield_123"] = []
            await pilot.press("r")
            await self.settled(app, pilot)
            self.assertEqual(editor.value, "2")
            self.assertIs(app.focused, editor)
            for control in (False, True):
                await pilot.click("#other", offset=(4, 1), control=control)
                self.assertEqual(self.opened, [])
            await pilot.press("escape")
            other = app.query_one("#other", IssueTable)
            self.assertIs(app.focused, other)
            self.assertEqual(other._key_at(other.cursor_row), "1")
            self.assertTrue(all(method == "GET" for method, *_ in self.server.requests))
            self.assertFalse(self.preference.exists())

    async def test_automatic_refresh_continues_and_save_does_not_cancel_inflight_load(self):
        async with self.running(interval=0.8) as (app, pilot):
            await pilot.press("s", "enter")
            editor = app.query_one("#refresh-minutes", Input)
            editor.value = "2"
            self.server.request_gate = True
            try:
                self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 3))
                await pilot.pause(0.1)
                self.assertTrue(app.refreshing)
                self.assertIs(app.focused, editor)
                self.assertIn("Updating", str(app.query_one("#connection", Static).render()))
                await pilot.press("enter")
                self.assertEqual(app.session.interval, 120)
                self.assertTrue(app.refreshing)
                self.assertFalse(app.query_one("#settings").display)
            finally:
                self.server.request_gate = False
                self.server.request_release.set()
            await self.settled(app, pilot)
            self.assertIsNone(app.session.view.refresh_error)
            self.assertTrue(116 < self.seconds_until(app.session.view.next_refresh_at) <= 120)
            self.assertEqual(self.opened, [])

    async def test_theme_and_settings_panels_are_mutually_exclusive(self):
        async with self.running() as (app, pilot):
            original = app.theme
            await pilot.press("t", "end")
            self.assertNotEqual(app.theme, original)
            await pilot.press("s")
            self.assertEqual(app.theme, original)
            self.assertFalse(app.query_one("#themes").display)
            self.assertTrue(app.query_one("#settings").display)
            await pilot.press("enter", "ctrl+shift+a", "6", "0", "t")
            self.assertTrue(app.query_one("#themes").display)
            self.assertFalse(app.query_one("#settings").display)
            self.assertFalse(self.preference.exists())
            await pilot.press("escape")
            self.assertIsInstance(app.focused, IssueTable)
            self.assertEqual(self.opened, [])

    async def test_save_failure_preserves_preference_and_timer_then_retry_succeeds(self):
        self.preference.write_text('{"version":1,"refresh_seconds":120}')
        async with self.running() as (app, pilot):
            before = self.preference.read_bytes()
            schedule = app.session.view.next_refresh_at
            await pilot.press("s", "enter")
            app.query_one("#refresh-minutes", Input).value = "5"
            with patch("jira_overview.settings.os.replace", side_effect=PermissionError("private path")):
                await pilot.press("enter")
            self.assertTrue(app.query_one("#settings").display)
            self.assertEqual(app.session.interval, 120)
            self.assertEqual(app.session.view.next_refresh_at, schedule)
            self.assertEqual(self.preference.read_bytes(), before)
            self.assertEqual(list(self.state_dir.glob(".settings-*")), [])
            self.assertIn("Не удалось сохранить интервал",
                          str(app.query_one("#settings-error", Static).render()))
            self.assertNotIn("private path", self.screenshot_text(app))
            await pilot.press("enter")
            self.assertFalse(app.query_one("#settings").display)
            self.assertEqual(app.session.interval, 300)

    async def test_corrupt_preference_falls_back_without_overwrite_or_private_error(self):
        for content in ('private broken content', '[]', '{"version":2,"refresh_seconds":120}',
                        '{"version":1,"refresh_seconds":true}', '{"version":1,"refresh_seconds":4}',
                        '{"version":1,"refresh_seconds":86401}'):
            with self.subTest(content=content):
                self.preference.write_text(content)
                async with self.running(interval=600) as (app, pilot):
                    self.assertEqual(app.session.interval, 600)
                    self.assertIn("Не удалось загрузить интервал", self.screenshot_text(app))
                    self.assertNotIn("private broken content", self.screenshot_text(app))
                    await pilot.press("s", "enter", "escape")
                    self.assertEqual(self.preference.read_text(), content)

    async def test_sidebar_resizes_and_editor_remains_visible(self):
        async with self.running(size=(140, 40)) as (app, pilot):
            await pilot.press("s", "enter")
            for width, height in ((45, 16), (80, 24), (140, 40)):
                with self.subTest(size=(width, height)):
                    await pilot.resize_terminal(width, height)
                    await pilot.pause()
                    panel, areas = app.query_one("#settings"), app.query_one("#areas")
                    self.assertGreater(areas.size.width, 0)
                    self.assertLessEqual(areas.region.right, panel.region.x)
                    self.assertEqual(panel.region.right, width)
                    self.assertLessEqual(panel.region.bottom, height - 1)
                    self.assertLessEqual(app.query_one("#refresh-minutes").region.bottom, height - 1)
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(app.query_one("#areas").size.width, 140)

    async def test_q_during_edit_does_not_save(self):
        async with self.running() as (app, pilot):
            await pilot.press("s", "enter", "ctrl+shift+a", "6", "0", "q")
            self.assertFalse(app.is_running)
        self.assertFalse(self.preference.exists())


if __name__ == "__main__":
    unittest.main()
