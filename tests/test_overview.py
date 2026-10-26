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
from xml.etree import ElementTree

from rich.color import Color
from rich.text import Text
from textual.widgets import Static

from jira_overview.app import IssueTable, Overview
from jira_overview.core import Jira, OverviewError, State


TOKEN = "synthetic-token-never-persist"
BODY = "private-comment-body-never-persist"


def comment(cid, author="other"):
    return {"id": str(cid), "author": {"key": author}, "created": "2026-01-01T12:00:00Z", "body": BODY}


def issue(i, sprints=None, comments=None, summary=None, *, epic=False, epic_key=None, parent=None):
    return {"id": str(i), "key": f"DEMO-{i}", "fields": {
        "summary": summary or f"Synthetic task {i}", "status": {"name": "In Progress"},
        "customfield_456": f"Большая работа {i}" if epic else None,
        "customfield_789": epic_key, "parent": {"key": parent} if parent else None,
        "customfield_123": sprints, "comment": {"comments": [], "total": 999}},
        "comments": comments if comments is not None else [comment(i * 10)]}


class Server:
    def __init__(self):
        self.issues = [issue(1, [{"id": 1}]), issue(2)]
        self.context_issues = []
        self.fields = [{"id": field, "schema": {"custom": "com.pyxis.greenhopper.jira:" + kind}}
                       for field, kind in (("customfield_123", "gh-sprint"),
                                           ("customfield_456", "gh-epic-label"),
                                           ("customfield_789", "gh-epic-link"))]
        self.fail_path = None
        self.user = "me"
        self.requests = []
        self.page_size = 1
        self.status = 200
        self.bad_json = False
        self.partial = False
        self.duplicate = False
        self.total_delta = 0
        self.bad_start = False
        self.delay = 0
        self.request_gate = False
        self.request_started = threading.Event()
        self.request_release = threading.Event()
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
                if fixture.request_gate:
                    fixture.request_started.set()
                    fixture.request_release.wait(timeout=10)
                if fixture.delay:
                    time.sleep(fixture.delay)
                if fixture.redirect:
                    self.send_response(302)
                    self.send_header("Location", fixture.redirect)
                    self.end_headers()
                    return
                if fixture.status != 200 or path == fixture.fail_path:
                    self.send_response(fixture.status if fixture.status != 200 else 403)
                    self.send_header("Retry-After", fixture.retry_after)
                    self.end_headers()
                    self.wfile.write(b"SECRET RESPONSE BODY")
                    return
                if path == "/rest/api/2/myself":
                    data = {"key": fixture.user, "displayName": "Synthetic User"}
                elif path == "/rest/api/2/field":
                    data = fixture.fields
                elif path == "/rest/api/2/search":
                    data = self.page(fixture.issues, "issues", params)
                elif path.startswith("/rest/agile/1.0/sprint/"):
                    sid = int(path.rsplit("/", 1)[1])
                    data = {"id": sid, "name": f"Sprint {sid}", "state": "closed" if sid == 3 else "active"}
                elif path.startswith("/rest/api/2/issue/") and path.endswith("/comment"):
                    iid = path.split("/")[-2]
                    data = self.page(next(i for i in fixture.issues if i["id"] == iid)["comments"], "comments", params)
                elif path.startswith("/rest/api/2/issue/"):
                    key = path.rsplit("/", 1)[1]
                    data = next((i for i in fixture.issues + fixture.context_issues if i["key"] == key), None)
                    if data is None:
                        self.send_response(404)
                        self.end_headers()
                        return
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                try:
                    self.wfile.write(b"broken JSON secret" if fixture.bad_json else json.dumps(data).encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def page(self, items, key, params):
                start = int(params.get("startAt", [0])[0])
                subset = items[start:start + fixture.page_size]
                if fixture.partial and start:
                    subset = []
                if fixture.duplicate and start:
                    subset = items[:fixture.page_size]
                total = len(items) + (fixture.total_delta if start else 0)
                start_at = start + (1 if fixture.bad_start and start else 0)
                return {key: subset, "total": total, "startAt": start_at, "maxResults": fixture.page_size}

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

    def issue_rows(self, app, table):
        return [row for row in self.rows(app, table) if row[2]]

    def visible(self, app):
        return str(self.rows(app, "sprint")) + str(self.rows(app, "other"))

    def status(self, app):
        return str(app.query_one("#connection", Static).render())

    def notice(self, app):
        return str(app.query_one("#notice", Static).render())

    def assert_row_highlight(self, app, table_id, row_index, *, new=False, unread=0):
        table = app.query_one("#" + table_id, IssueTable)
        issue_indices = [index for index in range(table.row_count) if table.get_row_at(index)[2]]
        key, summary, status = table.get_row_at(issue_indices[row_index])
        marker = (" NEW" if new else "") + (f" Comment +{unread}" if unread else "")
        self.assertEqual(key.plain, key.plain.split()[0] + marker)
        for text in (key, summary):
            self.assertEqual(bool(text.get_style_at_offset(app.console, 0).bold), bool(new or unread))
        self.assertFalse(status.get_style_at_offset(app.console, 0).bold)
        for label, color in (("NEW", "green"), (f"Comment +{unread}", "yellow")):
            if label in key.plain:
                start = key.plain.index(label)
                for offset in range(start, start + len(label)):
                    style = key.get_style_at_offset(app.console, offset)
                    self.assertTrue(style.bold)
                    self.assertEqual(style.color, Color.parse(color))

    def assert_status_columns_aligned(self, app, *, rendered=True):
        sprint = app.query_one("#sprint", IssueTable)
        other = app.query_one("#other", IssueTable)
        self.assertEqual([column.get_render_width(sprint) for column in sprint.ordered_columns],
                         [column.get_render_width(other) for column in other.ordered_columns])
        if rendered:
            positions = []
            for table in (sprint, other):
                header = "".join(segment.text for segment in table.render_line(0))
                self.assertIn("Статус", header)
                positions.append(table.region.x + Text(header[:header.index("Статус")]).cell_len)
            self.assertEqual(*positions)

    async def test_status_columns_share_widths_for_content_markers_and_empty_areas(self):
        self.server.issues[0]["fields"]["summary"] = "Коротко"
        self.server.issues[1]["key"] = "LONG_PROJECT-200"
        summary = "Название с широкими 界界 и e\u0301"
        self.server.issues[1]["fields"]["summary"] = summary
        self.server.issues[1]["fields"]["status"]["name"] = "Awaiting Verification"
        async with self.running(size=(180, 36)) as (app, pilot):
            await pilot.pause()
            self.assert_status_columns_aligned(app)
            sprint = app.query_one("#sprint", IssueTable)
            self.assertEqual(sprint.ordered_columns[1].width, Text(summary).cell_len)
            initial_width = sprint.virtual_size.width
            self.server.issues.append(issue(300, [{"id": 1}], summary="Новая"))
            self.server.issues[0]["comments"].append(comment(19))
            await self.refresh(app, pilot)
            self.assert_status_columns_aligned(app)
            self.assertIn("DEMO-300 NEW", str(self.rows(app, "sprint")))
            self.assertIn("DEMO-1 Comment +1", str(self.rows(app, "sprint")))
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assert_status_columns_aligned(app)
            self.assertEqual(sprint._key_at(sprint.cursor_row), "1")
            self.server.issues = [self.server.issues[0]]
            await self.refresh(app, pilot)
            self.assert_status_columns_aligned(app)
            self.assertLess(sprint.virtual_size.width, initial_width)
            self.server.issues[0]["fields"]["customfield_123"] = None
            await self.refresh(app, pilot)
            self.assert_status_columns_aligned(app)
            self.assertEqual(sprint.row_count, 0)
            self.assertEqual(app.focused.id, "other")
            self.server.issues = []
            await self.refresh(app, pilot)
            self.assert_status_columns_aligned(app)
            self.assertEqual([column.width for column in sprint.ordered_columns],
                             [Text(label).cell_len for label in ("Тикет", "Название", "Статус")])

    async def test_status_columns_stay_aligned_on_resize_scroll_and_return_from_epics(self):
        self.epic_fixture()
        self.server.issues[1]["fields"]["summary"] = "Synthetic longer summary " * 3
        # Hidden epic headers must not inflate the ordinary column widths.
        self.server.issues[-1]["fields"]["summary"] = "Hidden epic " * 50
        async with self.running(size=(180, 36)) as (app, pilot):
            for width, height in ((180, 36), (45, 16), (140, 32)):
                await pilot.resize_terminal(width, height)
                await pilot.pause()
                self.assert_status_columns_aligned(app, rendered=width == 180)
                sprint = app.query_one("#sprint", IssueTable)
                other = app.query_one("#other", IssueTable)
                self.assertLess(sprint.virtual_size.width, 150)
                if width == 45:
                    self.assertTrue(sprint.show_horizontal_scrollbar)
                    self.assertTrue(other.show_horizontal_scrollbar)
                    for table in (sprint, other):
                        table.scroll_to(x=table.max_scroll_x, animate=False)
                    await pilot.pause()
                    self.assert_status_columns_aligned(app)
                self.assertEqual(app.query_one("#other-heading", Static).region.y - sprint.region.bottom, 1)
            await pilot.press("e")
            self.server.issues[1]["fields"]["summary"] = "Ещё одно название после обновления"
            await self.refresh(app, pilot)
            await pilot.press("e")
            await pilot.pause()
            self.assert_status_columns_aligned(app)
            self.assertEqual(app.focused.id, "sprint")

    async def test_three_columns_without_sprint_in_both_areas(self):
        async with self.running() as (app, pilot):
            for _ in range(2):
                for table_id, number in (("sprint", 1), ("other", 2)):
                    with self.subTest(table=table_id):
                        table = app.query_one("#" + table_id, IssueTable)
                        self.assertEqual(
                            [column.label.plain for column in table.ordered_columns],
                            ["Тикет", "Название", "Статус"],
                        )
                        self.assertEqual(self.rows(app, table_id), [
                            [f"DEMO-{number}", f"Synthetic task {number}", "In Progress"],
                        ])
                await self.refresh(app, pilot)

    async def test_highlight_combinations_refresh_open_and_restart(self):
        async with self.running() as (app, pilot):
            self.assert_row_highlight(app, "sprint", 0)
            self.assert_row_highlight(app, "other", 0)
            self.server.issues.extend([issue(3, [{"id": 1}]), issue(4)])
            await self.refresh(app, pilot)
            self.server.issues[0]["comments"].append(comment(12))
            self.server.issues[-1]["comments"].append(comment(41))
            await self.refresh(app, pilot)
            expected = [("sprint", 0, True, 0), ("sprint", 1, False, 1),
                        ("other", 0, True, 1), ("other", 1, False, 0)]
            for _ in range(2):
                for table_id, row_index, new, unread in expected:
                    with self.subTest(table=table_id, row=row_index):
                        self.assert_row_highlight(app, table_id, row_index, new=new, unread=unread)
                self.assertEqual([row[0].split()[0] for row in self.issue_rows(app, "sprint")],
                                 ["DEMO-3", "DEMO-1"])
                self.assertEqual([row[0].split()[0] for row in self.issue_rows(app, "other")],
                                 ["DEMO-4", "DEMO-2"])
                await self.refresh(app, pilot)
            await pilot.press("tab", "ctrl+home")
            self.browser_ok = False
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assert_row_highlight(app, "other", 0, new=True, unread=1)
            self.assertIn("Браузер не принял", self.notice(app))
            self.browser_ok = True
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-4")
            self.assertEqual(self.notice(app), "")
            self.assert_row_highlight(app, "other", 1)
            await self.refresh(app, pilot)
            self.assert_row_highlight(app, "other", 1)
        async with self.running() as (app, pilot):
            self.assert_row_highlight(app, "sprint", 0, new=True)
            self.assert_row_highlight(app, "sprint", 1, unread=1)
            self.assert_row_highlight(app, "other", 0)
            self.assert_row_highlight(app, "other", 1)

    async def test_marker_colors_survive_cursor_and_focus(self):
        async with self.running() as (app, pilot):
            self.server.issues.append(issue(4))
            await self.refresh(app, pilot)
            self.server.issues[-1]["comments"].append(comment(41))
            await self.refresh(app, pilot)
            await pilot.press("tab", "ctrl+home")
            table = app.query_one("#other", IssueTable)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-4 NEW Comment +1")
            for focused in (True, False):
                with self.subTest(focused=focused):
                    if not focused:
                        await pilot.press("tab")
                    self.assertEqual(table.has_focus, focused)
                    rendered = Text.assemble(*[(segment.text, segment.style) for segment in
                                              table.render_line(table.header_height + table.cursor_row)])
                    self.assertIn("DEMO-4 NEW Comment +1", rendered.plain)
                    for label, color in (("NEW", "green"), ("Comment +1", "yellow")):
                        start = rendered.plain.index(label)
                        for offset in range(start, start + len(label)):
                            style = rendered.get_style_at_offset(app.console, offset)
                            self.assertTrue(style.bold)
                            self.assertEqual(style.color, Color.parse(color))
                    if focused:
                        style = rendered.get_style_at_offset(app.console, rendered.plain.index("DEMO-4"))
                        self.assertEqual(style.bgcolor,
                                         table.get_component_rich_style("datatable--cursor").bgcolor)
            self.assertFalse(self.opened)
            self.assert_row_highlight(app, "other", 0, new=True, unread=1)

    async def test_highlight_follows_selected_issue_between_status_groups(self):
        async with self.running() as (app, pilot):
            self.server.issues[1]["fields"]["status"]["name"] = "To Do"
            self.server.issues.append(issue(3))
            self.server.issues[-1]["fields"]["status"]["name"] = "Hold"
            await self.refresh(app, pilot)
            self.server.issues[-1]["comments"].append(comment(31))
            await self.refresh(app, pilot)
            await pilot.press("tab", "ctrl+home")
            table = app.query_one("#other", IssueTable)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-3 NEW Comment +1")
            self.assert_row_highlight(app, "other", 0, new=True, unread=1)
            self.server.issues[-1]["fields"]["status"]["name"] = "In Progress"
            await self.refresh(app, pilot)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-3 NEW Comment +1")
            self.assertTrue(all(row[2] for row in self.rows(app, "other")))
            self.assert_row_highlight(app, "other", 0, new=True, unread=1)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-3"])
            self.assert_row_highlight(app, "other", 0)

    async def test_local_markers_sort_before_status_in_each_area_and_survive_restart(self):
        self.server.page_size = 100
        self.server.issues = []
        for base, sprints in ((0, [{"id": 1}]), (100, None)):
            for number, status in ((1, "In Progress"), (2, "To Do"), (3, "In Progress"),
                                   (4, "Backlog"), (5, "In Progress")):
                item = issue(base + number, sprints)
                item["fields"]["status"]["name"] = status
                self.server.issues.append(item)
        async with self.running() as (app, pilot):
            for item in self.server.issues:
                if int(item["id"]) % 100 in (2, 3):
                    item["comments"].append(comment(10000 + int(item["id"])))
            for base, sprints in ((0, [{"id": 1}]), (100, None)):
                for number, status in ((6, "Zulu"), (7, "Backlog"), (8, "To Do"), (9, "To Do")):
                    item = issue(base + number, sprints)
                    item["fields"]["status"]["name"] = status
                    if number == 9:
                        item["key"] = f"OTHER-{base + number}"
                    self.server.issues.append(item)
            await self.refresh(app, pilot)
            for item in self.server.issues:
                if int(item["id"]) % 100 == 7:
                    item["comments"].extend([comment(10000 + int(item["id"])),
                                              comment(20000 + int(item["id"]))])
            await self.refresh(app, pilot)
            before = {area: self.rows(app, area) for area in ("sprint", "other")}
            for area, base in (("sprint", 0), ("other", 100)):
                with self.subTest(area=area):
                    rows = before[area]
                    self.assertEqual([row[0] for row in rows], [
                        f"DEMO-{base + 8} NEW", f"OTHER-{base + 9} NEW",
                        f"DEMO-{base + 7} NEW Comment +2", f"DEMO-{base + 6} NEW",
                        f"DEMO-{base + 3} Comment +1", f"DEMO-{base + 2} Comment +1",
                        f"DEMO-{base + 1}", f"DEMO-{base + 5}", f"DEMO-{base + 4}",
                    ])
                    self.assertEqual([row[2] for row in rows], [
                        "To Do", "To Do", "Backlog", "Zulu", "In Progress", "To Do",
                        "In Progress", "In Progress", "Backlog",
                    ])
                    self.assertEqual(len({row[0].split()[0] for row in rows}), 9)
                    self.assertIn("(9)", str(app.query_one("#" + area + "-heading", Static).render()))
                    for index in range(9):
                        self.assert_row_highlight(app, area, index, new=index < 4,
                                                  unread=2 if index == 2 else int(index in (4, 5)))
                    app.query_one("#" + area, IssueTable).focus()
                    await pilot.press("ctrl+home")
                    for row in rows:
                        table = app.query_one("#" + area, IssueTable)
                        self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, row[0])
                        await pilot.press("down")
            self.assertFalse(self.opened)
            self.server.status = 500
            await self.refresh(app, pilot)
            self.assertIn("УСТАРЕЛО", self.status(app))
            self.assertEqual({area: self.rows(app, area) for area in before}, before)
            self.server.status = 200
            await self.refresh(app, pilot)
            self.assertEqual({area: self.rows(app, area) for area in before}, before)
        async with self.running() as (app, pilot):
            self.assertEqual({area: self.rows(app, area) for area in before}, before)
            self.assertFalse(self.opened)

    async def test_selection_follows_marker_promotion_and_acknowledgment_in_each_area(self):
        self.server.page_size = 100
        self.server.issues = [issue(1, [{"id": 1}]), issue(2, [{"id": 1}]),
                              issue(101), issue(102)]
        for item in self.server.issues:
            if int(item["id"]) % 100 == 2:
                item["fields"]["status"]["name"] = "To Do"
        async with self.running() as (app, pilot):
            for area, base, sprints in (("sprint", 0, [{"id": 1}]), ("other", 100, None)):
                with self.subTest(area=area):
                    table = app.query_one("#" + area, IssueTable)
                    table.focus()
                    await pilot.press("ctrl+end")
                    self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, f"DEMO-{base + 2}")
                    added = issue(base + 3, sprints)
                    added["fields"]["status"]["name"] = "Backlog"
                    self.server.issues.append(added)
                    await self.refresh(app, pilot)
                    self.assertEqual(table.cursor_row, 2)
                    self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, f"DEMO-{base + 2}")
                    existing = next(item for item in self.server.issues if item["id"] == str(base + 2))
                    existing["comments"].append(comment(10000 + base))
                    added["comments"].append(comment(20000 + base))
                    await self.refresh(app, pilot)
                    self.assertEqual(table.cursor_row, 1)
                    self.assertEqual(table.get_row_at(table.cursor_row)[0].plain,
                                     f"DEMO-{base + 2} Comment +1")
                    await pilot.press("ctrl+home")
                    before = self.rows(app, area)
                    self.browser_ok = False
                    await pilot.press("enter")
                    await self.settled(app, pilot)
                    self.assertEqual(self.rows(app, area), before)
                    self.assertEqual(table.cursor_row, 0)
                    self.browser_ok = True
                    with patch("jira_overview.core.os.replace", side_effect=OSError("synthetic failure")):
                        await pilot.press("enter")
                        await self.settled(app, pilot)
                    self.assertEqual(self.rows(app, area), before)
                    self.assertEqual(table.cursor_row, 0)
                    self.assertIn("НЕ сохранены", self.notice(app))
                    await pilot.press("enter")
                    await self.settled(app, pilot)
                    self.assertEqual(self.opened[-1], self.server.url + f"/browse/DEMO-{base + 3}")
                    self.assertEqual(table.cursor_row, 2)
                    self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, f"DEMO-{base + 3}")
                    self.assertEqual([row[0] for row in self.rows(app, area)], [
                        f"DEMO-{base + 2} Comment +1", f"DEMO-{base + 1}", f"DEMO-{base + 3}",
                    ])
                    await pilot.press("ctrl+home", "enter")
                    await self.settled(app, pilot)
                    self.assertEqual(table.cursor_row, 1)
                    self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, f"DEMO-{base + 2}")
                    self.assertEqual([row[0] for row in self.rows(app, area)],
                                     [f"DEMO-{base + number}" for number in (1, 2, 3)])

    async def test_status_groups_are_exact_ordered_and_keep_issue_order_and_markers(self):
        self.server.issues = [
            issue(1, [{"id": 1}]), issue(2, [{"id": 1}]), issue(3), issue(4),
            issue(5), issue(6), issue(7), issue(8), issue(9), issue(10), issue(11),
            issue(12), issue(13),
        ]
        statuses = ["Open", "In Progress", "To Do", "Hold", "On Hold", "Backlog",
                    "Бэклог", "Review", "review"]
        for item, status in zip(self.server.issues, statuses):
            item["fields"]["status"]["name"] = status
        for item, status in zip(self.server.issues[9:],
                                ["В работе", "К выполнению", "in progress", "к выполнению"]):
            item["fields"]["status"]["name"] = status
        async with self.running() as (app, pilot):
            for _ in range(300):
                if "Обновлено" in self.status(app):
                    break
                await pilot.pause(0.01)
            self.server.issues.append(issue(14))
            self.server.issues[-1]["fields"]["status"]["name"] = "In Progress"
            cross_project = issue(15)
            cross_project["key"] = "OTHER-15"
            cross_project["fields"]["status"]["name"] = "In Progress"
            self.server.issues.append(cross_project)
            await self.refresh(app, pilot)
            other_table = app.query_one("#other", IssueTable)
            for _ in range(100):
                if other_table.row_count:
                    break
                await pilot.pause(0.01)
            sprint = self.rows(app, "sprint")
            other = self.rows(app, "other")
            self.assertEqual([r[0] or r[1] for r in sprint], [
                "DEMO-2", "DEMO-1",
            ])
            self.assertEqual([r[0] for r in other], [
                "DEMO-14 NEW", "OTHER-15 NEW", "DEMO-12", "DEMO-10", "DEMO-3",
                "DEMO-11", "DEMO-13", "DEMO-4", "DEMO-5", "DEMO-6", "DEMO-7",
                "DEMO-8", "DEMO-9",
            ])
            for rows in (sprint, other):
                self.assertTrue(all(row[2] for row in rows))
            self.assertEqual([r[2] for r in other if r[0].startswith(("DEMO-", "OTHER-"))],
                             ["In Progress", "In Progress", "in progress", "В работе", "To Do",
                              "К выполнению", "к выполнению", "Hold", "On Hold",
                              "Backlog", "Бэклог", "Review", "review"])

    async def test_single_status_group_is_compact_in_both_areas(self):
        async with self.running() as (app, pilot):
            for _ in range(2):
                await pilot.pause()
                for area, key in (("sprint", "DEMO-1"), ("other", "DEMO-2")):
                    with self.subTest(area=area):
                        table = app.query_one("#" + area, IssueTable)
                        rows = self.rows(app, area)
                        self.assertEqual(len(rows), 1)
                        self.assertEqual(rows[0][0], key)
                        self.assertEqual(rows[0][2], "In Progress")
                        self.assertEqual(table.cursor_row, 0)
                        rendered = "".join(segment.text for segment in
                                           table.render_line(table.header_height))
                        self.assertIn(key, rendered)
                        heading = str(app.query_one("#" + area + "-heading", Static).render())
                        self.assertIn("(1)", heading)
                await self.refresh(app, pilot)

    async def test_compact_sprint_rows_render_and_navigate_without_gaps(self):
        self.server.issues = [issue(i, [{"id": 1}]) for i in range(1, 7)]
        for item, status in zip(self.server.issues,
                                ["In Progress", "On Hold", "On Hold", "Backlog",
                                 "Verifying", "Verifying"]):
            item["fields"]["status"]["name"] = status
        async with self.running() as (app, pilot):
            table = app.query_one("#sprint", IssueTable)
            expected = [f"DEMO-{i}" for i in range(1, 7)]
            await pilot.pause()
            self.assertEqual(table.row_count, len(expected))
            self.assertEqual([row[0] for row in self.rows(app, "sprint")], expected)
            for index, key in enumerate(expected):
                rendered = "".join(segment.text for segment in
                                   table.render_line(table.header_height + index))
                self.assertIn(key, rendered)
                self.assertEqual(table.cursor_row, index)
                await pilot.press("down")
            await pilot.press("ctrl+home", "down", "down", "down")
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-4")
            self.server.issues[3]["fields"]["status"]["name"] = "In Progress"
            self.server.issues[3]["comments"].append(comment(41))
            await self.refresh(app, pilot)
            self.assertEqual(table.row_count, len(expected))
            self.assertEqual(table.cursor_row, 0)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-4 Comment +1")
            self.assert_row_highlight(app, "sprint", 0, unread=1)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-4"])
            await pilot.press("ctrl+home")
            await pilot.click("#sprint", offset=(5, table.header_height))
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-1")

    async def test_sprint_height_tracks_rows_with_one_blank_line_between_areas(self):
        self.server.page_size = 100
        async with self.running(size=(110, 40)) as (app, pilot):
            sprint = app.query_one("#sprint", IssueTable)
            other_heading = app.query_one("#other-heading", Static)

            async def assert_layout(count):
                await pilot.pause()
                self.assertEqual(sprint.row_count, count)
                self.assertEqual(sprint.size.height, sprint.header_height + count)
                self.assertEqual(other_heading.region.y - sprint.region.bottom, 1)
                return other_heading.region.y

            initial_y = await assert_layout(1)
            self.server.issues.extend([issue(3, [{"id": 1}]), issue(4, [{"id": 1}])])
            await self.refresh(app, pilot)
            self.assertEqual(await assert_layout(3), initial_y + 2)
            self.server.issues[0]["fields"]["customfield_123"] = None
            await self.refresh(app, pilot)
            self.assertEqual(await assert_layout(2), initial_y + 1)
            for item in self.server.issues:
                item["fields"]["customfield_123"] = None
            await self.refresh(app, pilot)
            self.assertEqual(await assert_layout(0), initial_y - 1)
            self.assertIn("нет задач", str(app.query_one("#sprint-heading", Static).render()))
            self.server.issues[0]["fields"]["customfield_123"] = [{"id": 1}]
            await self.refresh(app, pilot)
            self.assertEqual(await assert_layout(1), initial_y)
            self.server.issues.extend(issue(i, [{"id": 1}]) for i in range(5, 35))
            await self.refresh(app, pilot)
            await pilot.pause()
            self.assertLess(sprint.size.height, sprint.header_height + sprint.row_count)
            self.assertEqual(other_heading.region.y - sprint.region.bottom, 1)
            await pilot.press("ctrl+end")
            self.server.issues = self.server.issues[:2]
            await self.refresh(app, pilot)
            self.assertEqual(await assert_layout(1), initial_y)
            self.assertEqual(sprint.scroll_y, 0)

    async def test_sprint_gap_survives_wrapped_heading_and_horizontal_scrollbar(self):
        self.server.issues[0]["fields"]["summary"] = "Synthetic long task " * 8
        self.server.issues[0]["fields"]["customfield_123"] = [
            {"id": sid} for sid in (1, 2, 4, 5, 6, 7, 8)]
        async with self.running(size=(45, 16)) as (app, pilot):
            sprint = app.query_one("#sprint", IssueTable)
            heading = app.query_one("#sprint-heading", Static)
            other = app.query_one("#other", IssueTable)
            other_heading = app.query_one("#other-heading", Static)
            for width, height in ((45, 16), (160, 45), (45, 16)):
                with self.subTest(size=(width, height)):
                    await pilot.resize_terminal(width, height)
                    await pilot.pause()
                    if width == 45:
                        self.assertEqual(heading.size.height, 3)
                        self.assertTrue(sprint.show_horizontal_scrollbar)
                    self.assertEqual(sprint.size.height, sprint.header_height + sprint.row_count +
                                     (sprint.scrollbar_size_horizontal
                                      if sprint.show_horizontal_scrollbar else 0))
                    self.assertEqual(other_heading.region.y - sprint.region.bottom, 1)
                    self.assertGreater(other.scrollable_content_region.height, other.header_height)
                    self.assertLessEqual(other.region.bottom, height - 1)
                    await pilot.click(offset=(3, sprint.region.bottom))
                    await self.settled(app, pilot)
                    self.assertEqual(self.opened, [])

    async def test_long_sprint_keeps_both_areas_visible_and_independently_scrollable(self):
        self.server.page_size = 100
        self.server.issues = ([issue(i, [{"id": 1}]) for i in range(1, 31)] +
                              [issue(i) for i in range(31, 61)])
        async with self.running(size=(110, 32)) as (app, pilot):
            sprint = app.query_one("#sprint", IssueTable)
            other = app.query_one("#other", IssueTable)
            other_heading = app.query_one("#other-heading", Static)
            for width, height in ((110, 32), (45, 16), (160, 45), (45, 16)):
                with self.subTest(size=(width, height)):
                    await pilot.resize_terminal(width, height)
                    await pilot.pause()
                    self.assertEqual(other_heading.region.y - sprint.region.bottom, 1)
                    self.assertGreater(sprint.scrollable_content_region.height, sprint.header_height)
                    self.assertGreater(other.scrollable_content_region.height, other.header_height)
                    self.assertLessEqual(other.region.bottom, height - 1)
                    self.assertGreater(sprint.max_scroll_y, 0)
                    self.assertGreater(other.max_scroll_y, 0)
                    sprint.focus()
                    await pilot.press("ctrl+end")
                    await pilot.pause()
                    self.assertGreater(sprint.scroll_y, 0)
                    before = sprint.scroll_y
                    await pilot.press("tab", "ctrl+end")
                    await pilot.pause()
                    self.assertEqual(app.focused.id, "other")
                    self.assertGreater(other.scroll_y, 0)
                    self.assertEqual(sprint.scroll_y, before)
                    self.assertEqual(self.opened, [])

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

    async def test_multiple_sprints_move_selection_and_no_duplicate(self):
        self.server.issues[0]["fields"]["customfield_123"] = [
            {"id": 1}, "com.atlassian.Sprint@a[id=2,state=ACTIVE,name=legacy]", {"id": 3}]
        async with self.running() as (app, pilot):
            heading = str(app.query_one("#sprint-heading", Static).render())
            self.assertIn("Sprint 1 (#1)", heading)
            self.assertIn("Sprint 2 (#2)", heading)
            self.assertNotIn("Sprint 3", heading)
            self.assertEqual(self.rows(app, "sprint"), [
                ["DEMO-1", "Synthetic task 1", "In Progress"],
            ])
            self.server.issues[0]["fields"]["customfield_123"] = None
            await self.refresh(app, pilot)
            self.assertEqual(len(self.rows(app, "sprint")), 0)
            self.assertEqual(len(self.rows(app, "other")), 2)
            self.assertTrue(all(len(row) == 3 for row in self.rows(app, "other")))
            self.assertNotIn("NEW", self.visible(app))
            self.assertEqual(app.focused.id, "other")
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-1"])

    async def test_selection_tracks_issue_across_status_area_move_and_removal(self):
        self.server.issues = [issue(1, [{"id": 1}]), issue(2), issue(3)]
        async with self.running() as (app, pilot):
            await pilot.press("tab")
            table = app.query_one("#other", IssueTable)
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-2")
            self.server.issues[1]["fields"]["status"]["name"] = "To Do"
            self.server.issues[1]["fields"]["customfield_123"] = [{"id": 1}]
            await self.refresh(app, pilot)
            table = app.query_one("#sprint", IssueTable)
            self.assertEqual(app.focused.id, "sprint")
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-2")
            self.server.issues.pop(1)
            await self.refresh(app, pilot)
            self.assertEqual(app.focused.id, "sprint")
            self.assertEqual(table.get_row_at(table.cursor_row)[0].plain, "DEMO-1")
            self.assertTrue(table.get_row_at(table.cursor_row)[2])

    async def test_long_status_is_plain_and_safe_at_minimum_size(self):
        status = "[bold]" + ("Synthetic Status " * 80) + "\x1b\u202e"
        self.server.issues[0]["fields"]["status"]["name"] = status
        async with self.running(size=(45, 16)) as (app, pilot):
            self.assertIn("Synthetic Status", str(self.rows(app, "sprint")))
            self.assertNotIn("\x1b", str(self.rows(app, "sprint")))
            self.assertNotIn("\u202e", str(self.rows(app, "sprint")))
            self.assertIn("[bold]", str(self.rows(app, "sprint")))
            self.assertEqual(self.rows(app, "sprint")[0][0], "DEMO-1")
            # Snapshot acceptance precedes the DataTable idle pass that measures columns.
            await pilot.pause()
            screenshot = ElementTree.fromstring(app.export_screenshot())
            visible_text = " ".join("".join(screenshot.itertext()).split())
            self.assertIn("DEMO-1", visible_text)
            self.assertIn("Synthetic task 1", visible_text)
            await pilot.resize_terminal(160, 45)
            await pilot.resize_terminal(45, 16)

    async def test_compact_other_rows_render_navigate_and_ignore_clicks_outside_issues(self):
        self.server.issues = [issue(i) for i in range(1, 8)]
        for item, status in zip(self.server.issues,
                                ["In Progress", "To Do", "Hold", "Backlog", "Open", "Review", "Zulu"]):
            item["fields"]["status"]["name"] = status
        async with self.running() as (app, pilot):
            table = app.query_one("#other", IssueTable)
            await pilot.press("tab", "ctrl+home")
            expected = [f"DEMO-{i}" for i in range(1, 8)]
            self.assertEqual(table.row_count, len(expected))
            self.assertEqual([row[0] for row in self.rows(app, "other")], expected)
            for index, key in enumerate(expected):
                rendered = "".join(segment.text for segment in
                                   table.render_line(table.header_height + index))
                self.assertIn(key, rendered)
            self.assertEqual(table.cursor_row, 0)
            await pilot.press("down")
            self.assertEqual(table.cursor_row, 1)
            await pilot.press("up")
            self.assertEqual(table.cursor_row, 0)
            await pilot.press("pagedown")
            self.assertEqual(table.cursor_row, len(expected) - 1)
            await pilot.press("pageup")
            self.assertEqual(table.cursor_row, 0)
            await pilot.press("ctrl+end", "enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-7"])
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            self.assertEqual(table.cursor_row, len(expected) - 1)
            self.assertIn("Comment +1", self.visible(app))
            await pilot.press("ctrl+home")
            for y in (0, table.header_height + table.row_count):
                await pilot.click("#other", offset=(5, y))
                await self.settled(app, pilot)
                self.assertEqual(len(self.opened), 1)
                self.assertIn("Comment +1", self.visible(app))
            await pilot.click("#other", offset=(5, table.header_height))
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-1")
            self.assertNotIn("Comment +1", self.visible(app))
            self.assertEqual(table.cursor_row, 0)

    async def test_enter_and_real_mouse_click_acknowledge(self):
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened, [self.server.url + "/browse/DEMO-1"])
            self.assertNotIn("Comment", self.visible(app))
            self.assertEqual(self.notice(app), "")
            await pilot.click("#other", offset=(5, 1))
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-2")
            self.assertEqual(len(self.opened), 2)
            self.assertEqual(self.notice(app), "")

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
            self.assertIn("Comment +2", self.visible(app))
            self.browser_gate.set()
            await self.settled(app, pilot)
            self.assertIn("Comment +1", self.visible(app))

    async def test_delayed_row_event_opens_issue_captured_before_repaint(self):
        entered, release = asyncio.Event(), asyncio.Event()
        class DelayedOverview(Overview):
            async def on_data_table_row_selected(inner, event):
                if not hasattr(inner, "captured"):
                    inner.captured = event
                    entered.set()
                    asyncio.create_task(inner.open_captured(event))
            async def open_captured(inner, event):
                await release.wait()
                super(DelayedOverview, inner).on_data_table_row_selected(event)
        app = DelayedOverview(Jira(self.server.url, TOKEN, allow_local_http=True), self.state_dir,
                              interval=3600, browser=self.browser)
        async with app.run_test() as pilot:
            await self.settled(app, pilot)
            await pilot.press("enter")
            await asyncio.wait_for(entered.wait(), 2)
            selected = app.captured.shown
            self.assertEqual(selected.key, "DEMO-1")
            self.server.issues = [item for item in self.server.issues if item["id"] != selected.id]
            await self.refresh(app, pilot)
            release.set()
            await self.settled(app, pilot)
            self.assertTrue(self.opened)
            self.assertTrue(all(url == self.server.url + "/browse/DEMO-1" for url in self.opened))
            self.server.issues.append(issue(1, [{"id": 1}], [comment(10)]))
            await self.refresh(app, pilot)
            self.assertNotIn("NEW", self.visible(app))

    async def test_profile_isolation_and_identity_change(self):
        async with self.running() as (app, pilot):
            self.server.issues[0]["comments"].append(comment(12))
            await self.refresh(app, pilot)
            self.server.user = "another"
            await self.refresh(app, pilot)
            self.assertIn("Учётная запись изменилась", self.status(app))
            self.assertIn("Comment +1", self.visible(app))
        async with self.running() as (app, pilot):
            self.assertNotIn("Comment", self.visible(app))
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

    async def test_corruption_second_instance_and_save_failure(self):
        async with self.running() as (app, pilot):
            state_path = next(self.state_dir.glob("*.json"))
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
                self.assertIn("Comment +1", self.visible(app))
                self.assertEqual(state_path.read_bytes(), before)
                self.assertNotIn("private path", self.notice(app))
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertNotIn("Comment", self.visible(app))
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
            row = self.issue_rows(app, "sprint")[0]
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

    async def test_new_clears_on_open_and_later_comment_remains_new(self):
        async with self.running() as (app, pilot):
            self.server.issues.append(issue(4))
            await self.refresh(app, pilot)
            await pilot.press("tab", "ctrl+home", "enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-4")
            self.assertNotIn("NEW", self.visible(app))
            self.server.issues[-1]["comments"].append(comment(41))
            await self.refresh(app, pilot)
            self.assertIn("DEMO-4 Comment +1", self.visible(app))
        async with self.running() as (app, pilot):
            self.assertNotIn("NEW", self.visible(app))
            self.assertIn("Comment +1", self.visible(app))

    async def test_instance_isolation_and_large_retry_after(self):
        async with self.running() as (app, pilot):
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

    async def test_check_command_success_and_failure_never_creates_state(self):
        import contextlib
        import io
        from jira_overview.__main__ import main
        def run_check():
            with patch("jira_overview.__main__.configuration", side_effect=lambda _: (
                    Jira(self.server.url, TOKEN, allow_local_http=True), self.state_dir, 60)), \
                    patch("sys.argv", ["jirawarrior", "--check", "--config", "synthetic.toml"]):
                return main()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = await asyncio.to_thread(run_check)
        self.assertEqual(result, 0)
        self.assertIn("GET-проверка успешна", output.getvalue())
        self.assertFalse(list(self.state_dir.iterdir()))
        self.server.status = 500
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            result = await asyncio.to_thread(run_check)
        self.assertEqual(result, 1)
        self.assertIn("HTTP 500", errors.getvalue())
        self.assertFalse(list(self.state_dir.iterdir()))

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

    def epic_fixture(self):
        self.server.issues = [issue(1, [{"id": 1}], epic_key="DEMO-100"),
                              issue(2, epic_key="DEMO-100"), issue(3),
                              issue(4, parent="DEMO-300"),
                              issue(100, [{"id": 1}], epic=True), issue(101, epic=True)]
        closed_epic = issue(200, epic=True, summary="[bold]Контекстный эпик[/bold]")
        closed_epic["fields"]["status"]["name"] = "Done"
        self.server.context_issues = [closed_epic, issue(300, epic_key="DEMO-200"), issue(999)]

    async def test_epic_snapshot_resolves_context_and_subtasks_without_observing_them(self):
        self.epic_fixture()
        async with self.running() as (app, pilot):
            self.assertIsNotNone(app.snapshot)
            by_key = {i.key: i for i in app.snapshot.issues}
            self.assertTrue(by_key["DEMO-100"].is_epic)
            self.assertTrue(by_key["DEMO-101"].tracked)
            self.assertEqual(by_key["DEMO-4"].epic_key, "DEMO-200")
            self.assertEqual(by_key["DEMO-200"].status, "Done")
            self.assertFalse(by_key["DEMO-200"].tracked)
            self.assertNotIn("DEMO-300", by_key)
            self.assertNotIn("DEMO-999", by_key)
            saved = json.loads(next(self.state_dir.glob("*.json")).read_text())
            self.assertEqual(set(saved["issues"]), {"1", "2", "3", "4", "100", "101"})
            paths = [path for _, path, _, _ in self.server.requests]
            self.assertNotIn("/rest/api/2/issue/200/comment", paths)
            self.assertNotIn("/rest/api/2/issue/300/comment", paths)
            self.assertTrue(all(method == "GET" for method, *_ in self.server.requests))

    async def test_epic_toggle_groups_across_sprints_preserves_selection_and_has_no_side_effects(self):
        self.epic_fixture()
        async with self.running(size=(45, 16)) as (app, pilot):
            self.assertEqual([r[0] for r in self.rows(app, "sprint")], ["DEMO-1"])
            self.assertEqual([r[0] for r in self.rows(app, "other")], ["DEMO-2", "DEMO-3", "DEMO-4"])
            saved = next(self.state_dir.glob("*.json")).read_bytes()
            requests = len(self.server.requests)
            await pilot.press("e")
            await pilot.pause()
            self.assertTrue(app.query_one("#epic-area").display)
            self.assertFalse(app.query_one("#sprint-area").display)
            self.assertFalse(app.query_one("#other-area").display)
            table = app.query_one("#epic", IssueTable)
            keys = [r[0].strip().split()[0] for r in self.rows(app, "epic")]
            self.assertEqual(keys, ["DEMO-100", "DEMO-1", "DEMO-2", "DEMO-101", "DEMO-200", "DEMO-4"])
            self.assertEqual(table._key_at(table.cursor_row), "1")
            self.assertIn("(0)", self.rows(app, "epic")[3][1])
            self.assertIn("[bold]Контекстный эпик[/bold]", str(self.rows(app, "epic")))
            await pilot.press("down", "e")
            await pilot.pause()
            self.assertEqual(app.focused.id, "other")
            self.assertEqual(app.focused._key_at(app.focused.cursor_row), "2")
            self.assertEqual(next(self.state_dir.glob("*.json")).read_bytes(), saved)
            self.assertEqual(len(self.server.requests), requests)
            await pilot.press("е")
            await pilot.resize_terminal(110, 32)
            await pilot.pause()
            self.assertEqual(app.focused.id, "epic")
            self.assertGreater(table.size.height, 0)
        async with self.running() as (app, pilot):
            self.assertFalse(app.query_one("#epic-area").display)
            self.assertEqual(app.focused.id, "sprint")

    async def test_epic_open_context_and_own_markers_and_children_order(self):
        self.epic_fixture()
        async with self.running() as (app, pilot):
            self.server.issues.extend([issue(102, epic=True), issue(5, epic_key="DEMO-100")])
            self.server.issues[0]["comments"].append(comment(19))
            await self.refresh(app, pilot)
            await pilot.press("e")
            await pilot.pause()
            table = app.query_one("#epic", IssueTable)
            keys = [r[0].strip() for r in self.rows(app, "epic")]
            self.assertEqual(keys[:4], ["DEMO-100", "DEMO-5 NEW", "DEMO-1 Comment +1", "DEMO-2"])
            self.assertIn("DEMO-102 NEW", keys)
            context_row = next(n for n in range(table.row_count) if table._key_at(n) == "200")
            before = next(self.state_dir.glob("*.json")).read_bytes()
            table.move_cursor(row=context_row)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-200")
            self.assertEqual(next(self.state_dir.glob("*.json")).read_bytes(), before)
            self.assertEqual(self.notice(app), "")
            own_row = next(n for n in range(table.row_count) if table._key_at(n) == "102")
            table.move_cursor(row=own_row)
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertNotIn("NEW", str(table.get_row_at(own_row)))
            self.assertEqual(table._key_at(table.cursor_row), "102")
            # Mouse opens the context epic too, but column headings never open it.
            await pilot.click("#epic", offset=(4, 1))
            await self.settled(app, pilot)
            opened = len(self.opened)
            table.scroll_to(y=0, animate=False)
            await pilot.pause()
            await pilot.click("#epic", offset=(4, context_row + 1))
            await self.settled(app, pilot)
            self.assertEqual(len(self.opened), opened + 1)
            self.assertEqual(self.opened[-1], self.server.url + "/browse/DEMO-200")

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

    async def test_epic_context_open_race_never_clears_a_later_observed_epic(self):
        self.epic_fixture()
        async with self.running() as (app, pilot):
            await pilot.press("e")
            await pilot.pause()
            table = app.query_one("#epic", IssueTable)
            table.move_cursor(row=next(n for n in range(table.row_count) if table._key_at(n) == "200"))
            self.browser_gate = asyncio.Event()
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(app.opening)
            context = self.server.context_issues.pop(0)
            self.server.issues.append(context)
            await pilot.press("r")
            for _ in range(300):
                await pilot.pause(0.01)
                if not app.refreshing:
                    break
            observed = next(item for item in app.session.view.items if item.issue.id == "200")
            self.assertTrue(observed.new)
            self.browser_gate.set()
            await self.settled(app, pilot)
            self.assertTrue(next(item for item in app.session.view.items if item.issue.id == "200").new)
            # A subsequent open captured as observed does clear the marker.
            await pilot.press("enter")
            await self.settled(app, pilot)
            self.assertFalse(next(item for item in app.session.view.items if item.issue.id == "200").new)

    async def test_epic_refresh_regroups_selected_ticket_and_empty_mode_is_navigable(self):
        async with self.running() as (app, pilot):
            await pilot.press("e", "down", "ctrl+end", "tab")
            await pilot.pause()
            table = app.query_one("#epic", IssueTable)
            self.assertEqual(table.row_count, 0)
            self.assertIn("нет эпиков", str(app.query_one("#epic-heading", Static).render()))
            await pilot.press("enter")
            self.assertEqual(self.opened, [])
            self.epic_fixture()
            await self.refresh(app, pilot)
            table.move_cursor(row=next(n for n in range(table.row_count) if table._key_at(n) == "2"))
            self.server.issues[1]["fields"]["customfield_789"] = "DEMO-200"
            await self.refresh(app, pilot)
            self.assertEqual(table._key_at(table.cursor_row), "2")
            preceding_epics = [table._key_at(n) for n in range(table.cursor_row)
                               if table.shown[table._key_at(n)].is_epic]
            self.assertEqual(preceding_epics[-1], "200")
            await pilot.press("ctrl+home")
            self.assertEqual(table._key_at(table.cursor_row), "100")
            await pilot.press("ctrl+end")
            self.assertEqual(table._key_at(table.cursor_row), "2")
            await pilot.press("pageup", "pagedown", "e", "tab")
            await pilot.pause()
            self.assertIn(app.focused.id, ("sprint", "other"))

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
            self.assertIsNotNone(app.snapshot)
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


if __name__ == "__main__":
    unittest.main()
