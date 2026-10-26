"""Conflict recovery through Textual, synthetic Jira and an owned child process."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from textual.widgets import Button, Static

from jira_overview.app import Overview, OwnerConfirmation
from jira_overview.core import Jira, OverviewError
from test_overview import Server, TOKEN
from test_processes import locked_process


class ConflictRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = Server()
        self.temp = tempfile.TemporaryDirectory(prefix="jira-conflict-ui-")
        self.root = Path(self.temp.name)
        self.state_dir = self.root / "state"
        self.opened = []

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.close)
        self.temp.cleanup()

    async def browser(self, url):
        self.opened.append(url)
        return True

    @asynccontextmanager
    async def running(self, *, interval=3600):
        app = Overview(Jira(self.server.url, TOKEN, allow_local_http=True), self.state_dir,
                       interval=interval, browser=self.browser)
        async with app.run_test(size=(110, 32)) as pilot:
            await self.wait_for(pilot, lambda: not app.refreshing)
            yield app, pilot

    async def wait_for(self, pilot, predicate):
        for _ in range(300):
            await pilot.pause(0.01)
            if predicate():
                return
        self.fail("TUI recovery did not settle")

    async def find(self, app, pilot):
        await pilot.press("p")
        await self.wait_for(pilot, lambda: isinstance(app.screen, OwnerConfirmation))
        await pilot.pause()

    async def test_no_conflict_or_other_error_has_no_process_action(self):
        for status in (200, 500):
            with self.subTest(status=status):
                self.server.status = status
                async with self.running() as (app, pilot):
                    self.assertFalse(app.session.view.profile_busy)
                    self.assertNotIn("p", app.active_bindings)
                    with patch("jira_overview.session.find_lock_owner", new_callable=AsyncMock) as find:
                        await pilot.press("p")
                        find.assert_not_called()
                    self.assertNotIsInstance(app.screen, OwnerConfirmation)

    async def test_find_shows_pid_and_default_enter_or_escape_cancels_without_signal(self):
        async with locked_process(self.root, self.state_dir, self.server.url) as process:
            async with self.running() as (app, pilot):
                self.assertTrue(app.session.view.profile_busy)
                self.assertIsNone(app.snapshot)
                self.assertIn("p", app.active_bindings)
                self.assertIn("P — найти", str(app.query_one("#notice", Static).render()))
                files = {p.name: p.read_bytes() for p in self.state_dir.iterdir()}
                for cancel in ("enter", "escape"):
                    await self.find(app, pilot)
                    self.assertEqual(app.screen.owner.pid, process.pid)
                    self.assertEqual(app.focused.id, "cancel-owner")
                    self.assertIn(str(process.pid), str(app.screen.query_one("#owner-question", Static).render()))
                    with patch("jira_overview.processes.os.kill") as kill:
                        await pilot.press(cancel)
                        await self.wait_for(pilot, lambda: not isinstance(app.screen, OwnerConfirmation))
                        kill.assert_not_called()
                    self.assertIsNone(process.returncode)
                    self.assertTrue(app.session.view.profile_busy)
                self.assertEqual(files, {p.name: p.read_bytes() for p in self.state_dir.iterdir()})
                self.assertEqual(self.opened, [])

    async def test_confirm_stops_only_own_child_and_reloads_automatically(self):
        async with locked_process(self.root, self.state_dir, self.server.url) as process:
            async with self.running() as (app, pilot):
                await self.find(app, pilot)
                await pilot.click("#stop-owner")
                await self.wait_for(pilot, lambda: app.snapshot is not None and not app.refreshing)
                await asyncio.wait_for(process.wait(), 3)
                self.assertEqual(process.returncode, 0)
                self.assertFalse(app.session.view.profile_busy)
                self.assertFalse(app.session.view.recovery_busy)
                self.assertIsNone(app.session.view.lock_owner)
                self.assertNotIn("p", app.active_bindings)
                self.assertNotIsInstance(app.screen, OwnerConfirmation)
                self.assertTrue(list(self.state_dir.glob("*.json")))
                self.assertEqual(self.opened, [])
                self.assertTrue(all(method == "GET" for method, *_ in self.server.requests))

    async def test_keyboard_tab_and_shift_tab_can_select_and_confirm_stop(self):
        for key in ("tab", "shift+tab"):
            with self.subTest(key=key):
                async with locked_process(self.root, self.state_dir, self.server.url) as process:
                    async with self.running() as (app, pilot):
                        await self.find(app, pilot)
                        await pilot.press(key)
                        self.assertEqual(app.focused.id, "stop-owner")
                        await pilot.press("enter")
                        await self.wait_for(pilot, lambda: app.snapshot is not None and not app.refreshing)
                        await asyncio.wait_for(process.wait(), 3)
                        self.assertEqual(process.returncode, 0)
                        self.assertEqual(self.opened, [])

    async def test_confirmation_remains_valid_across_automatic_timer_ticks(self):
        async with locked_process(self.root, self.state_dir, self.server.url) as process:
            async with self.running(interval=0.3) as (app, pilot):
                await self.find(app, pilot)
                owner = app.screen.owner
                requests = len(self.server.requests)
                schedule = app.session.view.next_refresh_at
                await self.wait_for(pilot, lambda: app.session.view.next_refresh_at != schedule
                                    and not app.refreshing)
                self.assertEqual(app.session.view.lock_owner, owner)
                self.assertEqual(len(self.server.requests), requests)
                await pilot.click("#stop-owner")
                await self.wait_for(pilot, lambda: app.snapshot is not None and not app.refreshing)
                await asyncio.wait_for(process.wait(), 3)
                self.assertFalse(app.session.view.profile_busy)

    async def test_owner_already_closed_before_confirmation_is_not_signalled_again(self):
        async with locked_process(self.root, self.state_dir, self.server.url) as process:
            async with self.running() as (app, pilot):
                await self.find(app, pilot)
                process.send_signal(signal.SIGINT)
                await asyncio.wait_for(process.wait(), 3)
                with patch("jira_overview.processes.os.kill") as kill:
                    await pilot.click("#stop-owner")
                    await self.wait_for(pilot, lambda: app.snapshot is not None and not app.refreshing)
                    kill.assert_not_called()
                self.assertFalse(app.session.view.profile_busy)

    async def test_changed_owner_at_confirmation_refuses_and_keeps_original_process(self):
        async with locked_process(self.root, self.state_dir, self.server.url) as process:
            async with self.running() as (app, pilot):
                await self.find(app, pilot)
                stale = replace(app.screen.owner, started="different process")
                with patch("jira_overview.processes.find_lock_owner", AsyncMock(return_value=stale)), \
                        patch("jira_overview.processes.os.kill") as kill:
                    await pilot.click("#stop-owner")
                    await self.wait_for(pilot, lambda: not app.session.view.recovery_busy)
                    kill.assert_not_called()
                self.assertTrue(app.session.view.profile_busy)
                self.assertIn("изменился", app.session.view.recovery_notice)
                self.assertIsNone(process.returncode)
                self.assertFalse(list(self.state_dir.glob("*.json")))

    async def test_discovery_error_is_visible_and_can_be_retried(self):
        async with locked_process(self.root, self.state_dir, self.server.url) as process:
            async with self.running() as (app, pilot):
                with patch("jira_overview.session.find_lock_owner", AsyncMock(
                        side_effect=OverviewError("Поиск процесса недоступен; нажмите R."))):
                    await pilot.press("p")
                    await self.wait_for(pilot, lambda: not app.session.view.recovery_busy)
                self.assertIn("Поиск процесса недоступен", str(app.query_one("#notice", Static).render()))
                self.assertIsNone(process.returncode)
                await self.find(app, pilot)
                await pilot.click("#cancel-owner")
                self.assertTrue(app.session.view.profile_busy)

    async def test_closed_owner_before_lookup_reloads_without_confirmation(self):
        async with locked_process(self.root, self.state_dir, self.server.url) as process:
            async with self.running() as (app, pilot):
                process.send_signal(signal.SIGINT)
                await asyncio.wait_for(process.wait(), 3)
                with patch("jira_overview.processes.os.kill") as kill:
                    await pilot.press("p")
                    await self.wait_for(pilot, lambda: app.snapshot is not None and not app.refreshing)
                    kill.assert_not_called()
                self.assertNotIsInstance(app.screen, OwnerConfirmation)

    async def test_confirmation_buttons_are_visible_at_minimum_size(self):
        async with locked_process(self.root, self.state_dir, self.server.url) as process:
            async with self.running() as (app, pilot):
                await pilot.resize_terminal(45, 16)
                await self.find(app, pilot)
                for name in ("stop-owner", "cancel-owner"):
                    button = app.screen.query_one("#" + name, Button)
                    self.assertGreaterEqual(button.region.y, 0)
                    self.assertLessEqual(button.region.bottom, 16)
                    self.assertTrue(button.region.width > 0)
                await pilot.press("tab", "enter")
                await self.wait_for(pilot, lambda: app.snapshot is not None and not app.refreshing)
                await asyncio.wait_for(process.wait(), 3)
                self.assertEqual(process.returncode, 0)

    async def test_final_animation_during_screen_teardown_does_not_query_removed_widgets(self):
        finished = asyncio.Event()
        class FinalAnimation(Static):
            async def on_unmount(widget):
                await asyncio.sleep(0.01)
                widget.app.animate_refresh()
                finished.set()
        try:
            async with self.running() as (app, pilot):
                await app.mount(FinalAnimation())
                self.server.request_started.clear()
                self.server.request_release.clear()
                self.server.request_gate = True
                app.session.refresh()
                self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 2))
                self.assertTrue(app.refreshing)
            await asyncio.wait_for(finished.wait(), 1)
            self.assertTrue(app.session.view.closed)
        finally:
            self.server.request_gate = False
            self.server.request_release.set()

    async def test_lookup_is_single_flight_and_quit_cancels_it(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def waiting(path):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        async with locked_process(self.root, self.state_dir, self.server.url) as process:
            with patch("jira_overview.session.find_lock_owner", side_effect=waiting) as find:
                async with self.running() as (app, pilot):
                    await pilot.press("p")
                    await asyncio.wait_for(started.wait(), 2)
                    requests = len(self.server.requests)
                    await pilot.press("p", "p", "r")
                    self.assertEqual(find.call_count, 1)
                    self.assertEqual(len(self.server.requests), requests)
                    await pilot.press("q")
                await asyncio.wait_for(cancelled.wait(), 1)
                self.assertTrue(app.session.view.closed)
                self.assertFalse(app.session.view.recovery_busy)
                self.assertIsNone(process.returncode)


if __name__ == "__main__":
    unittest.main()
