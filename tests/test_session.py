import asyncio
from pathlib import Path
import tempfile
import unittest

from jira_overview.core import Jira
from jira_overview.session import ReviewSession
from test_overview import Server, TOKEN


class ReviewSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = Server()
        self.temp = tempfile.TemporaryDirectory()
        self.opened = []
        self.browser_gate = None
        self.browser_entered = asyncio.Event()

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.close)
        self.temp.cleanup()

    async def browser(self, url):
        self.opened.append(url)
        self.browser_entered.set()
        if self.browser_gate is not None:
            await self.browser_gate.wait()
        return True

    def make_session(self, changed=None, interval=3600):
        return ReviewSession(Jira(self.server.url, TOKEN, allow_local_http=True),
                             Path(self.temp.name), interval, self.browser, changed)

    async def test_failed_initial_load_is_not_an_empty_success_and_recovers(self):
        self.server.status = 500
        session = self.make_session()
        await session.start()
        await self.wait_until(lambda: not session.view.refreshing)
        self.assertIsNone(session.view.snapshot)
        self.assertEqual(session.view.items, ())
        self.assertIn("HTTP 500", session.view.refresh_error)
        self.assertFalse(list(Path(self.temp.name).glob("*.json")))
        self.server.status = 200
        session.refresh()
        await self.wait_until(lambda: session.view.snapshot is not None)
        self.assertFalse(any(item.new for item in session.view.items))
        await session.aclose()

    async def test_sprint_membership_stays_a_single_issue_in_session_view(self):
        self.server.issues[0]["fields"]["customfield_123"] = [
            {"id": 1}, "com.atlassian.Sprint@a[id=2,state=ACTIVE,name=legacy]", {"id": 3}]
        session = self.make_session()
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        matching = [item for item in session.view.items if item.issue.id == "1"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].issue.sprints, ("Sprint 1 (#1)", "Sprint 2 (#2)"))
        await session.aclose()

    async def test_baseline_new_comments_restart_and_disappearance_use_persisted_markers(self):
        session = self.make_session()
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        self.server.issues.append({"id": "4", "key": "DEMO-4", "fields": {
            "summary": "Synthetic task 4", "status": {"name": "In Progress"}, "customfield_123": None},
            "comments": [{"id": "40", "author": {"key": "other"}, "created": "2026-01-01T12:00:00Z", "body": "old"}]})
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        item = next(item for item in session.view.items if item.issue.id == "4")
        self.assertTrue(item.new)
        self.assertEqual(item.unread_comments, 0)
        self.server.issues[-1]["comments"].extend([
            {"id": "41", "author": {"key": "me"}, "created": "2026-01-01T12:00:00Z", "body": "self"},
            {"id": "42", "author": {"key": "other"}, "created": "2026-01-01T12:00:00Z", "body": "foreign"}])
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        item = next(item for item in session.view.items if item.issue.id == "4")
        self.assertTrue(item.new)
        self.assertEqual(item.unread_comments, 1)
        self.server.issues[-1]["comments"][0]["body"] = "edited known comment"
        self.server.issues[-1]["fields"]["status"]["name"] = "Review"
        self.server.issues[-1]["comments"].pop(0)
        self.server.issues[-1]["comments"].append({
            "id": "43", "author": {"key": "other"}, "created": "2026-01-01T12:00:00Z", "body": "replacement"})
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        item = next(item for item in session.view.items if item.issue.id == "4")
        self.assertEqual(item.unread_comments, 2)
        session.open(item.issue)
        await self.wait_until(lambda: not session.view.opening)
        item = next(item for item in session.view.items if item.issue.id == "4")
        self.assertFalse(item.new)
        self.assertEqual(item.unread_comments, 0)
        self.server.issues[-1]["fields"]["customfield_123"] = [{"id": 1}]
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        self.assertEqual(sum(item.issue.id == "4" for item in session.view.items), 1)
        self.server.issues.pop()
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        await session.aclose()
        session = self.make_session()
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        self.server.issues.append({"id": "4", "key": "DEMO-4", "fields": {
            "summary": "Synthetic task 4", "status": {"name": "In Progress"}, "customfield_123": None},
            "comments": [{"id": "40", "author": {"key": "other"}, "created": "2026-01-01T12:00:00Z", "body": "old"},
                         {"id": "42", "author": {"key": "other"}, "created": "2026-01-01T12:00:00Z", "body": "foreign"}]})
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        item = next(item for item in session.view.items if item.issue.id == "4")
        self.assertFalse(item.new)
        self.assertEqual(item.unread_comments, 0)
        await session.aclose()

    async def test_check_success_and_failure_never_create_or_change_state(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from jira_overview.__main__ import check
        from jira_overview.core import OverviewError
        before = b"{\"version\":1,\"baseline\":true,\"issues\":{}}"
        existing = Path(self.temp.name) / "existing.json"
        existing.write_bytes(before)
        output = StringIO()
        with redirect_stdout(output):
            await check(Jira(self.server.url, TOKEN, allow_local_http=True))
        self.assertIn("GET-проверка успешна", output.getvalue())
        self.assertEqual(existing.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in Path(self.temp.name).iterdir()), ["existing.json"])
        self.server.status = 500
        with self.assertRaises(OverviewError):
            await check(Jira(self.server.url, TOKEN, allow_local_http=True))
        self.assertEqual(existing.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in Path(self.temp.name).iterdir()), ["existing.json"])

    async def test_start_publishes_immutable_baseline_view(self):
        changed = asyncio.Event()
        session = self.make_session(changed.set)
        await session.start()
        await asyncio.wait_for(changed.wait(), 2)
        while session.view.snapshot is None:
            changed.clear()
            await asyncio.wait_for(changed.wait(), 2)
        view = session.view
        self.assertEqual([item.issue.key for item in view.items], ["DEMO-1", "DEMO-2"])
        self.assertFalse(any(item.new or item.unread_comments for item in view.items))
        self.assertIsNone(view.refresh_error)
        with self.assertRaises((AttributeError, TypeError)):
            view.items[0].new = True
        await session.aclose()
        self.assertTrue(session.view.closed)

    async def test_refresh_gate_keeps_last_success_and_open_confirms_only_shown(self):
        session = self.make_session()
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        baseline = session.view
        self.server.issues[0]["comments"].append({
            "id": "99", "author": {"key": "other"}, "created": "2026-01-01T12:00:00Z", "body": "synthetic"})
        self.server.delay = 0.1
        session.refresh()
        session.refresh()
        session.refresh()
        await asyncio.sleep(0.05)
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        self.assertEqual(session.view.snapshot.issues[0].comments, frozenset({"10", "99"}))
        self.assertEqual(len([r for r in self.server.requests if r[1].endswith("/myself")]), 2)
        shown = baseline.items[0].issue
        self.browser_gate = asyncio.Event()
        self.browser_entered.clear()
        session.open(shown)
        session.open(session.view.items[1].issue)
        await asyncio.wait_for(self.browser_entered.wait(), 2)
        self.server.issues[0]["comments"].append({
            "id": "100", "author": {"key": "other"}, "created": "2026-01-01T12:00:00Z", "body": "later"})
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        self.assertEqual(session.view.items[0].unread_comments, 2)
        self.browser_gate.set()
        await self.wait_until(lambda: not session.view.opening)
        self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-1"])
        self.assertEqual(session.view.items[0].unread_comments, 2)
        await session.aclose()

    async def wait_until(self, predicate):
        for _ in range(300):
            if predicate():
                return
            await asyncio.sleep(0.01)
        self.fail("session outcome did not arrive")

    async def test_changed_pagination_and_first_write_failure_never_publish_baseline(self):
        for invalid in ("partial", "duplicate", "total_delta", "bad_start"):
            with self.subTest(invalid=invalid):
                setattr(self.server, invalid, 1 if invalid == "total_delta" else True)
                session = self.make_session()
                await session.start()
                await self.wait_until(lambda: not session.view.refreshing)
                self.assertIsNone(session.view.snapshot)
                self.assertIsNotNone(session.view.refresh_error)
                self.assertFalse(list(Path(self.temp.name).glob("*.json")))
                await session.aclose()
                setattr(self.server, invalid, 0 if invalid == "total_delta" else False)
                self.temp.cleanup()
                self.temp = tempfile.TemporaryDirectory()

        session = self.make_session()
        from unittest.mock import patch
        with patch("jira_overview.core.os.replace", side_effect=OSError("synthetic disk failure")):
            await session.start()
            await self.wait_until(lambda: not session.view.refreshing)
            self.assertIsNone(session.view.snapshot)
            self.assertIn("НЕ сохранены", session.view.refresh_error)
            self.server.user = "changed-account"
            session.refresh()
            await self.wait_until(lambda: not session.view.refreshing)
            self.assertIn("Учётная запись изменилась", session.view.refresh_error)
            self.assertFalse(list(Path(self.temp.name).glob("*.json")))
        await session.aclose()

    async def test_ingest_write_failure_after_baseline_preserves_view_and_disk(self):
        session = self.make_session()
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        previous_view = session.view
        state_path = next(Path(self.temp.name).glob("*.json"))
        previous_state = state_path.read_bytes()
        self.server.issues[0]["comments"].append({
            "id": "99", "author": {"key": "other"}, "created": "2026-01-01T12:00:00Z", "body": "synthetic"})
        from unittest.mock import patch
        with patch("jira_overview.core.os.replace", side_effect=OSError("synthetic disk failure")):
            session.refresh()
            await self.wait_until(lambda: not session.view.refreshing)
        self.assertIs(session.view.snapshot, previous_view.snapshot)
        self.assertEqual(session.view.updated_at, previous_view.updated_at)
        self.assertEqual(session.view.items, previous_view.items)
        self.assertEqual(state_path.read_bytes(), previous_state)
        self.assertIn("НЕ сохранены", session.view.refresh_error)
        await session.aclose()

    async def test_acknowledge_write_failure_preserves_disk_and_markers(self):
        session = self.make_session()
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        self.server.issues[0]["comments"].append({
            "id": "99", "author": {"key": "other"}, "created": "2026-01-01T12:00:00Z", "body": "synthetic"})
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        path = next(Path(self.temp.name).glob("*.json"))
        previous = path.read_bytes()
        from unittest.mock import patch
        with patch("jira_overview.core.os.replace", side_effect=OSError("synthetic disk failure")):
            session.open(session.view.items[0].issue)
            await self.wait_until(lambda: not session.view.opening)
        self.assertEqual(path.read_bytes(), previous)
        self.assertEqual(session.view.items[0].unread_comments, 1)
        self.assertIn("НЕ сохранены", session.view.open_notice)
        await session.aclose()

    async def test_timer_ticks_do_not_queue_behind_gated_refresh(self):
        session = self.make_session(interval=0.01)
        self.server.request_started.clear()
        self.server.request_release.clear()
        self.server.request_gate = True
        await session.start()
        self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 2))
        await asyncio.sleep(0.06)
        myself = [request for request in self.server.requests if request[1].endswith("/myself")]
        self.assertEqual(len(myself), 1)
        self.server.request_release.set()
        self.server.request_gate = False
        await self.wait_until(lambda: session.view.snapshot is not None)
        await session.aclose()

    async def test_retry_after_and_reentrant_invalidation_do_not_queue_refresh(self):
        session = None
        reentered = False
        def changed():
            nonlocal reentered
            if session is not None and session.view.refreshing and not reentered:
                reentered = True
                session.refresh()
        session = self.make_session(changed)
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        self.server.status = 429
        self.server.retry_after = "30"
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        requests = len(self.server.requests)
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        self.assertEqual(len(self.server.requests), requests)
        self.assertIn("429", session.view.refresh_error)
        await session.aclose()

    async def test_close_cancels_browser_wait_before_releasing_profile(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def waiting_browser(url):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        session = ReviewSession(Jira(self.server.url, TOKEN, allow_local_http=True),
                                Path(self.temp.name), 3600, waiting_browser)
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        session.open(session.view.items[0].issue)
        await asyncio.wait_for(entered.wait(), 2)
        self.server.request_started.clear()
        self.server.request_release.clear()
        self.server.request_gate = True
        session.refresh()
        self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 2))
        await session.aclose()
        self.server.request_release.set()
        self.assertTrue(cancelled.is_set())
        replacement = Jira(self.server.url, TOKEN, allow_local_http=True)
        from jira_overview.core import State
        state = State(Path(self.temp.name), self.server.url, session.view.user_id)
        state.close()
        await replacement.close()

    async def test_close_cancels_gated_refresh_without_late_state_write(self):
        notifications = []
        session = None
        session = self.make_session(lambda: notifications.append(session.view))
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        state_file = next(Path(self.temp.name).glob("*.json"))
        saved = state_file.read_bytes()
        notifications.clear()
        self.server.request_started.clear()
        self.server.request_release.clear()
        self.server.request_gate = True
        session.refresh()
        self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 2))
        await session.aclose()
        self.server.request_release.set()
        self.assertEqual(state_file.read_bytes(), saved)
        count = len(notifications)
        await asyncio.sleep(0.02)
        self.assertEqual(len(notifications), count)

    async def test_cancelled_close_waiter_and_concurrent_close_keep_profile_until_cleanup(self):
        entered, cleanup_gate, cleanup_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def delayed_cleanup_browser(url):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await cleanup_gate.wait()
                cleanup_finished.set()
        session = ReviewSession(Jira(self.server.url, TOKEN, allow_local_http=True),
                                Path(self.temp.name), 3600, delayed_cleanup_browser)
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        session.open(session.view.items[0].issue)
        await asyncio.wait_for(entered.wait(), 2)
        first = asyncio.create_task(session.aclose())
        second = asyncio.create_task(session.aclose())
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.sleep(0)
        from jira_overview.core import State
        with self.assertRaises(Exception):
            State(Path(self.temp.name), self.server.url, session.view.user_id)
        cleanup_gate.set()
        await second
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertTrue(cleanup_finished.is_set())
        replacement = State(Path(self.temp.name), self.server.url, session.view.user_id)
        replacement.close()

    async def test_account_change_profile_lock_and_corrupt_state_are_rejected(self):
        first = self.make_session()
        await first.start()
        await self.wait_until(lambda: first.view.snapshot is not None)
        first_state_file = next(Path(self.temp.name).glob("*.json"))
        other_instance = Server()
        independent = ReviewSession(Jira(other_instance.url, TOKEN, allow_local_http=True),
                                   Path(self.temp.name), 3600, self.browser)
        try:
            await independent.start()
            await self.wait_until(lambda: independent.view.snapshot is not None)
            self.assertEqual(len(list(Path(self.temp.name).glob("*.json"))), 2)
        finally:
            await independent.aclose()
            await asyncio.to_thread(other_instance.close)
        occupied = self.make_session()
        await occupied.start()
        await self.wait_until(lambda: occupied.view.refresh_error is not None)
        self.assertIn("Другой экземпляр", occupied.view.refresh_error)
        await occupied.aclose()
        self.server.user = "different"
        first.refresh()
        await self.wait_until(lambda: not first.view.refreshing)
        self.assertIn("Учётная запись изменилась", first.view.refresh_error)
        state_path = first_state_file
        state_path.write_text("synthetic corruption")
        await first.aclose()
        self.server.user = "me"
        corrupted = self.make_session()
        await corrupted.start()
        await self.wait_until(lambda: corrupted.view.refresh_error is not None)
        self.assertIn("повреждено", corrupted.view.refresh_error)
        self.assertEqual(state_path.read_text(), "synthetic corruption")
        await corrupted.aclose()

    async def test_close_during_initial_load_cancels_without_creating_state(self):
        session = self.make_session()
        self.server.request_started.clear()
        self.server.request_release.clear()
        self.server.request_gate = True
        await session.start()
        self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 2))
        await session.aclose()
        self.server.request_release.set()
        self.assertIsNone(session.view.snapshot)
        self.assertTrue(session.view.closed)
        self.assertFalse(list(Path(self.temp.name).glob("*.json")))

    async def test_close_releases_state_and_jira_exactly_once(self):
        from unittest.mock import AsyncMock, patch
        from jira_overview.core import State
        jira = Jira(self.server.url, TOKEN, allow_local_http=True)
        original_close = jira.close
        jira.close = AsyncMock(wraps=original_close)
        session = ReviewSession(jira, Path(self.temp.name), 3600, self.browser)
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        state_close = State.close
        with patch("jira_overview.session.State.close", autospec=True, wraps=state_close) as close_state:
            await session.aclose()
            await session.aclose()
        jira.close.assert_awaited_once()
        close_state.assert_called_once()
        replacement = State(Path(self.temp.name), self.server.url, session.view.user_id)
        replacement.close()

    async def test_close_before_start_is_idempotent_and_rejects_later_start(self):
        session = self.make_session()
        await session.aclose()
        await session.aclose()
        self.assertTrue(session.view.closed)
        with self.assertRaises(RuntimeError):
            await session.start()

    async def test_browser_timeout_is_a_safe_failure_and_preserves_new_marker(self):
        async def browser_timeout(url):
            try:
                await asyncio.wait_for(asyncio.Event().wait(), timeout=0.01)
            except TimeoutError:
                return False
        session = ReviewSession(Jira(self.server.url, TOKEN, allow_local_http=True),
                                Path(self.temp.name), 3600, browser_timeout)
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        self.server.issues.append({"id": "5", "key": "DEMO-5", "fields": {
            "summary": "Synthetic task 5", "status": {"name": "In Progress"}, "customfield_123": None},
            "comments": []})
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        shown = next(item.issue for item in session.view.items if item.issue.id == "5")
        session.open(shown)
        await self.wait_until(lambda: not session.view.opening)
        self.assertTrue(next(item for item in session.view.items if item.issue.id == "5").new)
        self.assertIn("Браузер не принял", session.view.open_notice)
        await session.aclose()

    async def test_browser_refusal_preserves_marker_and_close_sends_no_late_invalidation(self):
        notifications = []
        async def refuse(url):
            return False
        session = ReviewSession(Jira(self.server.url, TOKEN, allow_local_http=True),
                                Path(self.temp.name), 3600, refuse, lambda: notifications.append(session.view))
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        self.server.issues.append({"id":"4", "key":"DEMO-4", "fields":{"summary":"Synthetic task 4","status":{"name":"In Progress"},"customfield_123":None},"comments":[]})
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        issue4 = next(item.issue for item in session.view.items if item.issue.id == "4")
        session.open(issue4)
        await self.wait_until(lambda: not session.view.opening)
        self.assertTrue(session.view.items[-1].new)
        self.assertIn("не принял", session.view.open_notice)
        await session.aclose()
        after_close = len(notifications)
        self.assertTrue(session.view.closed)
        self.assertEqual(len(notifications), after_close)

    async def test_browser_completion_before_refresh_keeps_new_comment_unread(self):
        session = self.make_session()
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        shown = session.view.items[0].issue
        self.server.issues[0]["comments"].append({
            "id": "99", "author": {"key": "other"}, "created": "2026-01-01T12:00:00Z", "body": "later"})
        self.server.request_started.clear()
        self.server.request_release.clear()
        self.server.request_gate = True
        session.refresh()
        self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 2))
        session.open(shown)
        await self.wait_until(lambda: not session.view.opening)
        self.assertEqual(session.view.items[0].unread_comments, 0)
        self.server.request_gate = False
        self.server.request_release.set()
        await self.wait_until(lambda: not session.view.refreshing)
        self.assertEqual(session.view.items[0].unread_comments, 1)
        await session.aclose()

    async def test_refresh_failure_is_separate_from_open_and_close_is_idempotent(self):
        session = self.make_session()
        await session.start()
        await self.wait_until(lambda: session.view.snapshot is not None)
        old = session.view
        state_path = next(Path(self.temp.name).glob("*.json"))
        previous_state = state_path.read_bytes()
        self.server.status = 503
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        self.assertIs(session.view.snapshot, old.snapshot)
        self.assertEqual(session.view.updated_at, old.updated_at)
        self.assertEqual(state_path.read_bytes(), previous_state)
        self.assertIn("HTTP 503", session.view.refresh_error)
        session.open(old.items[0].issue)
        await self.wait_until(lambda: not session.view.opening)
        self.assertIsNotNone(session.view.refresh_error)
        self.assertEqual(session.view.open_notice.split(".")[0], "Ссылка передана браузеру")
        await session.aclose()
        await session.aclose()
        self.assertTrue(session.view.closed)


class StartupCleanupTests(unittest.TestCase):
    def test_failed_application_run_still_closes_unstarted_session(self):
        from jira_overview.__main__ import run_overview
        class FailedApp:
            def run(self):
                raise RuntimeError("synthetic compose/mount failure")
        failed = FailedApp()
        failed.session = ReviewSession(Jira("https://jira.example.invalid", TOKEN), Path("/tmp/unused"),
                                       60, lambda url: asyncio.sleep(0, result=True))
        with self.assertRaisesRegex(RuntimeError, "synthetic compose/mount failure"):
            run_overview(failed)
        self.assertTrue(failed.session.view.closed)

        class PartiallyStartedApp:
            def run(self):
                asyncio.run(self.session.start())
                raise RuntimeError("synthetic failure after mount start")
        partial = PartiallyStartedApp()
        partial.session = ReviewSession(Jira("https://jira.example.invalid", TOKEN), Path("/tmp/unused"),
                                        60, lambda url: asyncio.sleep(0, result=True))
        with self.assertRaisesRegex(RuntimeError, "synthetic failure after mount start"):
            run_overview(partial)
        self.assertTrue(partial.session.view.closed)

        class NormallyClosedApp:
            def run(self):
                asyncio.run(self.session.aclose())
        normal = NormallyClosedApp()
        normal.session = ReviewSession(Jira("https://jira.example.invalid", TOKEN), Path("/tmp/unused"),
                                       60, lambda url: asyncio.sleep(0, result=True))
        run_overview(normal)
        self.assertTrue(normal.session.view.closed)
