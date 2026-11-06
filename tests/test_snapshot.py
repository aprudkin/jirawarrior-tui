"""Snapshot validation and bounded comment reads, using deterministic HTTP gates."""

import asyncio
import time
import unittest
from unittest.mock import patch

import httpx
from support.jira import TOKEN, comment, issue

from jira_overview.core import Jira, OverviewError, RateLimited, _sprint_ids
from jira_overview.session import ReviewSession


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.items = [issue(i, [{"id": 1}]) for i in range(1, 9)]
        self.metadata = {"id": 1, "name": "Sprint 1", "state": "active"}
        self.sprint_reads = 0
        self.jira = Jira("https://jira.example.invalid", TOKEN)
        await self.jira.client.aclose()
        self.jira.client = httpx.AsyncClient(transport=httpx.MockTransport(self.handle))
        self.addAsyncCleanup(self.jira.close)

    async def handle(self, request):
        path = request.url.path
        if path.endswith("/myself"):
            data = {"key": "me", "displayName": "Synthetic User"}
        elif path.endswith("/field"):
            data = [{"id": field, "schema": {"custom": "com.pyxis.greenhopper.jira:" + kind}}
                    for field, kind in (("customfield_123", "gh-sprint"),
                                        ("customfield_456", "gh-epic-label"),
                                        ("customfield_789", "gh-epic-link"))]
        elif path.endswith("/search"):
            data = {"issues": self.items, "startAt": 0, "total": len(self.items)}
        elif "/sprint/" in path:
            self.sprint_reads += 1
            data = self.metadata
        elif path.endswith("/comment"):
            return await self.comment_page(request)
        else:
            self.fail(f"Unexpected HTTP request: {request.method} {path}")
        return httpx.Response(200, json=data)

    async def comment_page(self, request):
        iid = request.url.path.split("/")[-2]
        start = int(request.url.params["startAt"])
        return httpx.Response(200, json={"comments": [comment(int(iid) * 10 + start)],
                                        "startAt": start, "total": 2})

    def test_sprint_ids_reject_incompatible_values_for_both_read_and_write_paths(self):
        self.assertEqual(_sprint_ids(None), [])
        self.assertEqual(_sprint_ids([{"id": 1}, {"id": "2"}, "Sprint[id=3,state=active]"]),
                         ["1", "2", "3"])
        for values in ({"id": 1}, [True], [{"id": True}], [{"id": 1.5}],
                       [{"id": "../1"}], [{"id": "١"}], ["Sprint[state=active]"]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                _sprint_ids(values)

    def test_concurrent_rate_limits_cannot_shorten_an_existing_retry_after(self):
        with self.assertRaises(RateLimited):
            self.jira._rate_limit(httpx.Response(429, headers={"Retry-After": "60"}))
        deadline = self.jira.retry_at
        with self.assertRaises(RateLimited):
            self.jira._rate_limit(httpx.Response(429, headers={"Retry-After": "1"}))
        self.assertGreaterEqual(self.jira.retry_at, deadline)

    async def test_sprint_formats_share_validation_and_cache_only_within_one_snapshot(self):
        self.items[1]["fields"]["customfield_123"] = [
            "com.atlassian.Sprint@a[id=1,state=ACTIVE,name=legacy]", {"id": "1"}]
        for expected_reads in (1, 2):
            snapshot = await self.jira.snapshot()
            self.assertEqual(self.sprint_reads, expected_reads)
            self.assertEqual(len(snapshot.active_sprints), 1)
            self.assertTrue(all(i.sprints == ("Sprint 1 (#1)",) for i in snapshot.issues))
            self.assertTrue(all(len(i.comments) == 2 for i in snapshot.issues))

    async def test_incompatible_metadata_never_publishes_or_ingests_a_new_snapshot(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temporary:
            session = ReviewSession(self.jira, Path(temporary), 3600, lambda _: asyncio.sleep(0, True))
            self.addAsyncCleanup(session.aclose)
            await session.start()
            # The shared HTTP fixture is instant; use the session's completion handle, not a sleep.
            task = session._refresh_task
            assert task is not None
            await task
            accepted = session.view.snapshot
            saved = next(Path(temporary).glob("*.json"))
            before = saved.read_bytes()
            for metadata in ({"id": 999, "name": "Wrong sprint", "state": "active"},
                             {"id": 1, "state": "closed"},
                             {"id": 1, "name": "Sprint", "state": "unknown"},
                             {"id": True, "name": "Sprint", "state": "active"}):
                with self.subTest(metadata=metadata):
                    self.metadata = metadata
                    session.refresh()
                    task = session._refresh_task
                    assert task is not None
                    await task
                    self.assertIs(session.view.snapshot, accepted)
                    self.assertIsNotNone(session.view.refresh_error)
                    self.assertEqual(saved.read_bytes(), before)
                    with self.assertRaises(OverviewError):
                        await self.jira._sprint_state("1")

    async def test_comment_reads_overlap_with_a_fixed_bound_and_sequential_pages(self):
        entered, release = asyncio.Event(), asyncio.Event()
        active = set()
        peak = 0
        starts = {}
        original = self.comment_page

        async def gated(request):
            nonlocal peak
            iid = request.url.path.split("/")[-2]
            start = int(request.url.params["startAt"])
            self.assertNotIn(iid, active)
            self.assertEqual(start, len(starts.setdefault(iid, [])))
            starts[iid].append(start)
            active.add(iid)
            peak = max(peak, len(active))
            if len(active) == 4:
                entered.set()
            try:
                await release.wait()
                return await original(request)
            finally:
                active.remove(iid)

        with patch.object(self, "comment_page", gated):
            task = asyncio.create_task(self.jira.snapshot())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                self.assertEqual(len(starts), 4)
                release.set()
                snapshot = await task
            finally:
                release.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(peak, 4)
        self.assertFalse(active)
        self.assertEqual(starts, {str(i): [0, 1] for i in range(1, 9)})
        self.assertEqual(len(snapshot.issues), 8)

    async def test_one_failed_comment_read_cancels_siblings_and_preserves_rate_limit(self):
        entered = asyncio.Event()
        active = set()
        cancelled = set()

        async def failing(request):
            iid = request.url.path.split("/")[-2]
            active.add(iid)
            if len(active) == 4:
                entered.set()
            try:
                await entered.wait()
                if iid == "1":
                    return httpx.Response(429, headers={"Retry-After": "60"})
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.add(iid)
                raise
            finally:
                active.remove(iid)

        with patch.object(self, "comment_page", failing), self.assertRaises(RateLimited):
            await asyncio.wait_for(self.jira.snapshot(), 2)
        self.assertFalse(active)
        self.assertEqual(cancelled, {"2", "3", "4"})
        self.assertGreater(self.jira.retry_at, time.monotonic())
        with self.assertRaises(RateLimited):
            await self.jira.snapshot()

    async def test_cancelled_snapshot_joins_all_comment_workers(self):
        entered = asyncio.Event()
        active = set()

        async def gated(request):
            iid = request.url.path.split("/")[-2]
            active.add(iid)
            if len(active) == 4:
                entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                active.remove(iid)

        with patch.object(self, "comment_page", gated):
            task = asyncio.create_task(self.jira.snapshot())
            try:
                await asyncio.wait_for(entered.wait(), 2)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertFalse(active)


if __name__ == "__main__":
    unittest.main()
