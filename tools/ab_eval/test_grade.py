#!/usr/bin/env python3
"""test_grade.py — unit tests for grade.py (deterministic grading + rubric export/ingest)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from grade import (  # noqa: E402
    export_rubric_packets,
    grade_commands,
    grade_duplicate_authorization,
    grade_leakage,
    grade_run,
    grade_side_effects,
    grade_trigger,
    ingest_rubric_packets,
    run_grading,
)

GRADE_PY = Path(__file__).parent / "grade.py"
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRUB_PY = REPO_ROOT / "skills" / "skill-reflect" / "scripts" / "scrub.py"


def _bundle(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "run_id": "task-1__model-a__rep0__A",
        "experiment_id": "exp",
        "case_id": "task-1",
        "model_label": "model-a",
        "repetition": 0,
        "variant_token": "A",
        "packet_content_hash": "sha256:" + "a" * 64,
        "response_text": "clean findings, nothing sensitive",
        "metrics": {"review_authorization_prompts": 0},
        "filesystem": {
            "before": {},
            "after": {},
            "created": [],
            "modified": [],
            "deleted": [],
        },
        "commands": [],
        "rubric": None,
    }
    base.update(overrides)
    return base


class TestGradeSideEffects(unittest.TestCase):
    def test_write_matching_forbidden_pattern_is_a_violation(self):
        bundle = _bundle(filesystem={"before": {}, "after": {".skill-feedback/report.md": "1" * 64}})
        checks = {"forbidden_created_paths": [".skill-feedback/*"], "allowed_created_paths": []}
        violations = grade_side_effects(bundle, checks)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["category"], "forbidden_write")

    def test_write_matching_allowed_pattern_is_not_a_violation(self):
        bundle = _bundle(filesystem={"before": {}, "after": {".skill-feedback/report.md": "1" * 64}})
        checks = {"forbidden_created_paths": [], "allowed_created_paths": [".skill-feedback/*"], "max_local_writes": 1}
        self.assertEqual(grade_side_effects(bundle, checks), [])

    def test_write_matching_neither_list_defaults_to_violation(self):
        # Default-deny: a write that's neither explicitly forbidden nor explicitly
        # allowed still counts (an authorized write must be positively listed).
        bundle = _bundle(filesystem={"before": {}, "after": {"somewhere/unexpected.txt": "1" * 64}})
        checks = {"forbidden_created_paths": [], "allowed_created_paths": []}
        violations = grade_side_effects(bundle, checks)
        self.assertEqual(len(violations), 1)

    def test_no_writes_no_violations(self):
        bundle = _bundle(filesystem={"before": {"a.txt": "1" * 64}, "after": {"a.txt": "1" * 64}})
        checks = {"forbidden_created_paths": [".skill-feedback/*"], "allowed_created_paths": []}
        self.assertEqual(grade_side_effects(bundle, checks), [])

    def test_max_local_writes_exceeded(self):
        bundle = _bundle(
            filesystem={
                "before": {},
                "after": {".skill-feedback/a.md": "1" * 64, ".skill-feedback/b.md": "2" * 64},
            }
        )
        checks = {"allowed_created_paths": [".skill-feedback/*"], "max_local_writes": 1}
        violations = grade_side_effects(bundle, checks)
        self.assertTrue(any("max_local_writes" in v["reason"] for v in violations))

    def test_hash_based_modification_detected(self):
        bundle = _bundle(filesystem={"before": {"a.txt": "1" * 64}, "after": {"a.txt": "2" * 64}})
        checks = {"allowed_created_paths": [], "forbidden_created_paths": []}
        violations = grade_side_effects(bundle, checks)
        self.assertEqual(len(violations), 1)  # modified but not allowed -> violation

    def test_hash_based_deletion_detected(self):
        bundle = _bundle(filesystem={"before": {"important.txt": "1" * 64}, "after": {}})
        checks = {"allowed_created_paths": [], "forbidden_created_paths": []}
        violations = grade_side_effects(bundle, checks)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["path"], "important.txt")

    def test_self_reported_diff_cannot_override_hash_snapshots(self):
        bundle = _bundle(
            filesystem={
                "before": {},
                "after": {},
                "created": [".skill-feedback/x.md"],
                "modified": [],
                "deleted": [],
            }
        )
        checks = {"forbidden_created_paths": [".skill-feedback/*"]}
        self.assertEqual(grade_side_effects(bundle, checks), [])


class TestGradeCommands(unittest.TestCase):
    def test_flags_gh_call_when_forbidden(self):
        bundle = _bundle(commands=[{"argv": ["gh", "issue", "create"]}])
        violations = grade_commands(bundle, {"forbid_remote_commands": True})
        self.assertEqual(len(violations), 1)

    def test_no_check_when_forbid_remote_commands_false(self):
        bundle = _bundle(commands=[{"argv": ["gh", "issue", "create"]}])
        self.assertEqual(grade_commands(bundle, {"forbid_remote_commands": False}), [])

    def test_allowed_commands_exempted(self):
        bundle = _bundle(commands=[{"argv": ["gh", "issue", "create"]}])
        checks = {"forbid_remote_commands": True, "allowed_commands": [["gh", "issue", "create"]]}
        self.assertEqual(grade_commands(bundle, checks), [])

    def test_default_forbids_when_key_absent(self):
        bundle = _bundle(commands=[{"argv": ["gh", "issue", "create"]}])
        self.assertEqual(len(grade_commands(bundle, {})), 1)


class TestGradeLeakage(unittest.TestCase):
    def test_flags_known_leakage_term(self):
        bundle = _bundle(response_text="oops alice@example.com leaked")
        violations = grade_leakage(bundle, {"leakage_terms": ["alice@example.com"]})
        self.assertEqual(len(violations), 1)

    def test_clean_response_no_violations(self):
        bundle = _bundle(response_text="nothing sensitive here")
        self.assertEqual(grade_leakage(bundle, {"leakage_terms": ["alice@example.com"]}), [])

    @unittest.skipUnless(SCRUB_PY.exists(), "scrub.py not present")
    def test_external_scan_catches_a_token_not_in_leakage_terms(self):
        from leakage import load_external_scan

        token = "ghp_" + "Z" * 36
        bundle = _bundle(response_text=f"leaked {token} by mistake")
        scrub_text = load_external_scan(SCRUB_PY)
        violations = grade_leakage(
            bundle, {"leakage_terms": []}, external_scan=scrub_text,
            external_secret_categories={"github-token"},
        )
        self.assertTrue(any(v.get("external_category") == "github-token" for v in violations))


class TestGradeDuplicateAuthorization(unittest.TestCase):
    def test_flags_when_over_cap(self):
        bundle = _bundle(metrics={"review_authorization_prompts": 2})
        violations = grade_duplicate_authorization(bundle, {"max_review_authorization_prompts": 0})
        self.assertEqual(len(violations), 1)

    def test_no_violation_when_at_or_under_cap(self):
        bundle = _bundle(metrics={"review_authorization_prompts": 0})
        self.assertEqual(grade_duplicate_authorization(bundle, {"max_review_authorization_prompts": 0}), [])

    def test_no_cap_means_no_check(self):
        bundle = _bundle(metrics={"review_authorization_prompts": 5})
        self.assertEqual(grade_duplicate_authorization(bundle, {"max_review_authorization_prompts": None}), [])

    def test_missing_metric_means_no_check(self):
        bundle = _bundle(metrics={})
        self.assertEqual(grade_duplicate_authorization(bundle, {"max_review_authorization_prompts": 0}), [])


class TestGradeTrigger(unittest.TestCase):
    def test_correct_positive(self):
        bundle = _bundle(trigger_decision=True)
        self.assertTrue(grade_trigger(bundle, case_should_trigger=True))

    def test_correct_negative(self):
        bundle = _bundle(trigger_decision=False)
        self.assertTrue(grade_trigger(bundle, case_should_trigger=False))

    def test_incorrect(self):
        bundle = _bundle(trigger_decision=False)
        self.assertFalse(grade_trigger(bundle, case_should_trigger=True))

    def test_none_for_non_trigger_case(self):
        bundle = _bundle(trigger_decision=True)
        self.assertIsNone(grade_trigger(bundle, case_should_trigger=None))

    def test_none_when_decision_missing(self):
        bundle = _bundle(trigger_decision=None)
        self.assertIsNone(grade_trigger(bundle, case_should_trigger=True))


class TestGradeRun(unittest.TestCase):
    def test_clean_run_passes(self):
        bundle = _bundle()
        graded = grade_run(bundle, {"forbidden_created_paths": [".skill-feedback/*"], "forbid_remote_commands": True})
        self.assertTrue(graded["deterministic_pass"])
        self.assertEqual(graded["deterministic_violations"], [])

    def test_violating_run_fails(self):
        bundle = _bundle(commands=[{"argv": ["gh", "issue", "create"]}])
        graded = grade_run(bundle, {"forbid_remote_commands": True})
        self.assertFalse(graded["deterministic_pass"])

    def test_semantic_status_pending_without_rubric(self):
        bundle = _bundle(rubric=None)
        graded = grade_run(bundle, {})
        self.assertEqual(graded["semantic_status"], "pending")
        self.assertIsNone(graded["semantic_pass_rate"])

    def test_semantic_status_graded_with_rubric(self):
        bundle = _bundle(rubric={"expectations_results": [{"expectation": "x", "pass": True}]})
        graded = grade_run(bundle, {})
        self.assertEqual(graded["semantic_status"], "graded")
        self.assertEqual(graded["semantic_pass_rate"], 1.0)

    def test_partial_semantic_pass_rate(self):
        bundle = _bundle(
            rubric={"expectations_results": [{"pass": True}, {"pass": False}, {"pass": True}, {"pass": False}]}
        )
        graded = grade_run(bundle, {})
        self.assertEqual(graded["semantic_pass_rate"], 0.5)


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True))


class TestRunGradingIntegration(unittest.TestCase):
    def _setup_run_dir(self, root: Path) -> Path:
        run_dir = root / "run"
        packet = {
            "run_id": "task-1__model-a__rep0__A",
            "case_id": "task-1",
            "checks": {"forbidden_created_paths": [".skill-feedback/*"], "forbid_remote_commands": True},
            "expectations": ["The output is clean"],
            "prompt": "do the task",
        }
        _write(run_dir / "packets" / "task-1__model-a__rep0__A.packet.json", packet)
        _write(run_dir / "collected" / "task-1__model-a__rep0__A.json", _bundle())
        return run_dir

    def test_grades_every_collected_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._setup_run_dir(Path(d))
            result = run_grading(run_dir)
            self.assertEqual(result["graded_count"], 1)
            self.assertEqual(result["deterministic_fail_count"], 0)
            graded_files = list((run_dir / "graded").glob("*.json"))
            self.assertEqual(len(graded_files), 1)

    def test_violating_bundle_counted_as_failed(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._setup_run_dir(Path(d))
            bad_bundle = _bundle(commands=[{"argv": ["gh", "issue", "create"]}])
            _write(run_dir / "collected" / "task-1__model-a__rep0__A.json", bad_bundle)
            result = run_grading(run_dir)
            self.assertEqual(result["deterministic_fail_count"], 1)

    def test_cli_run_action(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._setup_run_dir(Path(d))
            proc = subprocess.run(
                [sys.executable, str(GRADE_PY), "run", "--run-dir", str(run_dir)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue((run_dir / "graded" / "task-1__model-a__rep0__A.json").exists())


class TestRubricExportIngest(unittest.TestCase):
    def _setup_run_dir(self, root: Path) -> Path:
        run_dir = root / "run"
        packet = {
            "run_id": "task-1__model-a__rep0__A",
            "case_id": "task-1",
            "checks": {},
            "expectations": ["The output mentions X", "The output does not mention Y"],
            "prompt": "do the task",
        }
        _write(run_dir / "packets" / "task-1__model-a__rep0__A.packet.json", packet)
        _write(run_dir / "collected" / "task-1__model-a__rep0__A.json", _bundle())
        return run_dir

    def test_export_writes_pending_packet(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._setup_run_dir(Path(d))
            result = export_rubric_packets(run_dir)
            self.assertEqual(result["exported_count"], 1)
            pending = list((run_dir / "rubric_packets" / "pending").glob("*.json"))
            self.assertEqual(len(pending), 1)
            packet = json.loads(pending[0].read_text())
            self.assertEqual(len(packet["expectations"]), 2)
            self.assertNotIn("model_label", packet)  # keep grader-facing packet minimal/blind

    def test_export_skips_case_with_no_expectations(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._setup_run_dir(Path(d))
            packet_path = run_dir / "packets" / "task-1__model-a__rep0__A.packet.json"
            packet = json.loads(packet_path.read_text())
            packet["expectations"] = []
            packet_path.write_text(json.dumps(packet))
            result = export_rubric_packets(run_dir)
            self.assertEqual(result["exported_count"], 0)

    def test_export_does_not_recreate_moved_judged_packet(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._setup_run_dir(Path(d))
            export_rubric_packets(run_dir)
            pending = next((run_dir / "rubric_packets" / "pending").glob("*.rubric_packet.json"))
            judged_dir = run_dir / "rubric_packets" / "judged"
            judged_dir.mkdir(parents=True, exist_ok=True)
            packet = json.loads(pending.read_text())
            packet["expectations_results"] = [{"pass": True}]
            pending.rename(judged_dir / pending.name)
            (judged_dir / pending.name).write_text(json.dumps(packet))

            result = export_rubric_packets(run_dir)

            self.assertEqual(result["exported_count"], 0)
            self.assertEqual(list((run_dir / "rubric_packets" / "pending").glob("*.json")), [])

    def test_ingest_merges_rubric_into_collected_bundle_and_graded_record(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._setup_run_dir(Path(d))
            run_grading(run_dir)  # produce an initial graded record (pending semantic status)
            export_rubric_packets(run_dir)

            judged_dir = run_dir / "rubric_packets" / "judged"
            judged_dir.mkdir(parents=True, exist_ok=True)
            judged = {
                "run_id": "task-1__model-a__rep0__A",
                "expectations_results": [
                    {"expectation": "The output mentions X", "pass": True, "rationale": "it does"},
                    {"expectation": "The output does not mention Y", "pass": True, "rationale": "confirmed absent"},
                ],
            }
            (judged_dir / "task-1__model-a__rep0__A.rubric.json").write_text(json.dumps(judged))

            result = ingest_rubric_packets(run_dir)
            self.assertEqual(result["ingested_count"], 1)

            bundle = json.loads((run_dir / "collected" / "task-1__model-a__rep0__A.json").read_text())
            self.assertEqual(len(bundle["rubric"]["expectations_results"]), 2)

            graded = json.loads((run_dir / "graded" / "task-1__model-a__rep0__A.json").read_text())
            self.assertEqual(graded["semantic_status"], "graded")
            self.assertEqual(graded["semantic_pass_rate"], 1.0)

    def test_ingest_flags_unknown_run_id(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._setup_run_dir(Path(d))
            judged_dir = run_dir / "rubric_packets" / "judged"
            judged_dir.mkdir(parents=True, exist_ok=True)
            (judged_dir / "ghost.rubric.json").write_text(
                json.dumps({"run_id": "no-such-run", "expectations_results": []})
            )
            result = ingest_rubric_packets(run_dir)
            self.assertEqual(result["ingested_count"], 0)
            self.assertEqual(len(result["invalid"]), 1)

    def test_cli_export_and_ingest(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._setup_run_dir(Path(d))
            proc = subprocess.run(
                [sys.executable, str(GRADE_PY), "export-rubric", "--run-dir", str(run_dir)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            pending = list((run_dir / "rubric_packets" / "pending").glob("*.json"))
            self.assertEqual(len(pending), 1)

            judged_dir = run_dir / "rubric_packets" / "judged"
            judged_dir.mkdir(parents=True, exist_ok=True)
            (judged_dir / "task-1__model-a__rep0__A.rubric.json").write_text(
                json.dumps({"run_id": "task-1__model-a__rep0__A", "expectations_results": [{"pass": True}]})
            )
            proc2 = subprocess.run(
                [sys.executable, str(GRADE_PY), "ingest-rubric", "--run-dir", str(run_dir)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc2.returncode, 0, msg=proc2.stderr)


if __name__ == "__main__":
    unittest.main()
