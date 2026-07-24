#!/usr/bin/env python3
"""
test_blinding.py — unit tests for blinding.py

Coverage: determinism/reproducibility, balanced-but-not-fixed assignment,
and the token<->variant inverse lookups used throughout grade/aggregate.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from blinding import (  # noqa: E402
    TOKENS,
    VARIANT_NAMES,
    assign_token_map,
    token_for_variant,
    variant_for_token,
)


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_give_same_map(self):
        a = assign_token_map(42, "exp-1", "task-1", "model-a", 0)
        b = assign_token_map(42, "exp-1", "task-1", "model-a", 0)
        self.assertEqual(a, b)

    def test_map_always_has_both_tokens(self):
        m = assign_token_map(1, "exp", "case", "model", 0)
        self.assertEqual(set(m.keys()), set(TOKENS))

    def test_map_never_assigns_same_variant_twice(self):
        for rep in range(20):
            m = assign_token_map(1, "exp", "case", "model", rep)
            self.assertEqual(set(m.values()), set(VARIANT_NAMES))
            self.assertNotEqual(m["A"], m["B"])

    def test_different_case_id_can_change_assignment(self):
        maps = {
            assign_token_map(7, "exp", f"case-{i}", "model", 0)["A"] for i in range(50)
        }
        # With 50 samples we expect to see BOTH variants show up in the "A" slot;
        # a buggy implementation that always assigns baseline->A would fail this.
        self.assertEqual(maps, set(VARIANT_NAMES))

    def test_different_repetition_can_change_assignment(self):
        maps = {assign_token_map(7, "exp", "case", "model", rep)["A"] for rep in range(50)}
        self.assertEqual(maps, set(VARIANT_NAMES))

    def test_different_seed_changes_overall_pattern(self):
        combos = [(f"case-{i}", f"model-{i % 3}", i % 4) for i in range(30)]
        pattern_1 = [assign_token_map(1, "exp", c, m, r)["A"] for c, m, r in combos]
        pattern_2 = [assign_token_map(2, "exp", c, m, r)["A"] for c, m, r in combos]
        self.assertNotEqual(pattern_1, pattern_2)

    def test_different_experiment_id_changes_assignment_space(self):
        combos = [(f"case-{i}", f"model-{i % 3}", i % 4) for i in range(30)]
        pattern_1 = [assign_token_map(9, "exp-a", c, m, r)["A"] for c, m, r in combos]
        pattern_2 = [assign_token_map(9, "exp-b", c, m, r)["A"] for c, m, r in combos]
        self.assertNotEqual(pattern_1, pattern_2)


class TestBalance(unittest.TestCase):
    def test_assignment_is_roughly_balanced_over_many_samples(self):
        # Not a fixed A=baseline rule: over enough samples, roughly half should
        # assign baseline to "A". Loose bounds to avoid flakiness.
        n = 400
        baseline_as_a = sum(
            1
            for i in range(n)
            if assign_token_map(3, "exp", f"case-{i}", "model-x", 0)["A"] == "baseline"
        )
        fraction = baseline_as_a / n
        self.assertGreater(fraction, 0.35)
        self.assertLess(fraction, 0.65)


class TestInverseLookups(unittest.TestCase):
    def setUp(self):
        self.token_map = {"A": "candidate", "B": "baseline"}

    def test_token_for_variant(self):
        self.assertEqual(token_for_variant(self.token_map, "candidate"), "A")
        self.assertEqual(token_for_variant(self.token_map, "baseline"), "B")

    def test_variant_for_token(self):
        self.assertEqual(variant_for_token(self.token_map, "A"), "candidate")
        self.assertEqual(variant_for_token(self.token_map, "B"), "baseline")

    def test_token_for_unknown_variant_raises(self):
        with self.assertRaises(KeyError):
            token_for_variant(self.token_map, "nonexistent")

    def test_variant_for_unknown_token_raises(self):
        with self.assertRaises(KeyError):
            variant_for_token(self.token_map, "C")


if __name__ == "__main__":
    unittest.main()
