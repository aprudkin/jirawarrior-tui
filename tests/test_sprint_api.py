"""Synthetic Jira HTTP boundary for the one permitted sprint write."""
import copy
import json
import unittest
from dataclasses import replace
from email.utils import formatdate
import time

import httpx

from jira_overview.core import Issue, Jira, OverviewError, RateLimited, Sprint


class SprintFixture:
    def __init__(self):
        self.fields = [
            {"id": "customfield_123", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
            {"id": "customfield_456", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-epic-label"}},
            {"id": "customfield_789", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-epic-link"}},
        ]
        self.issue = {"id": "10001", "key": "ABC-1", "fields": {
            "issuetype": {"name": "Задача", "subtask": False}, "parent": None,
            "customfield_456": None, "customfield_123": None,
        }}
        self.other_issues = {}
        self.sprints = {7: {"id": 7, "name": "Current", "state": "active"},
                        8: {"id": 8, "name": "Other", "state": "future"},
                        9: {"id": 9, "name": "Old", "state": "closed"}}
        self.calls = []
        self.post_status = 204
        self.apply = True
        self.drop = False
        self.fail_verify = False
        self.retry_after = "60"
        self.location = "https://unrelated.example/secret"

    def handle(self, request):
        self.calls.append((request.method, request.url.path, request.content))
        path = request.url.path.removeprefix("/jira")
        if path == "/rest/api/2/field":
            return httpx.Response(200, json=self.fields)
        issues = {self.issue["id"]: self.issue, **self.other_issues}
        if path.startswith("/rest/api/2/issue/"):
            iid = path.rsplit("/", 1)[1]
            if self.fail_verify and self.posts and iid == "10001":
                return httpx.Response(503, text="secret body")
            return httpx.Response(200, json=copy.deepcopy(issues[iid]))
        if request.method == "POST":
            if self.apply:
                iid = json.loads(request.content)["issues"][0]
                issues[iid]["fields"]["customfield_123"] = [{"id": 7}]
            if self.drop:
                raise httpx.ReadError("secret URL/token/body")
            return httpx.Response(self.post_status, text="secret body", headers={
                "Retry-After": self.retry_after, "Location": self.location})
        if path.startswith("/rest/agile/1.0/sprint/"):
            return httpx.Response(200, json=self.sprints[int(path.rsplit("/", 1)[1])])
        return httpx.Response(404, text="secret body")

    @property
    def posts(self):
        return [call for call in self.calls if call[0] == "POST"]


class SprintApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = SprintFixture()
        self.jira = Jira("https://jira.example/jira", "secret")
        await self.jira.client.aclose()
        self.jira.client = httpx.AsyncClient(transport=httpx.MockTransport(self.fixture.handle),
                                           follow_redirects=False)
        self.addAsyncCleanup(self.jira.close)
        self.shown = Issue("10001", "ABC-1", "Task", "Open", (), frozenset(), frozenset())
        self.target = Sprint("7", "Current")

    async def test_adds_one_issue_using_server_schema_and_verifies_readback(self):
        self.assertTrue(await self.jira.add_to_sprint(self.shown, self.target))
        self.assertEqual(self.fixture.posts, [
            ("POST", "/jira/rest/agile/1.0/sprint/7/issue", b'{"issues":["10001"]}')])
        self.assertFalse(await self.jira.add_to_sprint(self.shown, self.target))
        self.assertEqual(len(self.fixture.posts), 1)

    async def test_refuses_other_unfinished_sprints_including_legacy_values(self):
        for state in ("active", "future"):
            for value in ({"id": 8}, "Sprint@abc[id=8,state=FUTURE,name=Other]"):
                with self.subTest(state=state, value=value):
                    self.fixture.sprints[8]["state"] = state
                    self.fixture.issue["fields"]["customfield_123"] = [value]
                    with self.assertRaisesRegex(OverviewError, "другом"):
                        await self.jira.add_to_sprint(self.shown, self.target)
        self.assertEqual(self.fixture.posts, [])
        self.fixture.issue["fields"]["customfield_123"] = [{"id": 9}]
        self.assertTrue(await self.jira.add_to_sprint(self.shown, self.target))

    async def test_epics_subtasks_missing_and_changed_identity_fail_without_post(self):
        original = copy.deepcopy(self.fixture.issue)
        for changes in ({"customfield_456": "Локализованный эпик"},
                        {"issuetype": {"name": "Подзадача", "subtask": True}},
                        {"issuetype": {"name": "Unknown"}},
                        {"parent": {"key": "ABC-2"}}):
            with self.subTest(changes=changes):
                self.fixture.issue = copy.deepcopy(original)
                self.fixture.issue["fields"].update(changes)
                with self.assertRaises(OverviewError):
                    await self.jira.add_to_sprint(self.shown, self.target)
        self.fixture.issue = copy.deepcopy(original)
        del self.fixture.issue["fields"]["customfield_123"]
        with self.assertRaises(OverviewError):
            await self.jira.add_to_sprint(self.shown, self.target)
        self.fixture.issue = copy.deepcopy(original)
        self.fixture.issue["id"] = "10002"
        with self.assertRaises(OverviewError):
            await self.jira.add_to_sprint(self.shown, self.target)
        self.assertEqual(self.fixture.posts, [])
        for shown in (replace(self.shown, is_epic=True), replace(self.shown, is_subtask=True),
                      replace(self.shown, tracked=False), replace(self.shown, id="../1")):
            calls = len(self.fixture.calls)
            with self.assertRaises(OverviewError):
                await self.jira.add_to_sprint(shown, self.target)
            self.assertEqual(len(self.fixture.calls), calls)

    async def test_unknown_transport_outcome_reconciles_and_never_reposts_automatically(self):
        self.fixture.drop = True
        self.assertTrue(await self.jira.add_to_sprint(self.shown, self.target))
        self.assertFalse(await self.jira.add_to_sprint(self.shown, self.target))
        self.assertEqual(len(self.fixture.posts), 1)
        self.fixture.issue["fields"]["customfield_123"] = None
        self.fixture.apply = False
        with self.assertRaisesRegex(OverviewError, "не подтвердила"):
            await self.jira.add_to_sprint(self.shown, self.target)
        self.assertEqual(len(self.fixture.posts), 2)

    async def test_failed_verification_is_unknown_and_next_action_reads_before_post(self):
        self.fixture.fail_verify = True
        with self.assertRaisesRegex(OverviewError, "неизвестен"):
            await self.jira.add_to_sprint(self.shown, self.target)
        self.fixture.fail_verify = False
        self.assertFalse(await self.jira.add_to_sprint(self.shown, self.target))
        self.assertEqual(len(self.fixture.posts), 1)

    async def test_denial_redirect_and_server_failure_are_safe_and_not_blindly_retried(self):
        self.fixture.apply = False
        for code in (400, 401, 403, 302, 503):
            with self.subTest(code=code):
                self.fixture.post_status = code
                before = len(self.fixture.posts)
                with self.assertRaises(OverviewError) as raised:
                    await self.jira.add_to_sprint(self.shown, self.target)
                self.assertEqual(len(self.fixture.posts), before + 1)
                for secret in ("secret", "http", "unrelated"):
                    self.assertNotIn(secret, str(raised.exception))
                self.assertFalse(any("unrelated" in path for _, path, _ in self.fixture.calls))
        self.fixture.apply = True
        self.assertTrue(await self.jira.add_to_sprint(self.shown, self.target))

    async def test_closed_changed_or_invalid_target_has_no_write(self):
        for target in (Sprint("7", "Renamed"), Sprint("8", "Other"), Sprint("../7", "Current")):
            with self.subTest(target=target), self.assertRaises(OverviewError):
                await self.jira.add_to_sprint(self.shown, target)
        self.fixture.sprints[7]["state"] = "closed"
        with self.assertRaises(OverviewError):
            await self.jira.add_to_sprint(self.shown, self.target)
        self.assertEqual(self.fixture.posts, [])

    async def test_post_retry_after_http_date_throttles_subsequent_reads(self):
        self.fixture.apply = False
        self.fixture.post_status = 429
        self.fixture.retry_after = formatdate(time.time() + 120, usegmt=True)
        with self.assertRaises(RateLimited) as raised:
            await self.jira.add_to_sprint(self.shown, self.target)
        self.assertGreater(raised.exception.seconds, 115)
        calls = len(self.fixture.calls)
        with self.assertRaises(RateLimited):
            await self.jira.add_to_sprint(self.shown, self.target)
        self.assertEqual(len(self.fixture.calls), calls)

    async def test_unverified_a_is_reconciled_before_any_write_to_b(self):
        other = copy.deepcopy(self.fixture.issue)
        other.update(id="10002", key="ABC-2")
        self.fixture.other_issues["10002"] = other
        second = replace(self.shown, id="10002", key="ABC-2")
        self.fixture.fail_verify = True
        with self.assertRaisesRegex(OverviewError, "неизвестен"):
            await self.jira.add_to_sprint(self.shown, self.target)
        with self.assertRaisesRegex(OverviewError, "предыдущего"):
            await self.jira.add_to_sprint(second, self.target)
        self.assertEqual(len(self.fixture.posts), 1)
        self.fixture.fail_verify = False
        self.assertTrue(await self.jira.add_to_sprint(second, self.target))
        self.assertEqual(len(self.fixture.posts), 2)
        self.assertFalse(await self.jira.add_to_sprint(self.shown, self.target))
        self.assertEqual(len(self.fixture.posts), 2)


if __name__ == "__main__":
    unittest.main()
