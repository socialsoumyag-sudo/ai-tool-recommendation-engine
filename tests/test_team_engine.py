"""
test_team_engine.py

Tests the team consolidation math ONLY -- best-of-breed totals, single-suite
selection, complementary-pair brute force, and platform bonus/filter
behavior. No LLM assertions, same philosophy as test_scoring_engine.py.

Run with: python tests/test_team_engine.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rules_engine.team_engine import RoleTask, analyze_team
from rules_engine.tool_registry import ToolEntry
from rules_engine.task_taxonomy import FACTORS


class FakeRegistry:
    def __init__(self, entries):
        self._entries = entries

    def entries_for_task(self, task_id):
        return [e for e in self._entries if e.task == task_id]


def flat_scores(value):
    return {f: value for f in FACTORS}


class TestBestOfBreed(unittest.TestCase):
    def setUp(self):
        # Two tasks. ToolA dominates task1, ToolB dominates task2.
        self.entries = [
            ToolEntry(tool="ToolA", task="task1", scores=flat_scores(9),
                      last_verified="2026-07-01", source_notes="", vendor="VendorX"),
            ToolEntry(tool="ToolB", task="task1", scores=flat_scores(3),
                      last_verified="2026-07-01", source_notes="", vendor="VendorY"),
            ToolEntry(tool="ToolA", task="task2", scores=flat_scores(2),
                      last_verified="2026-07-01", source_notes="", vendor="VendorX"),
            ToolEntry(tool="ToolB", task="task2", scores=flat_scores(9),
                      last_verified="2026-07-01", source_notes="", vendor="VendorY"),
        ]
        self.registry = FakeRegistry(self.entries)
        self.role_tasks = [
            RoleTask(role_label="Role1", task_id="task1", task_label="Task 1",
                      weights={f: 1 for f in FACTORS}),
            RoleTask(role_label="Role2", task_id="task2", task_label="Task 2",
                      weights={f: 1 for f in FACTORS}),
        ]

    def test_best_of_breed_picks_specialist_per_task(self):
        result = analyze_team(self.role_tasks, self.registry)
        winners = {tc.task_id: tc.best_of_breed.tool for tc in result.best_of_breed_breakdown}
        self.assertEqual(winners["task1"], "ToolA")
        self.assertEqual(winners["task2"], "ToolB")

    def test_best_of_breed_total_is_sum_of_specialists(self):
        result = analyze_team(self.role_tasks, self.registry)
        # both specialists score 9.0 on their task -> total should be ~18.0
        self.assertAlmostEqual(result.best_of_breed_total, 18.0, delta=0.1)

    def test_single_suite_never_exceeds_best_of_breed(self):
        result = analyze_team(self.role_tasks, self.registry)
        self.assertLessEqual(
            result.single_suite.total_weighted_score, result.best_of_breed_total + 0.01
        )

    def test_single_suite_coverage_pct_bounded(self):
        result = analyze_team(self.role_tasks, self.registry)
        self.assertGreaterEqual(result.single_suite.coverage_pct, 0)
        self.assertLessEqual(result.single_suite.coverage_pct, 100)

    def test_complementary_pair_recovers_full_coverage_when_specialists_split(self):
        # Since ToolA and ToolB are perfect complements (each dominates one
        # task), the best pair should recover ~100% of best-of-breed.
        result = analyze_team(self.role_tasks, self.registry)
        self.assertGreaterEqual(result.complementary_pair.coverage_pct, 99.0)
        self.assertEqual(set(result.complementary_pair.tools), {"ToolA", "ToolB"})

    def test_complementary_pair_at_least_as_good_as_single_suite(self):
        result = analyze_team(self.role_tasks, self.registry)
        self.assertGreaterEqual(
            result.complementary_pair.total_weighted_score,
            result.single_suite.total_weighted_score - 0.01,
        )


class TestPlatformBonus(unittest.TestCase):
    def setUp(self):
        self.entries = [
            ToolEntry(tool="IncumbentTool", task="task1", scores=flat_scores(5),
                      last_verified="2026-07-01", source_notes="", vendor="Google"),
            ToolEntry(tool="ChallengerTool", task="task1", scores=flat_scores(5.5),
                      last_verified="2026-07-01", source_notes="", vendor="OpenAI"),
        ]
        self.registry = FakeRegistry(self.entries)
        self.role_tasks = [
            RoleTask(role_label="Role1", task_id="task1", task_label="Task 1",
                      weights={f: 1 for f in FACTORS}),
        ]

    def test_without_platform_bonus_challenger_wins(self):
        result = analyze_team(self.role_tasks, self.registry)
        self.assertEqual(result.best_of_breed_breakdown[0].best_of_breed.tool, "ChallengerTool")

    def test_platform_bonus_can_flip_the_winner(self):
        # 0.5 point gap, default bonus is 0.75 -- should flip to incumbent
        result = analyze_team(
            self.role_tasks, self.registry, existing_vendors=["Google"]
        )
        self.assertEqual(result.best_of_breed_breakdown[0].best_of_breed.tool, "IncumbentTool")

    def test_allowed_vendors_only_filters_out_others(self):
        result = analyze_team(
            self.role_tasks, self.registry,
            existing_vendors=["Google"], allowed_vendors_only=True,
        )
        # ChallengerTool (OpenAI) should be filtered out entirely
        self.assertEqual(result.best_of_breed_breakdown[0].best_of_breed.tool, "IncumbentTool")
        self.assertIsNone(result.complementary_pair)  # only 1 tool left, no pair possible


class TestEmptyAndEdgeCases(unittest.TestCase):
    def test_no_role_tasks_returns_zero_total(self):
        result = analyze_team([], FakeRegistry([]))
        self.assertEqual(result.best_of_breed_total, 0.0)
        self.assertIsNone(result.single_suite)
        self.assertIsNone(result.complementary_pair)

    def test_task_with_no_registry_data_contributes_zero(self):
        role_tasks = [
            RoleTask(role_label="Role1", task_id="ghost_task", task_label="Ghost",
                      weights={f: 1 for f in FACTORS}),
        ]
        result = analyze_team(role_tasks, FakeRegistry([]))
        self.assertEqual(result.best_of_breed_total, 0.0)

    def test_importance_weighting_scales_contribution(self):
        entries = [
            ToolEntry(tool="OnlyTool", task="task1", scores=flat_scores(4),
                      last_verified="2026-07-01", source_notes="", vendor="X"),
        ]
        registry = FakeRegistry(entries)
        role_tasks = [
            RoleTask(role_label="Role1", task_id="task1", task_label="Task 1",
                      weights={f: 1 for f in FACTORS}, importance=3.0),
        ]
        result = analyze_team(role_tasks, registry)
        self.assertAlmostEqual(result.best_of_breed_total, 12.0, delta=0.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
