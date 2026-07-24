#!/usr/bin/env python3
"""
summarize.py — de-blind, aggregate, evaluate acceptance gates, report.

    python3 summarize.py --run-dir /tmp/ab-run-1 --experiment experiments/<name>/experiment.json

This is the ONE step in the whole pipeline that reads `.private/blinding_key.json`
and turns blind tokens back into real variant names — grading (grade.py) and
blind preference collection (blind_review.py) never do. It combines:

  - variant pass rates (deterministic + semantic, from grade.py's output)
  - trigger precision/recall/F1 per variant
  - paired per-case metric deltas (candidate - baseline) and their mean/median
  - blind pairwise preference win-rates (if preferences.json exists)
  - acceptance-gate PASS/FAIL evaluation from experiment.json's `acceptance_gates`

and writes `summary.json` (machine-readable) + `summary.md` (for a training
log or PR description) into the run directory. Exits non-zero if any
acceptance gate fails, so it can be used as a CI-style check — pass
`--no-fail-on-gate` to only report.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent))
from aggregate import (  # noqa: E402
    deblind_graded_records,
    deblind_preferences,
    evaluate_acceptance_gates,
    paired_deltas,
    preference_win_rates,
    summarize_metric_deltas,
    trigger_confusion_matrix,
    variant_pass_rates,
)

SCHEMA_VERSION = 1
DEFAULT_METRICS_OF_INTEREST = [
    "metrics.tool_call_count",
    "metrics.user_turn_count",
    "metrics.review_authorization_prompts",
    "metrics.duplicate_authorization_prompts",
    "metrics.elapsed_seconds",
    "metrics.time_to_first_finding_seconds",
]


def _load_json(path: Path, default=None):
    if not Path(path).exists():
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_graded_records(run_dir: Path) -> List[dict]:
    records = []
    for path in sorted((run_dir / "graded").glob("*.json")):
        records.append(_load_json(path))
    return records


def flatten_token_maps(blinding_key: dict) -> dict:
    return blinding_key.get("token_maps", {})


def validate_experiment_identity(manifest: dict, blinding_key: dict, experiment: dict = None) -> None:
    identities = {
        "manifest.json": manifest.get("experiment_id"),
        ".private/blinding_key.json": blinding_key.get("experiment_id"),
    }
    if experiment is not None:
        identities["experiment spec"] = experiment.get("experiment_id")
    nonempty = {source: value for source, value in identities.items() if isinstance(value, str) and value}
    if len(nonempty) != len(identities) or len(set(nonempty.values())) != 1:
        raise ValueError(f"experiment_id mismatch or omission across summary inputs: {identities}")


def validate_graded_identities(graded: List[dict]) -> None:
    required_types = {
        "run_id": str,
        "case_id": str,
        "kind": str,
        "model_label": str,
        "repetition": int,
        "variant_token": str,
    }
    for index, record in enumerate(graded):
        if not isinstance(record, dict):
            raise ValueError(f"graded record {index} is not a JSON object")
        for field, expected_type in required_types.items():
            value = record.get(field)
            if not isinstance(value, expected_type):
                raise ValueError(
                    f"graded record {index} field {field!r} must be {expected_type.__name__}, "
                    f"got {type(value).__name__}"
                )
        if record["variant_token"] not in ("A", "B"):
            raise ValueError(f"graded record {index} has invalid variant_token {record['variant_token']!r}")
        if record["kind"] not in ("task", "trigger"):
            raise ValueError(f"graded record {index} has invalid kind {record['kind']!r}")


def validate_complete_records(manifest: dict, graded: List[dict], records: List[dict]) -> dict:
    run_ids = manifest.get("run_ids")
    if not isinstance(run_ids, list) or not all(isinstance(run_id, str) for run_id in run_ids):
        raise ValueError("manifest.json must contain a run_ids list of strings")
    if not run_ids:
        raise ValueError("manifest.json contains no run_ids; refusing to summarize an empty experiment")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("manifest.json contains duplicate run_ids")
    if manifest.get("run_count") is not None and manifest["run_count"] != len(run_ids):
        raise ValueError(
            f"manifest run_count={manifest['run_count']} does not match {len(run_ids)} run_ids"
        )

    observed_ids = [record.get("run_id") for record in graded]
    duplicate_observed = sorted(run_id for run_id, count in Counter(observed_ids).items() if count > 1)
    if duplicate_observed:
        raise ValueError(f"graded records contain duplicate run_ids: {duplicate_observed}")

    expected = set(run_ids)
    observed = set(observed_ids)
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if missing or unexpected:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)} expected graded run(s): {missing}")
        if unexpected:
            parts.append(f"found {len(unexpected)} unexpected graded run(s): {unexpected}")
        raise ValueError("; ".join(parts))

    variants_by_pair = defaultdict(list)
    records_by_pair = defaultdict(list)
    for record in records:
        key = f"{record['case_id']}|{record['model_label']}|{record['repetition']}"
        variants_by_pair[key].append(record.get("variant"))
        records_by_pair[key].append(record)
    invalid_pairs = {
        key: variants
        for key, variants in variants_by_pair.items()
        if sorted(variant for variant in variants if variant is not None) != ["baseline", "candidate"]
        or len(variants) != 2
    }
    if invalid_pairs:
        raise ValueError(
            "every case/model/repetition must have one complete baseline/candidate pair; "
            f"invalid pairs: {invalid_pairs}"
        )

    incomplete_trigger_pairs = {}
    for key, pair_records in records_by_pair.items():
        kinds = [record.get("kind") for record in pair_records]
        if len(set(kinds)) != 1:
            raise ValueError(f"pair {key!r} has mismatched case kinds: {kinds}")
        should_trigger_values = [record.get("should_trigger") for record in pair_records]
        if not any(value is not None for value in should_trigger_values):
            continue
        decisions = [record.get("trigger_decision") for record in pair_records]
        if (
            not all(isinstance(value, bool) for value in should_trigger_values)
            or len(set(should_trigger_values)) != 1
            or not all(isinstance(value, bool) for value in decisions)
        ):
            incomplete_trigger_pairs[key] = {
                "should_trigger": should_trigger_values,
                "trigger_decision": decisions,
            }
    if incomplete_trigger_pairs:
        raise ValueError(
            "trigger pairs require matching should_trigger values and complete trigger decisions; "
            f"invalid pairs: {incomplete_trigger_pairs}"
        )

    return {
        "expected_run_count": len(run_ids),
        "graded_run_count": len(graded),
        "pair_count": len(variants_by_pair),
        "complete": True,
    }


def summarize(run_dir: Path, experiment: dict = None, metrics_of_interest: List[str] = None) -> dict:
    run_dir = Path(run_dir)
    blinding_key = _load_json(run_dir / ".private" / "blinding_key.json")
    if blinding_key is None:
        raise FileNotFoundError(
            f"{run_dir}/.private/blinding_key.json not found — run prepare.py first, "
            "and do not hand this file to an executor or grader."
        )
    token_maps = flatten_token_maps(blinding_key)
    manifest = _load_json(run_dir / "manifest.json")
    if manifest is None:
        raise FileNotFoundError(f"{run_dir}/manifest.json not found — run prepare.py first.")
    validate_experiment_identity(manifest, blinding_key, experiment)

    graded = load_graded_records(run_dir)
    validate_graded_identities(graded)
    records = deblind_graded_records(graded, token_maps)
    completeness = validate_complete_records(manifest, graded, records)

    metrics_of_interest = metrics_of_interest or (experiment or {}).get("metrics_of_interest") or DEFAULT_METRICS_OF_INTEREST

    pass_rates = variant_pass_rates(records)
    trigger_metrics = trigger_confusion_matrix(records)
    deltas = paired_deltas(records, metrics_of_interest)
    metric_delta_summary = summarize_metric_deltas(deltas, metrics_of_interest)

    preferences = _load_json(run_dir / "preferences.json", default={})
    resolved_preferences = deblind_preferences(preferences, token_maps) if preferences else {}
    win_rates = preference_win_rates(resolved_preferences) if resolved_preferences else None

    gates = (experiment or {}).get("acceptance_gates", [])
    gate_results = evaluate_acceptance_gates(gates, records) if gates else []
    overall_passed = all(g["passed"] for g in gate_results) if gate_results else None

    run_counts = {"baseline": pass_rates.get("baseline", {}).get("n", 0), "candidate": pass_rates.get("candidate", {}).get("n", 0)}

    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": (experiment or {}).get("experiment_id") or blinding_key.get("experiment_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_counts": run_counts,
        "data_completeness": completeness,
        "variant_pass_rates": pass_rates,
        "trigger_metrics": trigger_metrics,
        "paired_metric_deltas": deltas,
        "metric_delta_summary": metric_delta_summary,
        "preference_win_rates": win_rates,
        "acceptance_gates": gate_results,
        "overall_passed": overall_passed,
    }


def render_markdown(summary: dict) -> str:
    lines = [f"# ab_eval summary — {summary.get('experiment_id')}", "", f"_Generated {summary.get('generated_at')}_", ""]

    lines.append("## Run counts")
    for variant, n in summary["run_counts"].items():
        lines.append(f"- **{variant}**: {n} graded run(s)")
    lines.append("")

    lines.append("## Variant pass rates")
    lines.append("| Variant | n | Deterministic pass rate | Semantic pass rate (graded n) | Violations |")
    lines.append("|---|---|---|---|---|")
    for variant, stats in sorted(summary["variant_pass_rates"].items()):
        det = stats["deterministic_pass_rate"]
        sem = stats["semantic_pass_rate"]
        lines.append(
            f"| {variant} | {stats['n']} | {det:.0%} | "
            f"{f'{sem:.0%}' if sem is not None else 'n/a'} ({stats['semantic_graded_n']}) | "
            f"{stats['total_violations']} |"
        )
    lines.append("")

    lines.append("## Trigger metrics (precision / recall / F1)")
    lines.append("| Variant | n | Precision | Recall | F1 |")
    lines.append("|---|---|---|---|---|")
    for variant, stats in sorted(summary["trigger_metrics"].items()):
        def _fmt(x):
            return f"{x:.0%}" if isinstance(x, (int, float)) else "n/a"
        lines.append(f"| {variant} | {stats['n']} | {_fmt(stats['precision'])} | {_fmt(stats['recall'])} | {_fmt(stats['f1'])} |")
    lines.append("")

    lines.append("## Paired metric deltas (candidate − baseline)")
    lines.append("| Metric | n pairs | mean Δ | median Δ |")
    lines.append("|---|---|---|---|")
    for metric, stats in summary["metric_delta_summary"].items():
        mean_str = f"{stats['mean']:.3g}" if stats["mean"] is not None else "n/a"
        median_str = f"{stats['median']:.3g}" if stats["median"] is not None else "n/a"
        lines.append(f"| `{metric}` | {stats['n']} | {mean_str} | {median_str} |")
    lines.append("")

    if summary.get("preference_win_rates"):
        lines.append("## Blind pairwise preference win-rates")
        wr = summary["preference_win_rates"]
        lines.append(f"_{wr.get('_total_judged', 0)} pair(s) judged._")
        lines.append("")
        lines.append("| Outcome | Wins | Rate |")
        lines.append("|---|---|---|")
        for key in ("candidate", "baseline", "tie"):
            stats = wr.get(key, {"wins": 0, "rate": None})
            rate_str = f"{stats['rate']:.0%}" if stats["rate"] is not None else "n/a"
            lines.append(f"| {key} | {stats['wins']} | {rate_str} |")
        lines.append("")

    if summary.get("acceptance_gates"):
        lines.append("## Acceptance gates")
        lines.append("| Gate | Kind | Result | Detail |")
        lines.append("|---|---|---|---|")
        for gate in summary["acceptance_gates"]:
            mark = "✅ PASS" if gate["passed"] else "❌ FAIL"
            lines.append(f"| `{gate['id']}` | {gate['kind']} | {mark} | {gate.get('detail', '')} |")
        lines.append("")
        overall = "✅ ALL GATES PASSED" if summary["overall_passed"] else "❌ ONE OR MORE GATES FAILED"
        lines.append(f"**Overall: {overall}**")
        lines.append("")

    lines.append(
        "_Semantic pass rates and preference win-rates reflect external/human judgment ingested via "
        "`grade.py ingest-rubric` / `blind_review.py ingest` — they are not computed by this tool._"
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--experiment", type=Path, default=None, help="experiment.json (for acceptance_gates)")
    parser.add_argument("--no-fail-on-gate", action="store_true", help="Always exit 0 regardless of gate results")
    args = parser.parse_args()

    experiment = _load_json(args.experiment) if args.experiment else None

    try:
        summary = summarize(args.run_dir, experiment)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    (Path(args.run_dir) / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    (Path(args.run_dir) / "summary.md").write_text(render_markdown(summary), encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))

    if summary["overall_passed"] is False and not args.no_fail_on_gate:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
