"""Overview publication and connection integration checks; synthetic Jira only."""
import asyncio
import json
import time
import unittest
from datetime import datetime

from support.jira import BODY, TOKEN, Server, comment, issue
from support.overview import OverviewCase
from textual.widgets import Static

from jira_overview.app import IssueTable, Overview
from jira_overview.core import Jira, State


class OverviewTests(OverviewCase):
    async def test_baseline_pagination_regions_and_read_only(self):
        self.server.issues[0]["comments"] = [comment(1), comment(2), comment(3)]
        async with self.running() as (app, pilot):
            self.assertIn("DEMO-1", str(self.rows(app, "sprint")))
            self.assertIn("DEMO-2", str(self.rows(app, "other")))
            self.assertNotIn("NEW", self.visible(app))
            self.assertNotIn("Comment", self.visible(app))
            self.assertIn("Synthetic User", self.status(app))
            self.assertIn("(1)", str(app.query_one("#sprint-heading", Static).render()))
            self.assertTrue(any(p.get("startAt") == ["2"] for _, path, p, _ in self.server.requests if path.endswith("/comment")))
            self.assertTrue(all(method == "GET" for method, *_ in self.server.requests))
            queries = [p for _, path, p, _ in self.server.requests if path.endswith("/search")]
            self.assertIn("currentUser()", queries[0]["jql"][0])
            self.assertIn("resolution = Unresolved", queries[0]["jql"][0])
            saved = "".join(p.read_text() for p in self.state_dir.glob("*.json"))
            for sensitive in (TOKEN, BODY, "Synthetic task", "Synthetic User", self.server.url):
                self.assertNotIn(sensitive, saved)

    async def test_overview_loads_when_instance_has_no_verifying_status(self):
        self.server.reject_unknown_verifying = True
        async with self.running() as (app, pilot):
            self.assertIsNotNone(app.snapshot)
            self.assertEqual([row[0] for row in self.rows(app, "sprint")], ["DEMO-1"])
            self.assertEqual([row[0] for row in self.rows(app, "other")], ["DEMO-2"])
            self.assertNotIn("УСТАРЕЛО", self.status(app))

    async def test_verifying_is_excluded_after_full_pagination_before_related_data_and_state(self):
        self.server.issues = [issue(1, [{"id": 1}]), issue(2),
                              issue(3, [{"id": 999}], epic_key="DEMO-999"),
                              issue(4), issue(5, epic=True), issue(6)]
        for item, status in zip(self.server.issues,
                                ["In Progress", "To Do", "Verifying", "VERIFYING",
                                 "verifying", "Awaiting Verification"]):
            item["fields"]["status"]["name"] = status
        async with self.running() as (app, pilot):
            assert app.snapshot is not None
            self.assertEqual([i.id for i in app.snapshot.issues], ["1", "2", "6"])
            self.assertEqual([r[0] for r in self.rows(app, "sprint")], ["DEMO-1"])
            self.assertEqual([r[0] for r in self.rows(app, "other")], ["DEMO-2", "DEMO-6"])
            searches = [p for _, path, p, _ in self.server.requests if path.endswith("/search")]
            self.assertEqual([p["startAt"] for p in searches], [[str(i)] for i in range(6)])
            self.assertTrue(all("verifying" not in p["jql"][0].casefold() for p in searches))
            paths = [path for _, path, _, _ in self.server.requests]
            for iid in (3, 4, 5):
                self.assertNotIn(f"/rest/api/2/issue/{iid}/comment", paths)
            self.assertNotIn("/rest/api/2/issue/DEMO-999", paths)
            self.assertNotIn("/rest/agile/1.0/sprint/999", paths)
            saved = json.loads(next(self.state_dir.glob("*.json")).read_text())
            self.assertEqual(set(saved["issues"]), {"1", "2", "6"})
            self.assertTrue(all(method == "GET" for method, *_ in self.server.requests))
            await pilot.press("e")
            await pilot.pause()
            self.assertEqual(self.rows(app, "epic"), [])

    async def test_verifying_transitions_preserve_history_and_accept_an_empty_snapshot(self):
        async with self.running() as (app, pilot):
            state_path = next(self.state_dir.glob("*.json"))
            before = state_path.read_bytes()
            self.server.issues.append(issue(3))
            for item in self.server.issues:
                item["fields"]["status"]["name"] = "Verifying"
            self.server.issues[0]["comments"].append(comment(19))
            await self.refresh(app, pilot)
            assert app.snapshot is not None
            self.assertEqual(app.snapshot.issues, ())
            self.assertEqual(self.rows(app, "sprint"), [])
            self.assertEqual(self.rows(app, "other"), [])
            self.assertNotIn("УСТАРЕЛО", self.status(app))
            self.assertEqual(state_path.read_bytes(), before)
        async with self.running() as (app, pilot):
            assert app.snapshot is not None
            self.assertEqual(app.snapshot.issues, ())
            for item in self.server.issues:
                item["fields"]["status"]["name"] = "In Progress"
            await self.refresh(app, pilot)
            self.assertEqual([r[0] for r in self.rows(app, "sprint")], ["DEMO-1 Comment +1"])
            self.assertEqual([r[0] for r in self.rows(app, "other")], ["DEMO-3 NEW", "DEMO-2"])

    async def test_verifying_epic_is_only_context_for_remaining_children(self):
        self.epic_fixture()
        for item in self.server.issues:
            if item["id"] in {"2", "100", "101"}:
                item["fields"]["status"]["name"] = "Verifying"
        async with self.running() as (app, pilot):
            assert app.snapshot is not None
            by_key = {i.key: i for i in app.snapshot.issues}
            self.assertNotIn("DEMO-2", by_key)
            self.assertNotIn("DEMO-101", by_key)
            self.assertFalse(by_key["DEMO-100"].tracked)
            paths = [path for _, path, _, _ in self.server.requests]
            self.assertNotIn("/rest/api/2/issue/100/comment", paths)
            self.assertNotIn("/rest/api/2/issue/2/comment", paths)
            saved = json.loads(next(self.state_dir.glob("*.json")).read_text())
            self.assertEqual(set(saved["issues"]), {"1", "3", "4"})
            await pilot.press("e")
            await pilot.pause()
            self.assertEqual([r[0].lstrip(" │├└─") for r in self.rows(app, "epic")],
                             ["DEMO-100", "DEMO-1", "DEMO-200", "DEMO-300", "DEMO-4"])
            self.assertIn("(1)", self.rows(app, "epic")[0][1])
            self.assertEqual(self.opened, [])

    async def test_default_interval_schedules_refresh_in_one_hour_and_keeps_manual_refresh(self):
        app = Overview(Jira(self.server.url, TOKEN, allow_local_http=True), self.state_dir,
                       browser=self.browser)
        async with app.run_test(size=(160, 32)) as pilot:
            await self.settled(app, pilot)
            assert app.snapshot is not None
            schedule = app.session.view.next_refresh_at
            assert schedule is not None
            scheduled = datetime.strptime(schedule.rsplit(" ", 1)[0], "%H:%M:%S")
            now = datetime.now().astimezone()
            seconds = ((scheduled.hour - now.hour) * 3600 +
                       (scheduled.minute - now.minute) * 60 + scheduled.second -
                       now.second - now.microsecond / 1_000_000) % 86400
            self.assertTrue(3590 < seconds <= 3600, seconds)
            self.assertIn(f"Следующее обновление {schedule}", self.status(app))
            self.server.issues[0]["fields"]["summary"] = "Updated manually"
            await self.refresh(app, pilot)
            self.assertIn("Updated manually", self.visible(app))
            self.assertEqual(app.session.view.next_refresh_at, schedule)
            self.assertEqual(self.opened, [])

    async def test_header_shows_jira_warrior_and_name_without_user_id(self):
        async with self.running() as (app, pilot):
            self.assertEqual(self.status(app),
                             f"Jira Warrior: Synthetic User | Обновлено {app.session.view.updated_at}"
                             f" | Следующее обновление {app.session.view.next_refresh_at}")
            assert app.snapshot is not None
            self.assertEqual(app.snapshot.user_id, "key:me")
            await pilot.press("e")
            self.assertTrue(self.status(app).startswith("Jira Warrior: Synthetic User | "))
            self.server.display_name = "[bold]Тестовый User[/bold]\x1b\u202e"
            await self.refresh(app, pilot)
            prefix = "Jira Warrior: [bold]Тестовый User[/bold]   | "
            self.assertEqual(self.status(app), prefix + f"Обновлено {app.session.view.updated_at}"
                             f" | Следующее обновление {app.session.view.next_refresh_at}")
            self.assertNotIn("key:me", self.status(app))
            updated_at = app.session.view.updated_at
            self.server.status = 500
            await self.refresh(app, pilot)
            self.assertTrue(self.status(app).startswith(prefix + f"УСТАРЕЛО: {updated_at} | "))
            self.assertIn("HTTP 500", self.status(app))
            self.assertNotIn("key:me", self.status(app))
            self.server.status = 200
            await self.refresh(app, pilot)
            await pilot.press("e")
            self.assertEqual(self.status(app), prefix + f"Обновлено {app.session.view.updated_at}"
                             f" | Следующее обновление {app.session.view.next_refresh_at}")
            assert app.snapshot is not None
            self.assertEqual(app.snapshot.user_id, "key:me")
            self.assertEqual(self.opened, [])

    async def test_header_animates_initial_and_manual_refresh_then_restores_schedule(self):
        self.server.request_gate = True
        app = self.make_app()
        async with app.run_test(size=(160, 32)) as pilot:
            self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 2))
            frames = set()
            for _ in range(5):
                await pilot.pause(0.09)
                status = self.status(app)
                self.assertIn("Updating", status)
                self.assertNotIn("Следующее обновление", status)
                self.assertNotIn("Обновлено", status)
                frames.add(status)
            self.assertGreater(len(frames), 1)
            self.server.request_gate = False
            self.server.request_release.set()
            await self.settled(app, pilot)
            schedule = app.session.view.next_refresh_at
            self.assertIn(f"Следующее обновление {schedule}", self.status(app))
            self.assertNotIn("Updating", self.status(app))
            updated = app.session.view.updated_at
            table = app.query_one("#other", IssueTable)
            table.focus()
            selected = table._key_at(table.cursor_row)
            self.server.status = 503
            self.server.request_started.clear()
            self.server.request_release.clear()
            self.server.request_gate = True
            await pilot.press("r")
            self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 2))
            self.assertIn(f"Обновлено {updated}", self.status(app))
            self.assertIn("Updating", self.status(app))
            await pilot.pause(0.2)
            self.assertIs(app.focused, table)
            self.assertEqual(table._key_at(table.cursor_row), selected)
            self.server.request_gate = False
            self.server.request_release.set()
            await self.settled(app, pilot)
            self.assertIn(f"УСТАРЕЛО: {updated}", self.status(app))
            self.assertIn("HTTP 503", self.status(app))
            self.assertIn(f"Следующее обновление {schedule}", self.status(app))
            self.assertNotIn("Updating", self.status(app))
            self.server.status = 200
            await self.refresh(app, pilot)
            self.assertNotIn("УСТАРЕЛО", self.status(app))
            self.assertNotIn("Updating", self.status(app))
            self.assertIn(f"Следующее обновление {schedule}", self.status(app))
            self.assertEqual(self.opened, [])

    async def test_header_shows_schedule_after_initial_failure_and_automatic_updating(self):
        self.server.status = 500
        async with self.running(size=(160, 32), interval=1.5) as (app, pilot):
            self.assertIsNone(app.snapshot)
            self.assertIn("НЕТ УСПЕШНОЙ ЗАГРУЗКИ", self.status(app))
            self.assertIn(f"Следующее обновление {app.session.view.next_refresh_at}", self.status(app))
            self.server.status = 200
            self.server.request_gate = True
            try:
                self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 3))
                await pilot.pause(0.1)
                self.assertIn("Updating", self.status(app))
                self.assertNotIn("Следующее обновление", self.status(app))
            finally:
                self.server.request_gate = False
                self.server.request_release.set()
            await self.settled(app, pilot)
            assert app.snapshot is not None
            self.assertIn("Обновлено", self.status(app))
            self.assertIn(f"Следующее обновление {app.session.view.next_refresh_at}", self.status(app))
            self.assertNotIn("Updating", self.status(app))

    async def test_weekly_sprint_heading_is_short_and_refreshes(self):
        self.server.sprint_names = {1: "DEMO-2026-W43"}
        async with self.running(size=(45, 16)) as (app, pilot):
            heading = app.query_one("#sprint-heading", Static)
            self.assertEqual(str(heading.render()), "Текущий спринт (1) — 43-я неделя")
            assert app.snapshot is not None
            self.assertEqual(app.snapshot.issues[0].sprints, ("DEMO-2026-W43 (#1)",))
            await pilot.pause()
            self.assertEqual(heading.size.height, 1)
            self.server.sprint_names[1] = "DEMO-2026-W44"
            await self.refresh(app, pilot)
            self.assertEqual(str(heading.render()), "Текущий спринт (1) — 44-я неделя")
            self.assertEqual(self.rows(app, "sprint"), [
                ["DEMO-1", "Synthetic task 1", "In Progress", "—"],
            ])
            assert isinstance(app.focused, IssueTable)
            self.assertEqual(app.focused._key_at(app.focused.cursor_row), "1")
            self.assertEqual(self.opened, [])

    async def test_multiple_weekly_sprints_and_custom_names(self):
        self.server.sprint_names = {1: "DEMO-2026-W01", 2: "DEMO-2026-W53",
                                    3: "DEMO-2026-W42", 4: "Release planning"}
        self.server.issues[0]["fields"]["customfield_123"] = [
            {"id": sid} for sid in (1, 2, 3, 4)]
        async with self.running() as (app, pilot):
            heading = str(app.query_one("#sprint-heading", Static).render())
            self.assertEqual(heading, "Текущий спринт (1) — 1-я неделя; 53-я неделя; Release planning (#4)")
            self.assertEqual(len(self.rows(app, "sprint")), 1)
            self.assertEqual(len(self.rows(app, "other")), 1)

    async def test_sprint_week_format_is_not_guessed(self):
        async with self.running() as (app, pilot):
            for name in ("DEMO-2026-W00", "DEMO-2026-W54", "DEMO-2026-W430",
                         "DEMO-2026-W43 extra", "Release 43", "DEMO-W43"):
                with self.subTest(name=name):
                    self.server.sprint_names[1] = name
                    await self.refresh(app, pilot)
                    self.assertEqual(str(app.query_one("#sprint-heading", Static).render()),
                                     f"Текущий спринт (1) — {name} (#1)")

    async def test_http_errors_keep_snapshot_and_recover(self):
        async with self.running() as (app, pilot):
            baseline = self.visible(app)
            for code, message in ((401, "Авторизация"), (403, "прав"), (500, "HTTP 500"), (429, "429")):
                with self.subTest(code=code):
                    self.server.status = code
                    await self.refresh(app, pilot)
                    self.assertIn(message, self.status(app))
                    self.assertIn("УСТАРЕЛО", self.status(app))
                    self.assertEqual(self.visible(app), baseline)
                    self.assertNotIn("SECRET RESPONSE", self.status(app))
                    if code == 429:
                        calls = len(self.server.requests)
                        await self.refresh(app, pilot)
                        self.assertEqual(len(self.server.requests), calls)
                        await asyncio.sleep(1.05)
            self.server.status = 200
            await self.refresh(app, pilot)
            self.assertNotIn("УСТАРЕЛО", self.status(app))

    async def test_auto_refresh_no_overlap_and_exit_during_network(self):
        async with self.running(interval=0.2) as (app, pilot):
            self.server.issues.append(issue(4))
            await pilot.pause(0.6)
            await self.settled(app, pilot)
            self.assertIn("DEMO-4 NEW", self.visible(app))
            # Hold one request explicitly: a timed delay may finish while Pilot
            # sends keys, allowing the same snapshot's next GET to change the count.
            self.server.request_gate = True
            try:
                await pilot.press("r", "r", "r")
                self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 2))
                before = len(self.server.requests)
                await pilot.press("r", "r")
                self.assertEqual(len(self.server.requests), before)
                start = time.monotonic()
                await pilot.press("q")
                self.assertLess(time.monotonic() - start, 0.8)
            finally:
                self.server.request_release.set()

    async def test_redirect_never_sends_authorization_to_other_origin(self):
        other = Server()
        self.server.redirect = other.url + "/rest/api/2/myself"
        try:
            async with self.running() as (app, pilot):
                self.assertIn("Перенаправление", self.status(app))
                self.assertEqual(other.requests, [])
                self.assertFalse(list(self.state_dir.glob("*.json")))
        finally:
            await asyncio.to_thread(other.close)

    async def test_network_failure_is_not_empty_success(self):
        async with self.running() as (app, pilot):
            before = self.visible(app)
            await asyncio.to_thread(self.server.close)
            # TearDown can safely close the already stopped HTTPServer again.
            await self.refresh(app, pilot)
            self.assertIn("Сетевая ошибка", self.status(app))
            self.assertEqual(self.visible(app), before)

    async def test_instance_isolation_and_large_retry_after(self):
        async with self.running() as (app, pilot):
            assert app.snapshot is not None
            other = State(self.state_dir, "https://other.example.org", app.snapshot.user_id)
            try:
                self.assertFalse(other.data["baseline"])
                self.assertNotEqual(other.path, next(self.state_dir.glob("*.json")))
            finally:
                other.close()
            self.server.status = 429
            self.server.retry_after = "172800"
            await self.refresh(app, pilot)
            calls = len(self.server.requests)
            await self.refresh(app, pilot)
            self.assertEqual(len(self.server.requests), calls)


if __name__ == "__main__":
    unittest.main()
