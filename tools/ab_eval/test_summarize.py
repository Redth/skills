#!/usr/bin/env python3
"""test_summarize.py — unit tests for summarize.py (de-blind + aggregate + gate CLI)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from summarize import render_markdown, summarize  # noqa: E402

SUMMARIZE_PY = Path(__file__).parent / "summarize.py"


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True))


def _graded(run_id, case_id, model, rep, token, **overrides):
    base = {
        "run_id": run_id,
        "case_id": case_id,
        "kind": "task",
        "model_label": model,
        "repetition": rep,
        "variant_token": token,
        "deterministic_pass": True,
        "deterministic_violations": [],
        "should_trigger": None,
        "trigger_decision": None,
        "semantic_pass_rate": None,
        "metrics": {"tool_call_count": 3, "review_authorization_prompts": 0},
    }
    base.update(overrides)
    return base


def _build_run_dir(root: Path) -> Path:
    run_dir = root / "run"
    run_ids = [
        "task-1__model-a__rep0__A",
        "task-1__model-a__rep0__B",
    ]
    _write(
        run_dir / "manifest.json",
        {"schema_version": 1, "experiment_id": "exp-1", "run_ids": run_ids, "run_count": len(run_ids)},
    )
    token_maps = {"task-1|model-a|0": {"A": "candidate", "B": "baseline"}}
    _write(
        run_dir / ".private" / "blinding_key.json",
        {"experiment_id": "exp-1", "token_maps": token_maps, "variant_content_hashes": {"baseline": "sha256:a", "candidate": "sha256:b"}},
    )
    _write(
        run_dir / "graded" / "task-1__model-a__rep0__A.json",
        _graded("task-1__model-a__rep0__A", "task-1", "model-a", 0, "A",
                metrics={"tool_call_count": 1, "review_authorization_prompts": 0}),
    )
    _write(
        run_dir / "graded" / "task-1__model-a__rep0__B.json",
        _graded("task-1__model-a__rep0__B", "task-1", "model-a", 0, "B",
                metrics={"tool_call_count": 5, "review_authorization_prompts": 1}),
    )
    return run_dir


class TestSummarize(unittest.TestCase):
    def test_missing_blinding_key_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                summarize(Path(d) / "run")

    def test_missing_manifest_raises(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            (run_dir / "manifest.json").unlink()
            with self.assertRaises(FileNotFoundError):
                summarize(run_dir)

    def test_missing_graded_run_rejects_authoritative_summary(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            (run_dir / "graded" / "task-1__model-a__rep0__B.json").unlink()
            with self.assertRaisesRegex(ValueError, "missing 1 expected graded run"):
                summarize(run_dir)

    def test_unpaired_variant_mapping_rejects_authoritative_summary(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            key_path = run_dir / ".private" / "blinding_key.json"
            key = json.loads(key_path.read_text())
            key["token_maps"]["task-1|model-a|0"] = {"A": "candidate", "B": "candidate"}
            key_path.write_text(json.dumps(key))
            with self.assertRaisesRegex(ValueError, "complete baseline/candidate pair"):
                summarize(run_dir)

    def test_incomplete_trigger_decision_rejects_authoritative_summary(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            for token, decision in (("A", True), ("B", None)):
                path = run_dir / "graded" / f"task-1__model-a__rep0__{token}.json"
                record = json.loads(path.read_text())
                record["kind"] = "trigger"
                record["should_trigger"] = True
                record["trigger_decision"] = decision
                path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "complete trigger decisions"):
                summarize(run_dir)

    def test_experiment_id_mismatch_rejects_summary(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            with self.assertRaisesRegex(ValueError, "experiment_id"):
                summarize(run_dir, experiment={"experiment_id": "different-experiment"})

    def test_deblinds_and_computes_pass_rates(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            summary = summarize(run_dir)
            self.assertEqual(summary["run_counts"], {"baseline": 1, "candidate": 1})
            self.assertEqual(summary["variant_pass_rates"]["baseline"]["deterministic_pass_rate"], 1.0)
            self.assertEqual(summary["variant_pass_rates"]["candidate"]["deterministic_pass_rate"], 1.0)

    def test_computes_paired_metric_deltas(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            summary = summarize(run_dir, metrics_of_interest=["metrics.tool_call_count"])
            # token A -> candidate (tool_call_count=1), token B -> baseline (tool_call_count=5)
            # delta = candidate - baseline = 1 - 5 = -4
            self.assertEqual(summary["metric_delta_summary"]["metrics.tool_call_count"]["mean"], -4)

    def test_acceptance_gates_evaluated_when_experiment_given(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            experiment = {
                "experiment_id": "exp-1",
                "acceptance_gates": [
                    {"id": "zero-writes", "kind": "max_deterministic_violations", "categories": ["forbidden_write"], "max": 0},
                    {"id": "fewer-prompts", "kind": "metric_reduction", "metric": "metrics.review_authorization_prompts",
                     "min_relative_reduction": 0.5},
                ],
            }
            summary = summarize(run_dir, experiment=experiment)
            self.assertTrue(summary["overall_passed"])
            self.assertEqual(len(summary["acceptance_gates"]), 2)

    def test_failing_gate_sets_overall_passed_false(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            _write(
                run_dir / "graded" / "task-1__model-a__rep0__A.json",
                _graded("task-1__model-a__rep0__A", "task-1", "model-a", 0, "A",
                        deterministic_pass=False, deterministic_violations=[{"category": "forbidden_write"}]),
            )
            experiment = {
                "experiment_id": "exp-1",
                "acceptance_gates": [{"id": "zero-writes", "kind": "max_deterministic_violations",
                                      "categories": ["forbidden_write"], "max": 0}],
            }
            summary = summarize(run_dir, experiment=experiment)
            self.assertFalse(summary["overall_passed"])

    def test_no_gates_gives_none_overall_passed(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            summary = summarize(run_dir, experiment={"experiment_id": "exp-1", "acceptance_gates": []})
            self.assertIsNone(summary["overall_passed"])

    def test_preference_win_rates_included_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            _write(run_dir / "preferences.json", {"task-1|model-a|0": {"preference": "A"}})
            summary = summarize(run_dir)
            self.assertIsNotNone(summary["preference_win_rates"])
            self.assertEqual(summary["preference_win_rates"]["candidate"]["wins"], 1)

    def test_trigger_metrics_present_but_empty_without_trigger_cases(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            summary = summarize(run_dir)
            self.assertIn("baseline", summary["trigger_metrics"])
            self.assertEqual(summary["trigger_metrics"]["baseline"]["n"], 0)


class TestRenderMarkdown(unittest.TestCase):
    def test_renders_without_error_and_includes_key_sections(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            summary = summarize(run_dir, experiment={
                "experiment_id": "exp-1",
                "acceptance_gates": [{"id": "g1", "kind": "max_deterministic_violations", "max": 0}],
            })
            md = render_markdown(summary)
            self.assertIn("# ab_eval summary", md)
            self.assertIn("## Variant pass rates", md)
            self.assertIn("## Acceptance gates", md)
            self.assertIn("g1", md)

    def test_renders_preference_section_only_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            summary_no_prefs = summarize(run_dir)
            md_no_prefs = render_markdown(summary_no_prefs)
            self.assertNotIn("Blind pairwise preference", md_no_prefs)

            _write(run_dir / "preferences.json", {"task-1|model-a|0": {"preference": "tie"}})
            summary_with_prefs = summarize(run_dir)
            md_with_prefs = render_markdown(summary_with_prefs)
            self.assertIn("Blind pairwise preference", md_with_prefs)


class TestCli(unittest.TestCase):
    def test_cli_writes_summary_files(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            proc = subprocess.run(
                [sys.executable, str(SUMMARIZE_PY), "--run-dir", str(run_dir)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue((run_dir / "summary.json").exists())
            self.assertTrue((run_dir / "summary.md").exists())

    def test_cli_exits_nonzero_on_failed_gate(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            _write(
                run_dir / "graded" / "task-1__model-a__rep0__A.json",
                _graded("task-1__model-a__rep0__A", "task-1", "model-a", 0, "A",
                        deterministic_pass=False, deterministic_violations=[{"category": "leakage"}]),
            )
            exp_path = run_dir / "experiment.json"
            exp_path.write_text(json.dumps({
                "experiment_id": "exp-1",
                "acceptance_gates": [{"id": "zero-leak", "kind": "max_deterministic_violations",
                                      "categories": ["leakage"], "max": 0}],
            }))
            proc = subprocess.run(
                [sys.executable, str(SUMMARIZE_PY), "--run-dir", str(run_dir), "--experiment", str(exp_path)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(proc.returncode, 0)

    def test_cli_no_fail_on_gate_flag_forces_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            _write(
                run_dir / "graded" / "task-1__model-a__rep0__A.json",
                _graded("task-1__model-a__rep0__A", "task-1", "model-a", 0, "A",
                        deterministic_pass=False, deterministic_violations=[{"category": "leakage"}]),
            )
            exp_path = run_dir / "experiment.json"
            exp_path.write_text(json.dumps({
                "experiment_id": "exp-1",
                "acceptance_gates": [{"id": "zero-leak", "kind": "max_deterministic_violations",
                                      "categories": ["leakage"], "max": 0}],
            }))
            proc = subprocess.run(
                [sys.executable, str(SUMMARIZE_PY), "--run-dir", str(run_dir), "--experiment", str(exp_path),
                 "--no-fail-on-gate"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_cli_missing_blinding_key_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            run_dir.mkdir()
            proc = subprocess.run(
                [sys.executable, str(SUMMARIZE_PY), "--run-dir", str(run_dir)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(proc.returncode, 0)

    def test_cli_incomplete_manifest_exits_nonzero_without_writing_summary(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = _build_run_dir(Path(d))
            (run_dir / "graded" / "task-1__model-a__rep0__B.json").unlink()
            proc = subprocess.run(
                [sys.executable, str(SUMMARIZE_PY), "--run-dir", str(run_dir)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse((run_dir / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
