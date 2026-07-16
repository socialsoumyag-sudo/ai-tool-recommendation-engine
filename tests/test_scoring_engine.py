"""
test_scoring_engine.py

Tests ONLY the deterministic logic: weight normalization, weighted-score
math, and ranking order. Deliberately does NOT test explainer_agent or
refresh_agent output, since asserting on non-deterministic LLM text
would be a brittle, false signal -- same testing philosophy as the two
sibling projects this one extends.

Run with: python tests/test_scoring_engine.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rules_engine.scoring_engine import (
    normalize_weights,
    score_entry,
    rank_tools,
    dominant_factor,
    weakest_factor,
)
from rules_engine.tool_registry import ToolEntry, ToolRegistry
from rules_engine.task_taxonomy import FACTORS


class FakeRegistry:
    """In-memory stand-in for ToolRegistry so tests don't depend on the
    live JSON file changing underneath them.
    """
    def __init__(self, entries):
        self._entries = entries

    def entries_for_task(self, task_id):
        return [e for e in self._entries if e.task == task_id]


class TestNormalizeWeights(unittest.TestCase):
    def test_normalizes_to_sum_one(self):
        weights = {f: 5 for f in FACTORS}
        result = normalize_weights(weights)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=6)

    def test_all_zero_falls_back_to_equal(self):
        weights = {f: 0 for f in FACTORS}
        result = normalize_weights(weights)
        expected = 1.0 / len(FACTORS)
        for f in FACTORS:
            self.assertAlmostEqual(result[f], expected, places=6)

    def test_negative_weights_clamped_to_zero(self):
        weights = {f: -5 for f in FACTORS}
        result = normalize_weights(weights)
        # should fall back to equal weighting, not go negative
        for v in result.values():
            self.assertGreaterEqual(v, 0)

    def test_missing_factor_defaults_to_zero_weight(self):
        weights = {"accuracy": 10}  # everything else missing
        result = normalize_weights(weights)
        self.assertAlmostEqual(result["accuracy"], 1.0, places=6)
        for f in FACTORS:
            if f != "accuracy":
                self.assertAlmostEqual(result[f], 0.0, places=6)


class TestScoreEntry(unittest.TestCase):
    def test_equal_weights_averages_all_factors(self):
        entry = ToolEntry(
            tool="TestTool", task="test_task",
            scores={f: 8 for f in FACTORS},
            last_verified="2026-07-01", source_notes="",
        )
        weights = normalize_weights({f: 1 for f in FACTORS})
        self.assertAlmostEqual(score_entry(entry, weights), 8.0, places=1)

    def test_single_factor_weight_isolates_that_score(self):
        scores = {f: 5 for f in FACTORS}
        scores["accuracy"] = 10
        entry = ToolEntry(
            tool="TestTool", task="test_task", scores=scores,
            last_verified="2026-07-01", source_notes="",
        )
        weights = normalize_weights({"accuracy": 1})  # only accuracy matters
        self.assertAlmostEqual(score_entry(entry, weights), 10.0, places=1)

    def test_missing_score_treated_as_zero(self):
        entry = ToolEntry(
            tool="TestTool", task="test_task", scores={},
            last_verified="2026-07-01", source_notes="",
        )
        weights = normalize_weights({f: 1 for f in FACTORS})
        self.assertAlmostEqual(score_entry(entry, weights), 0.0, places=1)


class TestRankTools(unittest.TestCase):
    def setUp(self):
        self.entries = [
            ToolEntry(
                tool="HighTool", task="demo_task",
                scores={f: 9 for f in FACTORS},
                last_verified="2026-07-01", source_notes="",
            ),
            ToolEntry(
                tool="LowTool", task="demo_task",
                scores={f: 3 for f in FACTORS},
                last_verified="2026-07-01", source_notes="",
            ),
            ToolEntry(
                tool="MidTool", task="demo_task",
                scores={f: 6 for f in FACTORS},
                last_verified="2020-01-01",  # deliberately stale
                source_notes="",
            ),
        ]
        self.registry = FakeRegistry(self.entries)

    def test_ranks_best_first(self):
        result = rank_tools("demo_task", {f: 1 for f in FACTORS}, self.registry)
        tool_order = [t.tool for t in result.ranked_tools]
        self.assertEqual(tool_order, ["HighTool", "MidTool", "LowTool"])

    def test_stale_count_detected(self):
        result = rank_tools("demo_task", {f: 1 for f in FACTORS}, self.registry)
        self.assertEqual(result.stale_count, 1)
        self.assertEqual(result.total_count, 3)

    def test_runner_up_gap_computed(self):
        result = rank_tools("demo_task", {f: 1 for f in FACTORS}, self.registry)
        self.assertIsNotNone(result.winner.runner_up_gap)
        self.assertGreater(result.winner.runner_up_gap, 0)

    def test_empty_task_returns_empty_ranking(self):
        result = rank_tools("nonexistent_task", {f: 1 for f in FACTORS}, self.registry)
        self.assertEqual(result.total_count, 0)
        self.assertIsNone(result.winner)

    def test_reweighting_changes_winner(self):
        # Construct a case where LowTool wins ONLY on accuracy
        entries = [
            ToolEntry(
                tool="AccuracyWinner", task="t2",
                scores={"accuracy": 10, "cost": 1, "speed": 1, "privacy": 1,
                        "ecosystem": 1, "context": 1, "ease": 1},
                last_verified="2026-07-01", source_notes="",
            ),
            ToolEntry(
                tool="CostWinner", task="t2",
                scores={"accuracy": 1, "cost": 10, "speed": 1, "privacy": 1,
                        "ecosystem": 1, "context": 1, "ease": 1},
                last_verified="2026-07-01", source_notes="",
            ),
        ]
        registry = FakeRegistry(entries)

        accuracy_focused = rank_tools("t2", {"accuracy": 10}, registry)
        cost_focused = rank_tools("t2", {"cost": 10}, registry)

        self.assertEqual(accuracy_focused.winner.tool, "AccuracyWinner")
        self.assertEqual(cost_focused.winner.tool, "CostWinner")


class TestDominantAndWeakestFactor(unittest.TestCase):
    def test_dominant_factor_matches_highest_contribution(self):
        from rules_engine.scoring_engine import ScoredTool
        scored = ScoredTool(
            tool="X", weighted_score=5.0,
            factor_scores={"accuracy": 10, "cost": 2, "speed": 2, "privacy": 2,
                            "ecosystem": 2, "context": 2, "ease": 2},
            last_verified="2026-07-01", is_stale=False, source_notes="",
        )
        weights = normalize_weights({f: 1 for f in FACTORS})
        self.assertEqual(dominant_factor(scored, weights), "accuracy")

    def test_weakest_factor_matches_lowest_raw_score(self):
        from rules_engine.scoring_engine import ScoredTool
        scored = ScoredTool(
            tool="X", weighted_score=5.0,
            factor_scores={"accuracy": 10, "cost": 1, "speed": 5, "privacy": 5,
                            "ecosystem": 5, "context": 5, "ease": 5},
            last_verified="2026-07-01", is_stale=False, source_notes="",
        )
        self.assertEqual(weakest_factor(scored), "cost")


class TestToolEntryStaleness(unittest.TestCase):
    def test_recent_date_not_stale(self):
        import datetime
        today = datetime.date.today().isoformat()
        entry = ToolEntry(
            tool="X", task="y", scores={}, last_verified=today, source_notes="",
        )
        self.assertFalse(entry.is_stale())

    def test_old_date_is_stale(self):
        entry = ToolEntry(
            tool="X", task="y", scores={}, last_verified="2020-01-01", source_notes="",
        )
        self.assertTrue(entry.is_stale())

    def test_malformed_date_treated_as_stale(self):
        entry = ToolEntry(
            tool="X", task="y", scores={}, last_verified="not-a-date", source_notes="",
        )
        self.assertTrue(entry.is_stale())


if __name__ == "__main__":
    unittest.main(verbosity=2)
