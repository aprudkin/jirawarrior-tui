"""Immutable review items for pure plan and widget contract tests."""

from jira_overview.core import Issue
from jira_overview.session import ReviewItem


def review_item(number: int, *, status="In Progress", sprint=False, new=False,
                comments=0, epic=False, epic_key=None, tracked=True, summary=None, updated=None,
                parent_key=None):
    issue = Issue(
        id=str(number), key=f"DEMO-{number}", summary=summary or f"Task {number}",
        status=status, sprints=("DEMO-2026-W43 (#1)",) if sprint else (),
        comments=frozenset(), foreign_comments=frozenset(), is_epic=epic,
        epic_key=epic_key, tracked=tracked, updated=updated,
        parent_key=parent_key, is_subtask=parent_key is not None,
    )
    return ReviewItem(issue, new, comments)
