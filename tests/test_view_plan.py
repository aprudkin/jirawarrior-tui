"""Pure grouping, ordering, filtering and measurement; no TUI event loop."""

import unittest
from datetime import UTC, datetime

from rich.text import Text
from support.items import review_item

from jira_overview.view_plan import build_plan


class ViewPlanTests(unittest.TestCase):
    def test_families_stay_contiguous_and_sort_only_by_parent_in_all_views(self):
        old = datetime(2020, 1, 1, tzinfo=UTC)
        recent = datetime(2026, 1, 1, tzinfo=UTC)
        for sprint in (True, False):
            items = (
                review_item(100, epic=True, tracked=False),
                review_item(1, sprint=sprint, epic_key="DEMO-100", status="Backlog", new=True),
                review_item(2, sprint=sprint, epic_key="DEMO-100", status="Open", comments=1),
                review_item(3, sprint=sprint, epic_key="DEMO-100", updated=old),
                review_item(4, sprint=sprint, epic_key="DEMO-100", status="Open"),
                review_item(11, sprint=sprint, epic_key="DEMO-100", parent_key="DEMO-1",
                            status="Backlog", new=True),
                review_item(14, sprint=sprint, epic_key="DEMO-100", parent_key="DEMO-1",
                            status="Backlog", new=True, updated=old),
                review_item(12, sprint=sprint, epic_key="DEMO-100", parent_key="DEMO-1", comments=2),
                review_item(13, sprint=sprint, epic_key="DEMO-100", parent_key="DEMO-1",
                            status="Open", updated=recent),
                review_item(31, sprint=sprint, epic_key="DEMO-100", parent_key="DEMO-3",
                            new=True, updated=recent),
            )
            table = build_plan(items).tables[0 if sprint else 1]
            roots = ["DEMO-3", "└─ DEMO-31 NEW", "DEMO-4"] if sprint else [
                "DEMO-4", "DEMO-3", "└─ DEMO-31 NEW"]
            self.assertEqual([cells[0].plain for _, cells in table.rows], [
                "DEMO-1 NEW", "├─ DEMO-14 NEW", "├─ DEMO-11 NEW", "├─ DEMO-12 Comment +2",
                "└─ DEMO-13", "DEMO-2 Comment +1", *roots,
            ])
            epic = build_plan(items, epic_mode=True).tables[0]
            self.assertEqual([cells[0].plain for _, cells in epic.rows], [
                "DEMO-100", "├─ DEMO-1 NEW", "│  ├─ DEMO-14 NEW", "│  ├─ DEMO-11 NEW",
                "│  ├─ DEMO-12 Comment +2", "│  └─ DEMO-13", "├─ DEMO-2 Comment +1",
                "├─ DEMO-3", "│  └─ DEMO-31 NEW", "└─ DEMO-4",
            ])
            self.assertEqual(epic.rows[0][1][1].plain, "Task 100 (9)")

    def test_tree_branches_stop_at_roots_and_epics_in_both_areas(self):
        for sprint in (True, False):
            items = (
                review_item(100, epic=True, tracked=False),
                review_item(200, epic=True, tracked=False),
                review_item(300, epic=True),
                review_item(10, sprint=sprint, epic_key="DEMO-100"),
                review_item(11, sprint=sprint, epic_key="DEMO-100", parent_key="DEMO-10"),
                review_item(12, sprint=sprint, epic_key="DEMO-100", parent_key="DEMO-10"),
                review_item(20, sprint=sprint, epic_key="DEMO-100"),
                review_item(21, sprint=sprint, epic_key="DEMO-100", parent_key="DEMO-20"),
                review_item(30, sprint=sprint, epic_key="DEMO-200"),
                review_item(31, sprint=sprint, epic_key="DEMO-200", parent_key="DEMO-30"),
            )
            table = build_plan(items).tables[0 if sprint else 1]
            self.assertEqual([cells[0].plain for _, cells in table.rows], [
                "DEMO-10", "├─ DEMO-11", "└─ DEMO-12", "DEMO-20", "└─ DEMO-21",
                "DEMO-30", "└─ DEMO-31",
            ])
            epic = build_plan(items, epic_mode=True).tables[0]
            self.assertEqual([cells[0].plain for _, cells in epic.rows], [
                "DEMO-100", "├─ DEMO-10", "│  ├─ DEMO-11", "│  └─ DEMO-12",
                "└─ DEMO-20", "   └─ DEMO-21", "DEMO-200", "└─ DEMO-30",
                "   └─ DEMO-31", "DEMO-300",
            ])

    def test_filter_retains_only_context_and_counts_matching_own_issues(self):
        items = (
            review_item(100, epic=True, tracked=False, summary="Epic"),
            review_item(10, epic_key="DEMO-100", new=True, comments=2),
            review_item(11, epic_key="DEMO-100", parent_key="DEMO-10", summary="Straße"),
            review_item(12, epic_key="DEMO-100", parent_key="DEMO-10"),
        )
        for epic_mode in (False, True):
            plan = build_plan(items, epic_mode=epic_mode, query="STRASSE")
            table = plan.tables[0 if epic_mode else 1]
            self.assertEqual([issue.id for issue, _ in table.rows],
                             ["100", "10", "11"] if epic_mode else ["10", "11"])
            parent, cells = table.rows[-2]
            self.assertFalse(parent.tracked)
            self.assertNotIn("NEW", cells[0].plain)
            self.assertNotIn("Comment", cells[0].plain)
            self.assertIn("(1)", table.heading)
            self.assertIs(table.rows[-1][0], items[2].issue)
            self.assertIn("└─ DEMO-11", table.rows[-1][1][0].plain)
        self.assertEqual(items[1].new, True)
        self.assertTrue(items[1].issue.tracked)
        empty = build_plan(items, query="no match")
        self.assertTrue(all(not table.rows and "нет совпадений" in table.heading for table in empty.tables))

    def test_widths_measure_final_connectors_markers_unicode_and_only_visible_areas(self):
        items = (review_item(100, epic=True, summary="Hidden" * 100),
                 review_item(1, sprint=True, new=True, comments=2, summary="界界e\u0301"),
                 review_item(123456, parent_key="DEMO-1", summary="short"))
        plan = build_plan(items)
        self.assertEqual(plan.column_widths[0], Text("DEMO-1 NEW Comment +2").cell_len)
        self.assertEqual(plan.column_widths[1], max(Text("Название").cell_len, Text("界界e\u0301").cell_len, 5))
        self.assertEqual(plan.tables[0].heading, "Текущий спринт (1) — 43-я неделя")
        self.assertEqual(plan.tables[1].rows[1][1][0].plain, "└─ DEMO-123456")
        self.assertGreater(build_plan(items, epic_mode=True).column_widths[1], plan.column_widths[1])
        self.assertLess(build_plan(()).column_widths[0], plan.column_widths[0])


if __name__ == "__main__":
    unittest.main()
