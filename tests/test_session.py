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

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.close)
        self.temp.cleanup()

    async def browser(self, url):
        self.opened.append(url)
        return True

    def make_session(self, changed=None, interval=3600):
        return ReviewSession(Jira(self.server.url, TOKEN, allow_local_http=True),
                             Path(self.temp.name), interval, self.browser, changed)

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
        for _ in range(200):
            if session.view.snapshot is not None:
                break
            await asyncio.sleep(0.01)
        baseline = session.view
        self.server.issues[0]["comments"].append({
            "id": "99", "author": {"key": "other"}, "created": "2026-01-01T12:00:00Z", "body": "synthetic"})
        self.server.delay = 0.1
        session.refresh()
        session.refresh()
        session.refresh()
        await asyncio.sleep(0.05)
        session.refresh()
        for _ in range(200):
            if not session.view.refreshing:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(session.view.snapshot.issues[0].comments, frozenset({"10", "99"}))
        self.assertEqual(len([r for r in self.server.requests if r[1].endswith("/myself")]), 2)
        shown = baseline.items[0].issue
        session.open(shown)
        for _ in range(200):
            if not session.view.opening:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-1"])
        self.assertEqual(session.view.items[0].unread_comments, 1)
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
        for _ in range(200):
            if session.view.snapshot is not None:
                break
            await asyncio.sleep(0.01)
        session.open(session.view.items[0].issue)
        await asyncio.wait_for(entered.wait(), 2)
        await session.aclose()
        self.assertTrue(cancelled.is_set())
        replacement = Jira(self.server.url, TOKEN, allow_local_http=True)
        from jira_overview.core import State
        state = State(Path(self.temp.name), self.server.url, session.view.user_id)
        state.close()
        await replacement.close()

    async def test_refresh_failure_is_separate_from_open_and_close_is_idempotent(self):
        session = self.make_session()
        await session.start()
        for _ in range(200):
            if session.view.snapshot is not None:
                break
            await asyncio.sleep(0.01)
        old = session.view
        self.server.status = 503
        session.refresh()
        for _ in range(200):
            if not session.view.refreshing:
                break
            await asyncio.sleep(0.01)
        self.assertIs(session.view.snapshot, old.snapshot)
        self.assertEqual(session.view.updated_at, old.updated_at)
        self.assertIn("HTTP 503", session.view.refresh_error)
        session.open(old.items[0].issue)
        for _ in range(200):
            if not session.view.opening:
                break
            await asyncio.sleep(0.01)
        self.assertIsNotNone(session.view.refresh_error)
        self.assertEqual(session.view.open_notice.split(".")[0], "Ссылка передана браузеру")
        await session.aclose()
        await session.aclose()
        self.assertTrue(session.view.closed)
