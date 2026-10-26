"""Sprint action through the session and real HTTP/Textual boundaries."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from textual.widgets import Input, OptionList

from jira_overview.app import Overview
from jira_overview.core import Jira, Sprint
from jira_overview.presentation import IssueTable
from jira_overview.session import ReviewSession
from test_overview import Server, TOKEN, comment, issue


class SprintTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = Server()
        self.server.sprint_post_status = 204
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.opened = []

    async def asyncTearDown(self):
        self.server.request_gate = False
        self.server.request_release.set()
        await asyncio.to_thread(self.server.close)

    async def browser(self, url):
        self.opened.append(url)
        return True

    def jira(self):
        return Jira(self.server.url, TOKEN, allow_local_http=True)

    def session(self):
        session = ReviewSession(self.jira(), Path(self.temp.name), 3600, self.browser)
        self.addAsyncCleanup(session.aclose)
        return session

    def app(self):
        return Overview(self.jira(), Path(self.temp.name), browser=self.browser)

    async def wait_until(self, condition):
        async with asyncio.timeout(5):
            while not condition():
                await asyncio.sleep(0.01)

    @property
    def posts(self):
        return [entry for entry in self.server.requests if entry[0] == "POST"]

    async def test_session_adds_then_refreshes_without_acknowledging_markers(self):
        session = self.session()
        await session.start()
        await self.wait_until(lambda: not session.view.refreshing)
        self.assertEqual(session.view.snapshot.active_sprints, (Sprint("1", "Sprint 1"),))
        self.server.issues.append(issue(4))
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        self.server.issues[-1]["comments"].append(comment(41))
        session.refresh()
        await self.wait_until(lambda: not session.view.refreshing)
        shown = next(item for item in session.view.items if item.issue.id == "4")
        self.assertTrue(shown.new)
        self.assertEqual(shown.unread_comments, 1)
        session.add_to_sprint(shown.issue)
        await self.wait_until(lambda: not session.view.sprint_busy)
        added = next(item for item in session.view.items if item.issue.id == "4")
        self.assertEqual(added.issue.sprints, ("Sprint 1 (#1)",))
        self.assertTrue(added.new)
        self.assertEqual(added.unread_comments, 1)
        self.assertIn("подтверждено", session.view.sprint_notice)
        self.assertEqual(self.posts[0][2], {"issues": ["4"]})
        self.assertEqual(self.opened, [])

    async def test_session_chooses_explicit_target_and_cancel_is_read_only(self):
        self.server.issues.append(issue(5, [{"id": 2}]))
        session = self.session()
        await session.start()
        await self.wait_until(lambda: not session.view.refreshing)
        shown = next(item.issue for item in session.view.items if item.issue.id == "2")
        requests = len(self.server.requests)
        session.add_to_sprint(shown)
        self.assertEqual(session.view.sprint_issue, shown)
        self.assertEqual(session.view.sprint_choices, (Sprint("1", "Sprint 1"), Sprint("2", "Sprint 2")))
        self.assertEqual(len(self.server.requests), requests)
        session.cancel_sprint()
        self.assertEqual(session.view.sprint_choices, ())
        self.assertIsNone(session.view.sprint_issue)
        self.assertEqual(self.posts, [])
        session.add_to_sprint(shown, Sprint("999", "Not in overview"))
        self.assertEqual(self.posts, [])
        session.add_to_sprint(shown)
        session.add_to_sprint(shown, Sprint("2", "Sprint 2"))
        await self.wait_until(lambda: not session.view.sprint_busy)
        self.assertEqual(self.posts[0][1], "/rest/agile/1.0/sprint/2/issue")
        self.assertEqual(session.view.sprint_choices, ())

    async def test_a_adds_selected_issue_and_keeps_id_when_it_moves_between_tables(self):
        app = self.app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.wait_until(lambda: app.snapshot is not None)
            await pilot.pause()
            await pilot.press("tab")
            self.assertEqual(app.focused.id, "other")
            await pilot.press("a")
            await self.wait_until(lambda: bool(self.posts) and not app.session.view.sprint_busy)
            await pilot.pause()
            self.assertEqual(app.focused.id, "sprint")
            table = app.query_one("#sprint", IssueTable)
            self.assertEqual(table.shown[table._key_at(table.cursor_row)].id, "2")
            self.assertEqual(self.posts[0][2], {"issues": ["2"]})
            await pilot.press("a")
            await self.wait_until(lambda: not app.session.view.sprint_busy)
            self.assertEqual(len(self.posts), 1)
            self.assertIn("уже", app.session.view.sprint_notice)
            self.assertEqual(self.opened, [])

    async def test_multiple_sprints_chooser_uses_full_unfiltered_overview_and_cancels(self):
        self.server.issues.append(issue(5, [{"id": 2}], summary="Hidden sprint source"))
        self.server.issues[1]["fields"]["summary"] = "Unique target"
        app = self.app()
        async with app.run_test(size=(80, 24)) as pilot:
            await self.wait_until(lambda: app.snapshot is not None)
            await pilot.press("/", "U", "n", "i", "q", "u", "e", "enter")
            self.assertEqual(app.focused.id, "other")
            await pilot.press("a")
            await pilot.pause()
            choices = app.screen.query_one("#sprint-choices", OptionList)
            self.assertEqual(choices.option_count, 2)
            self.assertEqual(self.posts, [])
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(app.focused.id, "other")
            self.assertEqual(self.posts, [])
            await pilot.press("a")
            await pilot.pause()
            # The default is Cancel; Tab explicitly enters the sprint list.
            await pilot.press("tab", "down", "enter")
            await self.wait_until(lambda: bool(self.posts) and not app.session.view.sprint_busy)
            await pilot.pause()
            self.assertEqual(self.posts[0][1], "/rest/agile/1.0/sprint/2/issue")
            table = app.query_one("#sprint", IssueTable)
            self.assertEqual(table.shown[table._key_at(table.cursor_row)].id, "2")
            self.assertEqual(app.query_one("#summary-filter", Input).value, "Unique")

    async def test_denial_and_refresh_failure_keep_last_snapshot(self):
        session = self.session()
        await session.start()
        await self.wait_until(lambda: not session.view.refreshing)
        before = session.view.snapshot
        shown = next(item.issue for item in session.view.items if item.issue.id == "2")
        self.server.sprint_post_status = 403
        session.add_to_sprint(shown)
        await self.wait_until(lambda: not session.view.sprint_busy)
        self.assertIn("403", session.view.sprint_notice)
        self.assertIs(session.view.snapshot, before)
        self.server.sprint_post_status = 204
        self.server.sprint_post_fail_refresh = True
        session.add_to_sprint(shown)
        await self.wait_until(lambda: not session.view.sprint_busy)
        self.assertIn("подтверждено", session.view.sprint_notice)
        self.assertIn("403", session.view.refresh_error)
        self.assertIs(session.view.snapshot, before)
        self.assertEqual(len(self.posts), 2)

    async def test_session_serializes_write_refresh_and_exit(self):
        session = self.session()
        await session.start()
        await self.wait_until(lambda: not session.view.refreshing)
        shown = next(item.issue for item in session.view.items if item.issue.id == "2")
        self.server.request_started.clear()
        self.server.request_gate = True
        session.add_to_sprint(shown)
        self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 2))
        count = len(self.server.requests)
        session.add_to_sprint(shown)
        session.refresh()
        self.assertEqual(len(self.server.requests), count)
        self.server.request_gate = False
        self.server.request_release.set()
        await self.wait_until(lambda: not session.view.sprint_busy)
        self.assertEqual(len(self.posts), 1)
        self.server.request_started.clear()
        self.server.request_release.clear()
        self.server.request_gate = True
        session.add_to_sprint(shown)
        self.assertTrue(await asyncio.to_thread(self.server.request_started.wait, 2))
        await asyncio.wait_for(session.aclose(), 2)
        self.assertTrue(session.view.closed)
        self.assertFalse(session.view.sprint_busy)
        self.assertEqual(len(self.posts), 1)
        self.server.request_release.set()

    async def test_no_active_sprint_has_message_and_no_post(self):
        self.server.sprint_states[1] = "closed"
        app = self.app()
        async with app.run_test(size=(80, 24)) as pilot:
            await self.wait_until(lambda: app.snapshot is not None)
            app.query_one("#other", IssueTable).focus()
            await pilot.press("a")
            self.assertIn("нет активных", app.session.view.sprint_notice)
            self.assertEqual(self.posts, [])

    async def test_epic_child_is_eligible_but_epic_and_subtask_are_not(self):
        self.server.issues = [issue(90, epic=True), issue(2, epic_key="DEMO-90"),
                              issue(4, parent="DEMO-2"), issue(1, [{"id": 1}])]
        app = self.app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.wait_until(lambda: app.snapshot is not None)
            await pilot.press("e", "a")
            self.assertEqual(self.posts, [])
            self.assertIn("Эпики и подзадачи", app.session.view.sprint_notice)
            await pilot.press("down", "a")
            await self.wait_until(lambda: bool(self.posts) and not app.session.view.sprint_busy)
            await pilot.pause()
            table = app.query_one("#epic", IssueTable)
            self.assertEqual(table.shown[table._key_at(table.cursor_row)].id, "2")
            await pilot.press("down", "a")
            self.assertEqual(len(self.posts), 1)
            self.assertIn("Эпики и подзадачи", app.session.view.sprint_notice)
            self.assertEqual(self.opened, [])

    async def test_a_is_filter_text_and_is_inert_in_sidebars(self):
        app = self.app()
        async with app.run_test(size=(80, 24)) as pilot:
            await self.wait_until(lambda: app.snapshot is not None)
            await pilot.press("/")
            requests = len(self.server.requests)
            await pilot.press("a")
            self.assertEqual(app.query_one("#summary-filter", Input).value, "a")
            self.assertEqual(len(self.server.requests), requests)
            await pilot.press("escape", "t", "a", "escape", "s", "a", "escape")
            self.assertEqual(self.posts, [])
            self.assertEqual(self.opened, [])

    async def test_chooser_defaults_to_cancel_and_fits_small_terminal(self):
        self.server.issues.append(issue(5, [{"id": 2}]))
        app = self.app()
        async with app.run_test(size=(45, 16)) as pilot:
            await self.wait_until(lambda: app.snapshot is not None)
            app.query_one("#other", IssueTable).focus()
            await pilot.press("a")
            await pilot.pause()
            self.assertEqual(app.focused.id, "cancel-sprint")
            await pilot.press("enter")
            await pilot.pause()
            self.assertFalse(app.session.view.sprint_choices)
            self.assertEqual(self.posts, [])
            self.assertEqual(app.focused.id, "other")


if __name__ == "__main__":
    unittest.main()
