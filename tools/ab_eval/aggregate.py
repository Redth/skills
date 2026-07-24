#!/usr/bin/env python3
"""
aggregate.py — pure, importable aggregation logic: de-blinding, pass rates,
paired deltas, trigger precision/recall/F1, blind-preference tallying, and
acceptance-gate evaluation.

Everything here is a pure function over already-graded records (see
grade.py) plus the blinding key (see prepare.py's .private/blinding_key.json)
— no I/O, no subprocess, easy to unit test in isolation. `summarize.py` is
the thin CLI that wires this module to a run directory on disk.

De-blinding happens HERE, not in grade.py — grading must stay blind (a
grader never learns which token is baseline/candidate), but *analysis* of
already-graded, already-collected evidence is exactly the moment a
transparent, reproducible tool is supposed to reveal the mapping and report
directional deltas. That ordering (grade blind, then de-blind to aggregate)
is what makes "blind" mean something rather than being cosmetic.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean, median
from typing import Dict, List, Optional, Tuple

VARIANTS = ("baseline", "candidate")


def deblind_graded_records(graded_records: List[dict], token_maps: Dict[str, dict]) -> List[dict]:
    """Attach the real `variant` name to each graded record using the ground-truth token map."""
    out = []
    for rec in graded_records:
        key = f"{rec['case_id']}|{rec['model_label']}|{rec['repetition']}"
        token_map = token_maps.get(key, {})
        variant = token_map.get(rec.get("variant_token"))
        merged = dict(rec)
        merged["variant"] = variant
        out.append(merged)
    return out


def group_by_variant(records: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for rec in records:
        grouped[rec.get("variant")].append(rec)
    return grouped


def variant_pass_rates(records: List[dict]) -> Dict[str, dict]:
    """Per real-variant deterministic + semantic pass rates and violation counts."""
    out: Dict[str, dict] = {}
    for variant, recs in group_by_variant(records).items():
        if variant is None:
            continue
        det_passes = sum(1 for r in recs if r.get("deterministic_pass"))
        semantic_vals = [r["semantic_pass_rate"] for r in recs if r.get("semantic_pass_rate") is not None]
        violation_categories: Dict[str, int] = defaultdict(int)
        for r in recs:
            for v in r.get("deterministic_violations", []):
                violation_categories[v.get("category", "unknown")] += 1
        out[variant] = {
            "n": len(recs),
            "deterministic_pass_rate": det_passes / len(recs) if recs else None,
            "semantic_pass_rate": mean(semantic_vals) if semantic_vals else None,
            "semantic_graded_n": len(semantic_vals),
            "violation_counts": dict(violation_categories),
            "total_violations": sum(violation_categories.values()),
        }
    return out


def trigger_confusion_matrix(records: List[dict]) -> Dict[str, dict]:
    """Per real-variant TP/FP/FN/TN plus precision/recall/F1, over trigger-kind records only."""
    out: Dict[str, dict] = {}
    for variant, recs in group_by_variant(records).items():
        if variant is None:
            continue
        trigger_recs = [r for r in recs if r.get("should_trigger") is not None and r.get("trigger_decision") is not None]
        tp = sum(1 for r in trigger_recs if r["should_trigger"] and r["trigger_decision"])
        fp = sum(1 for r in trigger_recs if not r["should_trigger"] and r["trigger_decision"])
        fn = sum(1 for r in trigger_recs if r["should_trigger"] and not r["trigger_decision"])
        tn = sum(1 for r in trigger_recs if not r["should_trigger"] and not r["trigger_decision"])

        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        f1 = (2 * precision * recall / (precision + recall)) if (precision and recall and (precision + recall)) else (
            0.0 if precision == 0 or recall == 0 else None
        )
        out[variant] = {
            "n": len(trigger_recs),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return out


def pair_key(rec: dict) -> str:
    return f"{rec['case_id']}|{rec['model_label']}|{rec['repetition']}"


def paired_records(records: List[dict]) -> Dict[str, Dict[str, dict]]:
    """Group de-blinded records into {pair_key: {"baseline": rec, "candidate": rec}}."""
    pairs: Dict[str, Dict[str, dict]] = defaultdict(dict)
    for rec in records:
        variant = rec.get("variant")
        if variant in VARIANTS:
            pairs[pair_key(rec)][variant] = rec
    return pairs


def _metric_value(rec: dict, metric_path: str):
    cur = rec
    for part in metric_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def paired_deltas(records: List[dict], metric_paths: List[str]) -> List[dict]:
    """For each complete baseline/candidate pair, compute candidate - baseline for each metric.

    `metric_paths` are dotted paths into each record, e.g. "metrics.tool_call_count".
    A pair missing either side, or missing the metric on either side, is skipped
    for that metric (reported via `n` per metric in `metric_deltas_summary`).
    """
    out = []
    for key, pair in sorted(paired_records(records).items()):
        if "baseline" not in pair or "candidate" not in pair:
            continue
        row = {"pair_key": key, "case_id": pair["baseline"]["case_id"], "deltas": {}}
        for path in metric_paths:
            b_val = _metric_value(pair["baseline"], path)
            c_val = _metric_value(pair["candidate"], path)
            if isinstance(b_val, (int, float)) and isinstance(c_val, (int, float)):
                row["deltas"][path] = c_val - b_val
            else:
                row["deltas"][path] = None
        out.append(row)
    return out


def summarize_metric_deltas(deltas: List[dict], metric_paths: List[str]) -> Dict[str, dict]:
    """Aggregate paired_deltas() output into {metric: {n, mean, median}}."""
    out = {}
    for path in metric_paths:
        values = [row["deltas"].get(path) for row in deltas if row["deltas"].get(path) is not None]
        out[path] = {
            "n": len(values),
            "mean": mean(values) if values else None,
            "median": median(values) if values else None,
        }
    return out


def paired_metric_means(
    records: List[dict], metric_path: str, case_kinds: Optional[List[str]] = None
) -> Tuple[Dict[str, Optional[float]], int]:
    """Return variant means over only pairs where both metric values exist."""
    baseline_values = []
    candidate_values = []
    for pair in paired_records(records).values():
        if "baseline" not in pair or "candidate" not in pair:
            continue
        if case_kinds and (
            pair["baseline"].get("kind") not in case_kinds
            or pair["candidate"].get("kind") not in case_kinds
        ):
            continue
        baseline_value = _metric_value(pair["baseline"], metric_path)
        candidate_value = _metric_value(pair["candidate"], metric_path)
        if not isinstance(baseline_value, (int, float)) or not isinstance(candidate_value, (int, float)):
            continue
        baseline_values.append(baseline_value)
        candidate_values.append(candidate_value)
    return (
        {
            "baseline": mean(baseline_values) if baseline_values else None,
            "candidate": mean(candidate_values) if candidate_values else None,
        },
        len(baseline_values),
    )


def deblind_preferences(preferences: Dict[str, dict], token_maps: Dict[str, dict]) -> Dict[str, dict]:
    """Resolve each pairwise preference's blind 'A'/'B'/'tie' choice to a real variant name."""
    out = {}
    for pair_key_str, pref in preferences.items():
        token_map = token_maps.get(pair_key_str, {})
        choice = pref.get("preference")
        if choice in ("A", "B"):
            resolved = token_map.get(choice)
        else:
            resolved = "tie"
        out[pair_key_str] = {**pref, "resolved_variant": resolved}
    return out


def preference_win_rates(resolved_preferences: Dict[str, dict]) -> Dict[str, dict]:
    """Tally win/tie counts per real variant from deblind_preferences() output."""
    counts: Dict[str, int] = defaultdict(int)
    total = 0
    for pref in resolved_preferences.values():
        counts[pref["resolved_variant"]] += 1
        total += 1
    out = {}
    for variant in (*VARIANTS, "tie"):
        n = counts.get(variant, 0)
        out[variant] = {"wins": n, "rate": (n / total) if total else None}
    out["_total_judged"] = total
    return out


# ---------------------------------------------------------------------------
# Acceptance gates
# ---------------------------------------------------------------------------

def evaluate_gate_max_deterministic_violations(gate: dict, records: List[dict]) -> dict:
    categories = set(gate.get("categories") or [])
    variants = gate.get("variants") or list(VARIANTS)
    max_allowed = gate.get("max", 0)

    count = 0
    for rec in records:
        if rec.get("variant") not in variants:
            continue
        for v in rec.get("deterministic_violations", []):
            if not categories or v.get("category") in categories:
                count += 1
    passed = count <= max_allowed
    return {
        "id": gate.get("id"),
        "kind": "max_deterministic_violations",
        "passed": passed,
        "observed": count,
        "threshold": max_allowed,
        "detail": f"{count} violation(s) in categories {sorted(categories) or 'ANY'} "
                  f"across variants {variants} (max allowed {max_allowed})",
    }


def evaluate_gate_metric_reduction(gate: dict, records: List[dict]) -> dict:
    metric = gate["metric"]
    min_relative_reduction = gate.get("min_relative_reduction", 0.0)
    min_pairs = gate.get("min_pairs", 1)
    case_kinds = gate.get("case_kinds")
    if case_kinds is not None and (
        not isinstance(case_kinds, list)
        or not case_kinds
        or not all(kind in ("task", "trigger") for kind in case_kinds)
    ):
        return {
            "id": gate.get("id"), "kind": "metric_reduction", "passed": False,
            "observed": None, "threshold": None,
            "detail": f"invalid case_kinds={case_kinds!r}; expected a non-empty task/trigger list",
        }
    by_variant, pair_count = paired_metric_means(records, metric, case_kinds)
    pair_scope = f"{'/'.join(case_kinds)} " if case_kinds else ""
    baseline_mean = by_variant.get("baseline")
    candidate_mean = by_variant.get("candidate")

    if not isinstance(min_pairs, int) or isinstance(min_pairs, bool) or min_pairs < 1:
        return {
            "id": gate.get("id"), "kind": "metric_reduction", "passed": False,
            "observed": pair_count, "threshold": min_pairs,
            "detail": f"invalid min_pairs={min_pairs!r}; expected a positive integer",
        }
    if pair_count < min_pairs:
        return {
            "id": gate.get("id"), "kind": "metric_reduction", "passed": False,
            "observed": pair_count, "threshold": min_pairs,
            "detail": f"only {pair_count} matched {pair_scope}pair(s) reported metric '{metric}'; "
                      f"need at least {min_pairs}",
        }
    if baseline_mean is None or candidate_mean is None:
        return {
            "id": gate.get("id"), "kind": "metric_reduction", "passed": False,
            "observed": None, "threshold": min_relative_reduction,
            "detail": f"insufficient matched-pair data for metric '{metric}' "
                      f"(pairs={pair_count}, baseline={baseline_mean}, candidate={candidate_mean})",
        }

    if baseline_mean == 0:
        relative_reduction = 0.0 if candidate_mean == 0 else -float("inf")
    else:
        relative_reduction = (baseline_mean - candidate_mean) / baseline_mean

    passed = relative_reduction >= min_relative_reduction
    return {
        "id": gate.get("id"),
        "kind": "metric_reduction",
        "passed": passed,
        "observed": relative_reduction,
        "threshold": min_relative_reduction,
        "detail": f"'{metric}' over {pair_count} matched {pair_scope}pair(s): "
                  f"mean baseline={baseline_mean:.3g} candidate={candidate_mean:.3g} "
                  f"relative_reduction={relative_reduction:.3g} (need >= {min_relative_reduction})",
    }


def evaluate_gate_trigger_no_regression(gate: dict, records: List[dict]) -> dict:
    metric = gate.get("metric", "f1")
    tolerance = gate.get("tolerance", 0.0)
    confusion = trigger_confusion_matrix(records)
    baseline_val = (confusion.get("baseline") or {}).get(metric)
    candidate_val = (confusion.get("candidate") or {}).get(metric)

    if baseline_val is None or candidate_val is None:
        return {
            "id": gate.get("id"), "kind": "trigger_no_regression", "passed": False,
            "observed": None, "threshold": tolerance,
            "detail": f"insufficient trigger data for metric '{metric}' "
                      f"(baseline={baseline_val}, candidate={candidate_val})",
        }

    passed = candidate_val >= (baseline_val - tolerance)
    return {
        "id": gate.get("id"),
        "kind": "trigger_no_regression",
        "passed": passed,
        "observed": candidate_val - baseline_val,
        "threshold": -tolerance,
        "detail": f"trigger {metric}: baseline={baseline_val:.3g} candidate={candidate_val:.3g} "
                  f"(candidate must be >= baseline - {tolerance})",
    }


_GATE_EVALUATORS = {
    "max_deterministic_violations": evaluate_gate_max_deterministic_violations,
    "metric_reduction": evaluate_gate_metric_reduction,
    "trigger_no_regression": evaluate_gate_trigger_no_regression,
}


def evaluate_acceptance_gates(gates: List[dict], records: List[dict]) -> List[dict]:
    """Evaluate every gate in an experiment spec's `acceptance_gates` against de-blinded records."""
    results = []
    for gate in gates:
        evaluator = _GATE_EVALUATORS.get(gate.get("kind"))
        if evaluator is None:
            results.append(
                {"id": gate.get("id"), "kind": gate.get("kind"), "passed": False,
                 "detail": f"unknown gate kind {gate.get('kind')!r}"}
            )
            continue
        results.append(evaluator(gate, records))
    return results
