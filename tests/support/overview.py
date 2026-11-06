"""HTTP + Textual Pilot + real temporary state, with browser handoff replaced."""
import asyncio
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

from rich.color import Color
from rich.text import Text
from textual.widgets import Static

from jira_overview.app import IssueTable, Overview
from jira_overview.core import Jira

from .jira import TOKEN, Server, issue


class OverviewCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = Server()
        self.temp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp.name)
        self.opened = []
        self.browser_ok = True
        self.browser_gate: asyncio.Event | None = None

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.close)
        self.temp.cleanup()

    async def browser(self, url):
        self.opened.append(url)
        if self.browser_gate:
            await self.browser_gate.wait()
        return self.browser_ok

    def make_app(self, interval: float = 3600):
        return Overview(Jira(self.server.url, TOKEN, allow_local_http=True), self.state_dir,
                        interval=interval, browser=self.browser)

    @asynccontextmanager
    async def running(self, *, size=(110, 32), interval: float = 3600):
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
        key, summary, status, updated = table.get_row_at(issue_indices[row_index])
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

    def epic_fixture(self):
        self.server.issues = [issue(1, [{"id": 1}], epic_key="DEMO-100"),
                              issue(2, epic_key="DEMO-100"), issue(3),
                              issue(4, parent="DEMO-300"),
                              issue(100, [{"id": 1}], epic=True), issue(101, epic=True)]
        closed_epic = issue(200, epic=True, summary="[bold]Контекстный эпик[/bold]")
        closed_epic["fields"]["status"]["name"] = "Done"
        self.server.context_issues = [closed_epic, issue(300, epic_key="DEMO-200"), issue(999)]
