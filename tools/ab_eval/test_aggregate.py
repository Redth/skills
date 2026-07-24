#!/usr/bin/env python3
"""test_aggregate.py — unit tests for aggregate.py (de-blinding, pass rates, PRF1, gates)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from aggregate import (  # noqa: E402
    deblind_graded_records,
    deblind_preferences,
    evaluate_acceptance_gates,
    evaluate_gate_max_deterministic_violations,
    evaluate_gate_metric_reduction,
    evaluate_gate_trigger_no_regression,
    pair_key,
    paired_deltas,
    preference_win_rates,
    summarize_metric_deltas,
    trigger_confusion_matrix,
    variant_pass_rates,
)


def _rec(case_id, model, rep, token, **overrides):
    base = {
        "case_id": case_id,
        "model_label": model,
        "repetition": rep,
        "variant_token": token,
        "deterministic_pass": True,
        "deterministic_violations": [],
        "should_trigger": None,
        "trigger_decision": None,
        "semantic_pass_rate": None,
        "metrics": {},
    }
    base.update(overrides)
    return base


def _token_maps_all_a_is_baseline(records):
    return {pair_key(r): {"A": "baseline", "B": "candidate"} for r in records}


def _metric_record(case_id, variant, value, metric="x"):
    return {
        "case_id": case_id,
        "model_label": "model-a",
        "repetition": 0,
        "variant": variant,
        "kind": "task",
        "metrics": {metric: value},
    }


class TestDeblindGradedRecords(unittest.TestCase):
    def test_attaches_real_variant_from_token_map(self):
        records = [_rec("task-1", "model-a", 0, "A"), _rec("task-1", "model-a", 0, "B")]
        token_maps = {"task-1|model-a|0": {"A": "candidate", "B": "baseline"}}
        out = deblind_graded_records(records, token_maps)
        variants = {r["variant_token"]: r["variant"] for r in out}
        self.assertEqual(variants, {"A": "candidate", "B": "baseline"})

    def test_missing_token_map_entry_leaves_variant_none(self):
        records = [_rec("task-1", "model-a", 0, "A")]
        out = deblind_graded_records(records, {})
        self.assertIsNone(out[0]["variant"])


class TestVariantPassRates(unittest.TestCase):
    def test_basic_pass_rate_split(self):
        records = [
            {"variant": "baseline", "deterministic_pass": True, "deterministic_violations": [], "semantic_pass_rate": None},
            {"variant": "baseline", "deterministic_pass": False, "deterministic_violations": [{"category": "forbidden_write"}], "semantic_pass_rate": None},
            {"variant": "candidate", "deterministic_pass": True, "deterministic_violations": [], "semantic_pass_rate": 1.0},
        ]
        rates = variant_pass_rates(records)
        self.assertEqual(rates["baseline"]["deterministic_pass_rate"], 0.5)
        self.assertEqual(rates["candidate"]["deterministic_pass_rate"], 1.0)
        self.assertEqual(rates["candidate"]["semantic_pass_rate"], 1.0)
        self.assertIsNone(rates["baseline"]["semantic_pass_rate"])

    def test_violation_categories_counted(self):
        records = [
            {"variant": "baseline", "deterministic_pass": False,
             "deterministic_violations": [{"category": "leakage"}, {"category": "leakage"}, {"category": "forbidden_write"}]},
        ]
        rates = variant_pass_rates(records)
        self.assertEqual(rates["baseline"]["violation_counts"], {"leakage": 2, "forbidden_write": 1})
        self.assertEqual(rates["baseline"]["total_violations"], 3)

    def test_records_with_none_variant_are_excluded(self):
        records = [{"variant": None, "deterministic_pass": True, "deterministic_violations": []}]
        self.assertEqual(variant_pass_rates(records), {})


class TestTriggerConfusionMatrix(unittest.TestCase):
    def test_perfect_variant(self):
        records = [
            {"variant": "candidate", "should_trigger": True, "trigger_decision": True},
            {"variant": "candidate", "should_trigger": False, "trigger_decision": False},
        ]
        matrix = trigger_confusion_matrix(records)
        self.assertEqual(matrix["candidate"]["tp"], 1)
        self.assertEqual(matrix["candidate"]["tn"], 1)
        self.assertEqual(matrix["candidate"]["precision"], 1.0)
        self.assertEqual(matrix["candidate"]["recall"], 1.0)
        self.assertEqual(matrix["candidate"]["f1"], 1.0)

    def test_false_positive_hurts_precision_not_recall(self):
        records = [
            {"variant": "baseline", "should_trigger": True, "trigger_decision": True},
            {"variant": "baseline", "should_trigger": False, "trigger_decision": True},  # FP
        ]
        matrix = trigger_confusion_matrix(records)
        self.assertEqual(matrix["baseline"]["fp"], 1)
        self.assertEqual(matrix["baseline"]["precision"], 0.5)
        self.assertEqual(matrix["baseline"]["recall"], 1.0)

    def test_false_negative_hurts_recall_not_precision(self):
        records = [
            {"variant": "baseline", "should_trigger": True, "trigger_decision": False},  # FN
            {"variant": "baseline", "should_trigger": True, "trigger_decision": True},
        ]
        matrix = trigger_confusion_matrix(records)
        self.assertEqual(matrix["baseline"]["fn"], 1)
        self.assertEqual(matrix["baseline"]["recall"], 0.5)
        self.assertEqual(matrix["baseline"]["precision"], 1.0)

    def test_no_positive_predictions_precision_is_none(self):
        records = [{"variant": "baseline", "should_trigger": True, "trigger_decision": False}]
        matrix = trigger_confusion_matrix(records)
        self.assertIsNone(matrix["baseline"]["precision"])

    def test_non_trigger_records_are_ignored(self):
        records = [{"variant": "baseline", "should_trigger": None, "trigger_decision": None}]
        matrix = trigger_confusion_matrix(records)
        self.assertEqual(matrix["baseline"]["n"], 0)

    def test_zero_recall_and_precision_gives_f1_zero(self):
        records = [
            {"variant": "baseline", "should_trigger": True, "trigger_decision": False},
            {"variant": "baseline", "should_trigger": False, "trigger_decision": True},
        ]
        matrix = trigger_confusion_matrix(records)
        self.assertEqual(matrix["baseline"]["precision"], 0.0)
        self.assertEqual(matrix["baseline"]["recall"], 0.0)
        self.assertEqual(matrix["baseline"]["f1"], 0.0)


class TestPairedDeltas(unittest.TestCase):
    def test_computes_candidate_minus_baseline(self):
        records = [
            {"case_id": "task-1", "model_label": "m", "repetition": 0, "variant": "baseline",
             "metrics": {"tool_call_count": 5}},
            {"case_id": "task-1", "model_label": "m", "repetition": 0, "variant": "candidate",
             "metrics": {"tool_call_count": 2}},
        ]
        deltas = paired_deltas(records, ["metrics.tool_call_count"])
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0]["deltas"]["metrics.tool_call_count"], -3)

    def test_incomplete_pair_is_skipped(self):
        records = [{"case_id": "task-1", "model_label": "m", "repetition": 0, "variant": "baseline", "metrics": {}}]
        self.assertEqual(paired_deltas(records, ["metrics.tool_call_count"]), [])

    def test_missing_metric_on_one_side_gives_none_delta(self):
        records = [
            {"case_id": "task-1", "model_label": "m", "repetition": 0, "variant": "baseline", "metrics": {}},
            {"case_id": "task-1", "model_label": "m", "repetition": 0, "variant": "candidate",
             "metrics": {"tool_call_count": 2}},
        ]
        deltas = paired_deltas(records, ["metrics.tool_call_count"])
        self.assertIsNone(deltas[0]["deltas"]["metrics.tool_call_count"])

    def test_summarize_metric_deltas_mean_and_median(self):
        deltas = [
            {"deltas": {"metrics.x": -3}},
            {"deltas": {"metrics.x": -1}},
            {"deltas": {"metrics.x": None}},
        ]
        summary = summarize_metric_deltas(deltas, ["metrics.x"])
        self.assertEqual(summary["metrics.x"]["n"], 2)
        self.assertEqual(summary["metrics.x"]["mean"], -2)
        self.assertEqual(summary["metrics.x"]["median"], -2)


class TestGateMaxDeterministicViolations(unittest.TestCase):
    def test_passes_when_zero_violations(self):
        records = [{"variant": "baseline", "deterministic_violations": []},
                   {"variant": "candidate", "deterministic_violations": []}]
        gate = {"id": "g1", "categories": ["forbidden_write"], "max": 0}
        result = evaluate_gate_max_deterministic_violations(gate, records)
        self.assertTrue(result["passed"])
        self.assertEqual(result["observed"], 0)

    def test_fails_when_over_max(self):
        records = [{"variant": "baseline", "deterministic_violations": [{"category": "forbidden_write"}]}]
        gate = {"id": "g1", "categories": ["forbidden_write"], "max": 0}
        result = evaluate_gate_max_deterministic_violations(gate, records)
        self.assertFalse(result["passed"])
        self.assertEqual(result["observed"], 1)

    def test_only_counts_specified_variants(self):
        records = [
            {"variant": "baseline", "deterministic_violations": [{"category": "leakage"}]},
            {"variant": "candidate", "deterministic_violations": []},
        ]
        gate = {"id": "g1", "categories": ["leakage"], "variants": ["candidate"], "max": 0}
        result = evaluate_gate_max_deterministic_violations(gate, records)
        self.assertTrue(result["passed"])  # baseline's violation not counted

    def test_no_category_filter_counts_everything(self):
        records = [{"variant": "baseline", "deterministic_violations": [{"category": "leakage"}, {"category": "forbidden_command"}]}]
        gate = {"id": "g1", "max": 1}
        result = evaluate_gate_max_deterministic_violations(gate, records)
        self.assertEqual(result["observed"], 2)
        self.assertFalse(result["passed"])


class TestGateMetricReduction(unittest.TestCase):
    def test_passes_on_sufficient_reduction(self):
        records = [
            _metric_record("task-1", "baseline", 2, "review_authorization_prompts"),
            _metric_record("task-1", "candidate", 0, "review_authorization_prompts"),
            _metric_record("task-2", "baseline", 2, "review_authorization_prompts"),
            _metric_record("task-2", "candidate", 0, "review_authorization_prompts"),
        ]
        gate = {"id": "g2", "metric": "metrics.review_authorization_prompts", "min_relative_reduction": 0.5}
        result = evaluate_gate_metric_reduction(gate, records)
        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["observed"], 1.0)

    def test_fails_when_no_improvement(self):
        records = [
            _metric_record("task-1", "baseline", 1),
            _metric_record("task-1", "candidate", 1),
        ]
        gate = {"id": "g2", "metric": "metrics.x", "min_relative_reduction": 0.2}
        result = evaluate_gate_metric_reduction(gate, records)
        self.assertFalse(result["passed"])

    def test_missing_data_fails_safely(self):
        records = [
            _metric_record("task-1", "baseline", None),
            _metric_record("task-1", "candidate", None),
        ]
        gate = {"id": "g2", "metric": "metrics.x", "min_relative_reduction": 0.2}
        result = evaluate_gate_metric_reduction(gate, records)
        self.assertFalse(result["passed"])

    def test_zero_baseline_and_zero_candidate_is_not_a_regression(self):
        records = [
            _metric_record("task-1", "baseline", 0),
            _metric_record("task-1", "candidate", 0),
        ]
        gate = {"id": "g2", "metric": "metrics.x", "min_relative_reduction": 0.0}
        result = evaluate_gate_metric_reduction(gate, records)
        self.assertTrue(result["passed"])

    def test_uses_only_matched_pairs(self):
        records = [
            _metric_record("paired", "baseline", 10),
            _metric_record("paired", "candidate", 12),
            _metric_record("baseline-only", "baseline", 1000),
            _metric_record("candidate-only", "candidate", 0),
        ]
        gate = {"id": "g2", "metric": "metrics.x", "min_relative_reduction": 0.1}
        result = evaluate_gate_metric_reduction(gate, records)
        self.assertFalse(result["passed"])
        self.assertIn("1 matched pair", result["detail"])

    def test_fails_when_matched_pair_count_is_below_gate_minimum(self):
        records = [
            _metric_record("task-1", "baseline", 10),
            _metric_record("task-1", "candidate", 0),
        ]
        gate = {
            "id": "g2",
            "metric": "metrics.x",
            "min_relative_reduction": 0.5,
            "min_pairs": 2,
        }
        result = evaluate_gate_metric_reduction(gate, records)
        self.assertFalse(result["passed"])
        self.assertIn("need at least 2", result["detail"])

    def test_case_kind_filter_prevents_unrelated_pairs_from_satisfying_coverage(self):
        records = [
            _metric_record("task-1", "baseline", 10),
            _metric_record("task-1", "candidate", 5),
            {**_metric_record("trigger-1", "baseline", 10), "kind": "trigger"},
            {**_metric_record("trigger-1", "candidate", 0), "kind": "trigger"},
        ]
        gate = {
            "id": "g2",
            "metric": "metrics.x",
            "case_kinds": ["task"],
            "min_pairs": 2,
            "min_relative_reduction": 0.1,
        }
        result = evaluate_gate_metric_reduction(gate, records)
        self.assertFalse(result["passed"])
        self.assertEqual(result["observed"], 1)


class TestGateTriggerNoRegression(unittest.TestCase):
    def test_passes_when_candidate_at_least_as_good(self):
        records = [
            {"variant": "baseline", "should_trigger": True, "trigger_decision": True},
            {"variant": "baseline", "should_trigger": False, "trigger_decision": True},  # FP -> precision 0.5
            {"variant": "candidate", "should_trigger": True, "trigger_decision": True},
            {"variant": "candidate", "should_trigger": False, "trigger_decision": False},
        ]
        gate = {"id": "g3", "metric": "f1", "tolerance": 0.0}
        result = evaluate_gate_trigger_no_regression(gate, records)
        self.assertTrue(result["passed"])

    def test_fails_on_material_regression(self):
        records = [
            {"variant": "baseline", "should_trigger": True, "trigger_decision": True},
            {"variant": "baseline", "should_trigger": False, "trigger_decision": False},
            {"variant": "candidate", "should_trigger": True, "trigger_decision": False},
            {"variant": "candidate", "should_trigger": False, "trigger_decision": False},
        ]
        gate = {"id": "g3", "metric": "f1", "tolerance": 0.0}
        result = evaluate_gate_trigger_no_regression(gate, records)
        self.assertFalse(result["passed"])

    def test_small_regression_within_tolerance_passes(self):
        # baseline f1=1.0 (perfect), candidate slightly worse but within tolerance
        records = [
            {"variant": "baseline", "should_trigger": True, "trigger_decision": True},
            {"variant": "candidate", "should_trigger": True, "trigger_decision": True},
            {"variant": "candidate", "should_trigger": True, "trigger_decision": False},
        ]
        gate = {"id": "g3", "metric": "recall", "tolerance": 0.6}
        result = evaluate_gate_trigger_no_regression(gate, records)
        self.assertTrue(result["passed"])


class TestEvaluateAcceptanceGates(unittest.TestCase):
    def test_dispatches_by_kind(self):
        records = [{"variant": "baseline", "deterministic_violations": []},
                   {"variant": "candidate", "deterministic_violations": []}]
        gates = [{"id": "g1", "kind": "max_deterministic_violations", "max": 0}]
        results = evaluate_acceptance_gates(gates, records)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["passed"])

    def test_unknown_gate_kind_fails_closed(self):
        results = evaluate_acceptance_gates([{"id": "gx", "kind": "not-a-real-kind"}], [])
        self.assertFalse(results[0]["passed"])

    def test_multiple_gates_all_evaluated(self):
        records = [
            {**_metric_record("task-1", "baseline", 2), "deterministic_violations": []},
            {**_metric_record("task-1", "candidate", 1),
             "deterministic_violations": [{"category": "leakage"}]},
        ]
        gates = [
            {"id": "g1", "kind": "max_deterministic_violations", "categories": ["leakage"], "max": 0},
            {"id": "g2", "kind": "metric_reduction", "metric": "metrics.x", "min_relative_reduction": 0.1},
        ]
        results = evaluate_acceptance_gates(gates, records)
        self.assertEqual(len(results), 2)
        self.assertFalse(results[0]["passed"])  # leakage violation present
        self.assertTrue(results[1]["passed"])  # x reduced from 2 to 1 (50%)


class TestPreferences(unittest.TestCase):
    def test_deblind_preferences_resolves_a_and_b(self):
        prefs = {"task-1|model-a|0": {"preference": "A"}}
        token_maps = {"task-1|model-a|0": {"A": "candidate", "B": "baseline"}}
        resolved = deblind_preferences(prefs, token_maps)
        self.assertEqual(resolved["task-1|model-a|0"]["resolved_variant"], "candidate")

    def test_tie_resolves_to_tie(self):
        prefs = {"task-1|model-a|0": {"preference": "tie"}}
        resolved = deblind_preferences(prefs, {"task-1|model-a|0": {"A": "candidate", "B": "baseline"}})
        self.assertEqual(resolved["task-1|model-a|0"]["resolved_variant"], "tie")

    def test_win_rates_tally_correctly(self):
        resolved = {
            "p1": {"resolved_variant": "candidate"},
            "p2": {"resolved_variant": "candidate"},
            "p3": {"resolved_variant": "baseline"},
            "p4": {"resolved_variant": "tie"},
        }
        rates = preference_win_rates(resolved)
        self.assertEqual(rates["candidate"]["wins"], 2)
        self.assertEqual(rates["baseline"]["wins"], 1)
        self.assertEqual(rates["tie"]["wins"], 1)
        self.assertEqual(rates["_total_judged"], 4)
        self.assertAlmostEqual(rates["candidate"]["rate"], 0.5)

    def test_empty_preferences_gives_none_rates(self):
        rates = preference_win_rates({})
        self.assertIsNone(rates["candidate"]["rate"])
        self.assertEqual(rates["_total_judged"], 0)


if __name__ == "__main__":
    unittest.main()
