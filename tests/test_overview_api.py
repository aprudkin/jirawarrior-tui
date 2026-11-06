"""Overview api integration checks; synthetic Jira only."""
import json
import unittest
from datetime import UTC, datetime

from support.jira import TOKEN, issue
from support.overview import OverviewCase

from jira_overview.core import Jira


class OverviewApiTests(OverviewCase):
    async def test_jira_updated_is_optional_timezone_aware_and_requested_on_every_page(self):
        instant = datetime(2026, 1, 2, 9, 0, 0, 123000, tzinfo=UTC)
        cases = [
            ("2026-01-02T12:00:00.123+0300", instant),
            ("2026-01-02T04:00:00.123-05:00", instant),
            ("2026-01-02T09:00:00.123Z", instant),
            ("2026-01-02T09:00:00+00:00", instant.replace(microsecond=0)),
            ("1960-01-02T09:00:00.123456Z",
             datetime(1960, 1, 2, 9, 0, 0, 123456, tzinfo=UTC)),
            (None, None), ("", None), ("invalid", None), (123, None), (True, None),
            ({"date": "2026-01-02"}, None), ([], None),
            ("2026-01-02T09:00:00", None), ("2026-01-02", None),
            ("2026-02-30T09:00:00Z", None),
            ("0001-01-01T00:00:00+0100", None),
        ]
        self.server.issues = [issue(number, updated=value)
                              for number, (value, _) in enumerate(cases, 1)]
        self.server.issues.append(issue(99))
        del self.server.issues[-1]["fields"]["updated"]
        self.server.issues[0]["fields"]["customfield_789"] = "DEMO-1000"
        self.server.context_issues = [issue(1000, epic=True, updated=cases[0][0])]
        jira = Jira(self.server.url, TOKEN, allow_local_http=True)
        try:
            snapshot = await jira.snapshot()
        finally:
            await jira.close()
        by_id = {item.id: item for item in snapshot.issues}
        for number, (_, expected) in enumerate(cases, 1):
            with self.subTest(number=number):
                self.assertEqual(by_id[str(number)].updated, expected)
                if expected is not None:
                    updated = by_id[str(number)].updated
                    assert updated is not None
                    self.assertIs(updated.tzinfo, instant.tzinfo)
        self.assertIsNone(by_id["99"].updated)
        self.assertEqual(by_id["1000"].updated, instant)
        related = [params for _, path, params, _ in self.server.requests
                   if path == "/rest/api/2/issue/DEMO-1000"]
        self.assertEqual(len(related), 1)
        self.assertIn("updated", related[0]["fields"][0].split(","))
        searches = [params for _, path, params, _ in self.server.requests
                    if path == "/rest/api/2/search"]
        self.assertEqual(len(searches), len(self.server.issues))
        self.assertTrue(all("updated" in params["fields"][0].split(",") for params in searches))
        self.assertTrue(all(method == "GET" for method, *_ in self.server.requests))

    async def test_snapshot_retains_immediate_parents_even_without_epics_and_caches_context(self):
        self.server.issues = [issue(1, parent="DEMO-10"), issue(2, parent="DEMO-10"),
                              issue(3, parent="DEMO-20"), issue(4, parent="DEMO-30"),
                              issue(5, parent="DEMO-40"), issue(10), issue(30)]
        self.server.issues[-1]["fields"]["status"]["name"] = "Verifying"
        self.server.context_issues = [issue(20), issue(40)]
        self.server.context_issues[-1]["fields"]["status"]["name"] = "Done"
        jira = Jira(self.server.url, TOKEN, allow_local_http=True)
        try:
            snapshot = await jira.snapshot()
        finally:
            await jira.close()
        by_key = {item.key: item for item in snapshot.issues}
        self.assertEqual({key: by_key[key].parent_key for key in ("DEMO-1", "DEMO-3", "DEMO-4", "DEMO-5")},
                         {"DEMO-1": "DEMO-10", "DEMO-3": "DEMO-20",
                          "DEMO-4": "DEMO-30", "DEMO-5": "DEMO-40"})
        self.assertTrue(by_key["DEMO-10"].tracked)
        for key in ("DEMO-20", "DEMO-30", "DEMO-40"):
            self.assertFalse(by_key[key].tracked)
            self.assertFalse(by_key[key].is_epic)
            self.assertFalse(by_key[key].comments)
        self.assertEqual(by_key["DEMO-40"].status, "Done")
        paths = [path for _, path, _, _ in self.server.requests]
        self.assertNotIn("/rest/api/2/issue/DEMO-10", paths)
        self.assertNotIn("/rest/api/2/issue/DEMO-30", paths)
        for number in (20, 40):
            self.assertEqual(paths.count(f"/rest/api/2/issue/DEMO-{number}"), 1)
        for number in (20, 30, 40):
            self.assertNotIn(f"/rest/api/2/issue/{number}/comment", paths)
        self.assertTrue(all(method == "GET" for method, *_ in self.server.requests))

    async def test_epic_snapshot_resolves_context_and_subtasks_without_observing_them(self):
        self.epic_fixture()
        async with self.running() as (app, pilot):
            assert app.snapshot is not None
            by_key = {i.key: i for i in app.snapshot.issues}
            self.assertTrue(by_key["DEMO-100"].is_epic)
            self.assertTrue(by_key["DEMO-101"].tracked)
            self.assertEqual(by_key["DEMO-4"].epic_key, "DEMO-200")
            self.assertEqual(by_key["DEMO-200"].status, "Done")
            self.assertFalse(by_key["DEMO-200"].tracked)
            self.assertFalse(by_key["DEMO-300"].tracked)
            self.assertEqual(by_key["DEMO-4"].parent_key, "DEMO-300")
            self.assertNotIn("DEMO-999", by_key)
            saved = json.loads(next(self.state_dir.glob("*.json")).read_text())
            self.assertEqual(set(saved["issues"]), {"1", "2", "3", "4", "100", "101"})
            paths = [path for _, path, _, _ in self.server.requests]
            self.assertNotIn("/rest/api/2/issue/200/comment", paths)
            self.assertNotIn("/rest/api/2/issue/300/comment", paths)
            self.assertTrue(all(method == "GET" for method, *_ in self.server.requests))

    async def test_epic_fields_are_discovered_by_schema_and_parents_are_cached(self):
        self.epic_fixture()
        self.server.issues.append(issue(5, parent="DEMO-300"))
        renames = {field["id"]: f"customfield_{index + 900}" for index, field in enumerate(self.server.fields)}
        for field in self.server.fields:
            field["id"] = renames[field["id"]]
            field["name"] = "Локализованное поле"
        for item in self.server.issues + self.server.context_issues:
            for old, new in renames.items():
                item["fields"][new] = item["fields"].pop(old)
        async with self.running() as (app, pilot):
            assert app.snapshot is not None
            self.assertEqual(next(i for i in app.snapshot.issues if i.id == "5").epic_key, "DEMO-200")
            paths = [path for _, path, _, _ in self.server.requests]
            self.assertEqual(paths.count("/rest/api/2/issue/DEMO-300"), 1)
            self.assertEqual(paths.count("/rest/api/2/issue/DEMO-200"), 1)
            queries = [p for _, path, p, _ in self.server.requests if path.endswith("/search")]
            self.assertTrue(all(new in queries[0]["fields"][0] for new in renames.values()))

    async def test_epic_metadata_ambiguity_and_parent_cycles_are_safe_errors(self):
        self.epic_fixture()
        self.server.fields.append(self.server.fields[-1])
        async with self.running() as (app, pilot):
            self.assertIsNone(app.snapshot)
            self.assertFalse(list(self.state_dir.glob("*.json")))
            self.server.fields.pop()
            self.server.context_issues[1]["fields"]["customfield_789"] = None
            self.server.context_issues[1]["fields"]["parent"] = {"key": "DEMO-4"}
            await self.refresh(app, pilot)
            self.assertIsNone(app.snapshot)
            self.assertFalse(list(self.state_dir.glob("*.json")))

    async def test_missing_sprint_field_and_comment_author_are_errors(self):
        del self.server.issues[0]["fields"]["customfield_123"]
        async with self.running() as (app, pilot):
            self.assertIn("НЕТ УСПЕШНОЙ", self.status(app))
            self.assertFalse(list(self.state_dir.glob("*.json")))
            self.server.issues[0]["fields"]["customfield_123"] = None
            del self.server.issues[0]["comments"][0]["author"]
            await self.refresh(app, pilot)
            self.assertIn("НЕТ УСПЕШНОЙ", self.status(app))
            self.assertFalse(list(self.state_dir.glob("*.json")))

    async def test_parent_context_failure_or_incomplete_data_preserves_snapshot_and_history(self):
        self.server.issues = [issue(1, parent="DEMO-20"), issue(2, parent="DEMO-20")]
        self.server.context_issues = [issue(20)]
        async with self.running() as (app, pilot):
            snapshot = app.snapshot
            rows = self.rows(app, "other")
            saved = next(self.state_dir.glob("*.json")).read_bytes()
            self.assertEqual(set(json.loads(saved)["issues"]), {"1", "2"})
            for broken in ("request", "summary", "status"):
                if broken == "request":
                    self.server.fail_path = "/rest/api/2/issue/DEMO-20"
                else:
                    del self.server.context_issues[0]["fields"][broken]
                await self.refresh(app, pilot)
                self.assertIs(app.snapshot, snapshot)
                self.assertEqual(self.rows(app, "other"), rows)
                self.assertEqual(next(self.state_dir.glob("*.json")).read_bytes(), saved)
                self.assertIn("УСТАРЕЛО", self.status(app))
                self.server.fail_path = None
                self.server.context_issues = [issue(20)]
            await self.refresh(app, pilot)
            self.assertNotIn("УСТАРЕЛО", self.status(app))

    async def test_epic_context_failure_and_bad_relations_keep_the_last_successful_view(self):
        self.epic_fixture()
        async with self.running() as (app, pilot):
            await pilot.press("e")
            await pilot.pause()
            before = self.rows(app, "epic")
            snapshot = app.snapshot
            saved = next(self.state_dir.glob("*.json")).read_bytes()
            self.server.fail_path = "/rest/api/2/issue/DEMO-200"
            await self.refresh(app, pilot)
            self.assertIs(app.snapshot, snapshot)
            self.assertEqual(self.rows(app, "epic"), before)
            self.assertIn("УСТАРЕЛО", self.status(app))
            self.server.fail_path = None
            for bad in ("../outside", "DEMO-999", 123):
                self.server.issues[0]["fields"]["customfield_789"] = bad
                await self.refresh(app, pilot)
                self.assertIs(app.snapshot, snapshot)
                self.assertEqual(next(self.state_dir.glob("*.json")).read_bytes(), saved)
            self.server.issues[0]["fields"]["customfield_789"] = "DEMO-100"
            await self.refresh(app, pilot)
            self.assertNotIn("УСТАРЕЛО", self.status(app))


if __name__ == "__main__":
    unittest.main()
