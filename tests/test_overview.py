"""Integration boundary: real HTTP + Textual Pilot + real temporary state.

No corporate fixtures. The only external action replaced is browser handoff.
"""
import asyncio
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from textual.widgets import Static

from jira_overview.app import IssueTable, Overview
from jira_overview.core import Jira, OverviewError, State


TOKEN = "synthetic-token-never-persist"
BODY = "private-comment-body-never-persist"


def comment(cid, author="other"):
    return {"id": str(cid), "author": {"key": author}, "created": "2026-01-01T12:00:00Z", "body": BODY}


def issue(i, sprints=None, comments=None, summary=None):
    return {"id": str(i), "key": f"DEMO-{i}", "fields": {
        "summary": summary or f"Synthetic task {i}", "status": {"name": "In Progress"},
        "customfield_123": sprints, "comment": {"comments": [], "total": 999}},
        "comments": comments if comments is not None else [comment(i * 10)]}


class Server:
    def __init__(self):
        self.issues = [issue(1, [{"id": 1}]), issue(2)]
        self.user = "me"
        self.requests = []
        self.page_size = 1
        self.status = 200
        self.bad_json = False
        self.partial = False
        self.duplicate = False
        self.delay = 0
        self.redirect = None
        self.retry_after = "1"
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                path = parsed.path.removeprefix("/jira")
                params = parse_qs(parsed.query)
                fixture.requests.append(("GET", path, params, self.headers.get("Authorization")))
                if fixture.delay:
                    time.sleep(fixture.delay)
                if fixture.redirect:
                    self.send_response(302)
                    self.send_header("Location", fixture.redirect)
                    self.end_headers()
                    return
                if fixture.status != 200:
                    self.send_response(fixture.status)
                    self.send_header("Retry-After", fixture.retry_after)
                    self.end_headers()
                    self.wfile.write(b"SECRET RESPONSE BODY")
                    return
                if path == "/rest/api/2/myself":
                    data = {"key": fixture.user, "displayName": "Synthetic User"}
                elif path == "/rest/api/2/field":
                    data = [{"id": "customfield_123", "schema": {
                        "custom": "com.pyxis.greenhopper.jira:gh-sprint"}}]
                elif path == "/rest/api/2/search":
                    data = self.page(fixture.issues, "issues", params)
                elif path.startswith("/rest/agile/1.0/sprint/"):
                    sid = int(path.rsplit("/", 1)[1])
                    data = {"id": sid, "name": f"Sprint {sid}", "state": "closed" if sid == 3 else "active"}
                elif path.startswith("/rest/api/2/issue/") and path.endswith("/comment"):
                    iid = path.split("/")[-2]
                    data = self.page(next(i for i in fixture.issues if i["id"] == iid)["comments"], "comments", params)
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                try:
                    self.wfile.write(b"broken JSON secret" if fixture.bad_json else json.dumps(data).encode())
                except BrokenPipeError:
                    pass

            def page(self, items, key, params):
                start = int(params.get("startAt", [0])[0])
                subset = items[start:start + fixture.page_size]
                if fixture.partial and start:
                    subset = []
                if fixture.duplicate and start:
                    subset = items[:fixture.page_size]
                return {key: subset, "total": len(items), "startAt": start, "maxResults": fixture.page_size}

            def do_POST(self):
                fixture.requests.append(("POST", self.path, {}, None))
                self.send_response(405)
                self.end_headers()

            do_PUT = do_DELETE = do_PATCH = do_POST

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.http.server_port}/jira"

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()


class OverviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = Server()
        self.temp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp.name)
        self.opened = []
        self.browser_ok = True
        self.browser_gate = None

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.close)
        self.temp.cleanup()

    async def browser(self, url):
        self.opened.append(url)
        if self.browser_gate:
            await self.browser_gate.wait()
        return self.browser_ok

    def make_app(self, interval=3600):
        return Overview(Jira(self.server.url, TOKEN, allow_local_http=True), self.state_dir,
                        interval=interval, browser=self.browser)

    @asynccontextmanager
    async def running(self, *, size=(110, 32), interval=3600):
        app = self.make_app(interval)
        async with app.run_test(size=size) as pilot:
            await self.settled(app, pilot)
            yield app, pilot

    async def settled(self, app, pilot):
        for _ in range(300):
            await pilot.pause(0.01)
            if not app.refreshing and not app.opening:
                return
        self.fail("TUI did not settle")

    async def refresh(self, app, pilot):
        await pilot.press("r")
        await self.settled(app, pilot)

    def rows(self, app, table):
        widget = app.query_one("#" + table, IssueTable)
        return [[str(cell) for cell in widget.get_row_at(i)] for i in range(widget.row_count)]

    def visible(self, app):
        return str(self.rows(app, "sprint")) + str(self.rows(app, "other"))

    def status(self, app):
        return str(app.query_one("#connection", Static).render())

    def notice(self, app):
        return str(app.query_one("#notice", Static).render())

    async def test_baseline_pagination_regions_and_read_only(self):
        self.server.issues[0]["comments"] = [comment(1), comment(2), comment(3)]
        async with self.running() as (app, pilot):
            self.assertIn("DEMO-1", str(self.rows(app, "sprint")))
            self.assertIn("DEMO-2", str(self.rows(app, "other")))
            self.assertNotIn("NEW", self.visible(app))
            self.assertNotIn("комм.", self.visible(app))
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

    async def test_new_persists_refresh_restart_and_return_is_not_new(self):
        async with self.running() as (app, pilot):
            self.server.issues.append(issue(4, comments=[comment(41), comment(42)]))
            await self.refresh(app, pilot)
            self.assertIn("DEMO-4 NEW", self.visible(app))
            self.assertNotIn("комм.", self.visible(app))
            await self.refresh(app, pilot)
            self.assertIn("DEMO-4 NEW", self.visible(app))
        async with self.running() as (app, pilot):
            self.assertIn("DEMO-4 NEW", self.visible(app))
            old = self.server.issues.pop(0)
            await self.refresh(app, pilot)
            self.server.issues.append(old)
            await self.refresh(app, pilot)
            self.assertEqual(self.rows(app, "sprint")[0][0], "DEMO-1")

    async def test_multiple_sprints_move_selection_and_no_duplicate(self):
        self.server.issues[0]["fields"]["customfield_123"] = [
            {"id": 1}, "com.atlassian.Sprint@a[id=2,state=ACTIVE,name=legacy]", {"id": 3}]
        async with self.running() as (app, pilot):
            heading = str(app.query_one("#sprint-heading", Static).render())
            self.assertIn("Sprint 1", heading)
            self.assertIn("Sprint 2", heading)
            self.assertNotIn("Sprint 3", heading)
            self.server.issues[0]["fields"]["customfield_123"] = None
            await self.refresh(app, pilot)
            self.assertEqual(len(self.rows(app, "sprint")), 0)
            self.assertEqual(len(self.rows(app, "other")), 2)
            self.assertNotIn("NEW", self.visible(app))
            self.assertEqual(app.focused.id, "other")
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-1"])

    async def test_comments_ignore_self_edits_and_count_replacement(self):
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"][0]["body"] = "edited"
            self.server.issues[0]["fields"]["status"]["name"] = "Review"
            self.server.issues[0]["comments"].append(comment(11, "me"))
            await self.refresh(app, pilot)
            self.assertNotIn("комм.", self.visible(app))
            self.server.issues[0]["comments"].pop(0)
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            self.assertIn("+1 комм.", self.visible(app))
        async with self.running() as (app, pilot):
            self.assertIn("+1 комм.", self.visible(app))

    async def test_enter_and_real_mouse_click_acknowledge(self):
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-1"])
            self.assertNotIn("комм.", self.visible(app))
            await pilot.click("#other", offset=(5, 1))
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-2")
            self.assertEqual(len(self.opened), 2)

    async def test_browser_failure_preserves_markers(self):
        self.browser_ok = False
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertIn("+1 комм.", self.visible(app))
            self.assertIn("не принял", self.notice(app))

    async def test_browser_race_acknowledges_only_displayed_snapshot(self):
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            self.browser_gate = asyncio.Event()
            await pilot.press("enter")
            await pilot.pause(0.05)
            self.assertTrue(app.opening)
            self.server.issues[0]["comments"].append(comment(13))
            await pilot.press("r")
            for _ in range(100):
                await pilot.pause(0.01)
                if not app.refreshing:
                    break
            self.assertIn("+2 комм.", self.visible(app))
            self.browser_gate.set()
            await self.settled(app, pilot)
            self.assertIn("+1 комм.", self.visible(app))

    async def test_profile_isolation_and_identity_change(self):
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            self.server.user = "another"
            await self.refresh(app, pilot)
            self.assertIn("Учётная запись изменилась", self.status(app))
            self.assertIn("+1 комм.", self.visible(app))
        async with self.running() as (app, pilot):
            self.assertNotIn("комм.", self.visible(app))
            self.assertEqual(len(list(self.state_dir.glob("*.json"))), 2)

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

    async def test_partial_invalid_and_duplicate_pages_never_commit_baseline(self):
        for mode in ("partial", "bad_json", "duplicate"):
            with self.subTest(mode=mode):
                setattr(self.server, mode, True)
                async with self.running() as (app, pilot):
                    self.assertIn("НЕТ УСПЕШНОЙ", self.status(app))
                    self.assertFalse(list(self.state_dir.glob("*.json")))
                    setattr(self.server, mode, False)
                    await self.refresh(app, pilot)
                    self.assertIn("Обновлено", self.status(app))
                    self.assertNotIn("NEW", self.visible(app))
                for path in self.state_dir.glob("*.json"):
                    path.unlink()

    async def test_bad_refresh_preserves_disk_and_unread(self):
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            before = app.state.path.read_bytes()
            self.server.partial = True
            await self.refresh(app, pilot)
            self.assertEqual(app.state.path.read_bytes(), before)
            self.assertIn("+1 комм.", self.visible(app))

    async def test_corruption_second_instance_and_save_failure(self):
        async with self.running() as (app, pilot):
            state_path = app.state.path
            second = self.make_app()
            async with second.run_test() as second_pilot:
                await self.settled(second, second_pilot)
                self.assertIn("Другой экземпляр", self.status(second))
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            before = state_path.read_bytes()
            with patch("jira_overview.core.os.replace", side_effect=OSError("private path")):
                await pilot.press("enter")
                await self.settled(app, pilot)
                self.assertIn("НЕ сохранены", self.notice(app))
                self.assertIn("+1 комм.", self.visible(app))
                self.assertEqual(state_path.read_bytes(), before)
                self.assertNotIn("private path", self.notice(app))
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertNotIn("комм.", self.visible(app))
        state_path.write_text("broken state")
        async with self.running() as (app, pilot):
            self.assertIn("повреждено", self.status(app))
            self.assertEqual(state_path.read_text(), "broken state")

    async def test_empty_and_long_lists_selection_survives_and_nearest_on_removal(self):
        self.server.issues = []
        async with self.running() as (app, pilot):
            self.assertIn("нет задач", str(app.query_one("#other-heading", Static).render()))
            await pilot.press("enter")
            self.assertFalse(self.opened)
            self.server.issues = [issue(i) for i in range(1, 31)]
            await self.refresh(app, pilot)
            await pilot.press("tab", "down", "down", "pagedown")
            table = app.query_one("#other", IssueTable)
            key = table.get_row_at(table.cursor_row)[0].plain.split()[0]
            await self.refresh(app, pilot)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain.split()[0], key)
            self.server.issues = [i for i in self.server.issues if i["key"] != key]
            row = table.cursor_row
            await self.refresh(app, pilot)
            self.assertEqual(table.cursor_row, min(row, 28))
            self.assertFalse(self.opened)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertNotEqual(self.opened[-1].rsplit("/", 1)[1], key)

    async def test_resize_controls_markup_and_narrow_screen(self):
        self.server.issues[0]["fields"]["summary"] = "[bold]literal[/bold]\x1b\x07\n\u202e$(touch /tmp/never)"
        async with self.running(size=(45, 16)) as (app, pilot):
            row = self.rows(app, "sprint")[0]
            self.assertIn("[bold]literal[/bold]", row[1])
            self.assertNotIn("\x1b", row[1])
            self.assertNotIn("\u202e", row[1])
            await pilot.resize_terminal(160, 45)
            await pilot.resize_terminal(45, 16)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-1"])
            await pilot.press("q")
            self.assertFalse(app.is_running)

    async def test_auto_refresh_no_overlap_and_exit_during_network(self):
        async with self.running(interval=0.2) as (app, pilot):
            self.server.issues.append(issue(4))
            await pilot.pause(0.6)
            await self.settled(app, pilot)
            self.assertIn("DEMO-4 NEW", self.visible(app))
            self.server.delay = 1
            await pilot.press("r", "r", "r")
            await pilot.pause(0.1)
            before = len(self.server.requests)
            await pilot.press("r", "r")
            self.assertEqual(len(self.server.requests), before)
            start = time.monotonic()
            await pilot.press("q")
            self.assertLess(time.monotonic() - start, 0.8)

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

    async def test_new_clears_on_open_and_later_comment_remains_new(self):
        async with self.running() as (app, pilot):
            self.server.issues.append(issue(4))
            await self.refresh(app, pilot)
            await pilot.press("tab", "down", "enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-4")
            self.assertNotIn("NEW", self.visible(app))
            self.server.issues[-1]["comments"].append(comment(41))
            await self.refresh(app, pilot)
            self.assertIn("DEMO-4 +1 комм.", self.visible(app))
        async with self.running() as (app, pilot):
            self.assertNotIn("NEW", self.visible(app))
            self.assertIn("+1 комм.", self.visible(app))

    async def test_first_write_failure_does_not_cross_accounts_on_retry(self):
        with patch("jira_overview.core.os.replace", side_effect=OSError()):
            async with self.running() as (app, pilot):
                self.assertIn("НЕ сохранены", self.status(app))
                self.assertFalse(list(self.state_dir.glob("*.json")))
                self.server.user = "another"
                await self.refresh(app, pilot)
                self.assertIn("Учётная запись изменилась", self.status(app))
                self.assertFalse(list(self.state_dir.glob("*.json")))

    async def test_instance_isolation_and_large_retry_after(self):
        async with self.running() as (app, pilot):
            other = State(self.state_dir, "https://other.example.org", app.snapshot.user_id)
            try:
                self.assertFalse(other.data["baseline"])
                self.assertNotEqual(other.path, app.state.path)
            finally:
                other.close()
            self.server.status = 429
            self.server.retry_after = "172800"
            await self.refresh(app, pilot)
            self.assertGreater(app.jira.retry_at - time.monotonic(), 172790)
            calls = len(self.server.requests)
            await self.refresh(app, pilot)
            self.assertEqual(len(self.server.requests), calls)

    async def test_cli_requires_tls_and_valid_configuration(self):
        from jira_overview.__main__ import configuration
        with self.assertRaises(OverviewError):
            Jira(self.server.url, TOKEN)
        config = self.state_dir / "config.toml"
        for contents in ('not TOML', 'url = "https://jira.example.org"',
                         'url = "https://jira.example.org"\ntoken_env = "MISSING_SYNTHETIC_TOKEN"'):
            config.write_text(contents)
            with self.assertRaises(OverviewError):
                configuration(config)

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


if __name__ == "__main__":
    unittest.main()
