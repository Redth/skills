#!/usr/bin/env python3
"""
test_skill_reflect_experiment.py — regression tests for the packaged
skill-reflect v1.1.0-vs-v1.2.0 reference experiment.

Unlike the other test_*.py files (which exercise the generic ab_eval
framework against synthetic fixtures), this file locks the *specific*
experiment.json + checks.json under experiments/skill-reflect-v1.1.0-vs-v1.2.0/
to the live skills/skill-reflect/evals/*.json files. If a future change adds
or renumbers a task eval without updating checks.json, or changes SKILL.md in
a way that breaks variant materialization, these tests fail loudly instead
of silently producing an incomplete or blinding-broken run.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_DIR = Path(__file__).resolve().parent / "experiments" / "skill-reflect-v1.1.0-vs-v1.2.0"
EXPERIMENT_JSON = EXPERIMENT_DIR / "experiment.json"
CHECKS_JSON = EXPERIMENT_DIR / "checks.json"

sys.path.insert(0, str(Path(__file__).parent))
from case_loader import checks_for_case, duplicate_case_ids, load_case_set, load_checks  # noqa: E402
from prepare import materialize_variants, prepare  # noqa: E402
from schemas import validate_case_checks, validate_experiment_spec  # noqa: E402


def _load_experiment() -> dict:
    return json.loads(EXPERIMENT_JSON.read_text(encoding="utf-8"))


@unittest.skipUnless(EXPERIMENT_JSON.exists(), "reference experiment.json not present")
class TestExperimentSpecItself(unittest.TestCase):
    def test_experiment_spec_is_structurally_valid(self):
        spec = _load_experiment()
        self.assertEqual(validate_experiment_spec(spec), [])

    def test_baseline_pins_a_git_ref_candidate_uses_worktree(self):
        # This is the specific design choice for this experiment: baseline is
        # pinned to the pre-v1.2.0 commit; candidate reads the current
        # (possibly uncommitted) working tree. Both variant sources share the
        # same include-list so VERSION/evals/** never leak into either.
        spec = _load_experiment()
        self.assertEqual(spec["variants"]["baseline"]["source"]["kind"], "git_ref")
        self.assertEqual(spec["variants"]["candidate"]["source"]["kind"], "worktree")
        baseline_include = set(spec["variants"]["baseline"]["source"]["include"])
        candidate_include = set(spec["variants"]["candidate"]["source"]["include"])
        self.assertEqual(baseline_include, candidate_include)
        self.assertNotIn("VERSION", baseline_include)

    def test_five_acceptance_gates_cover_the_four_named_goals(self):
        spec = _load_experiment()
        gate_ids = {g["id"] for g in spec["acceptance_gates"]}
        # The four goals named in the training brief, mapped 1:1 to gate ids.
        self.assertIn("zero-unauthorized-writes", gate_ids)
        self.assertIn("remote-safety", gate_ids)
        self.assertIn("material-interaction-reduction", gate_ids)
        self.assertIn("no-trigger-regression", gate_ids)

    def test_holdout_is_honestly_marked_not_included(self):
        spec = _load_experiment()
        self.assertFalse(spec["holdout"]["included"])


@unittest.skipUnless(CHECKS_JSON.exists(), "reference checks.json not present")
class TestChecksCompletenessAgainstLiveEvals(unittest.TestCase):
    """The most important regression guard: checks.json must stay in sync with
    the live evals.json — every task case needs hand-authored leakage/write/
    command rules, because (per the harness's core rule) those can't be
    derived automatically from natural-language `expectations` text."""

    def setUp(self):
        spec = _load_experiment()
        case_set = spec["case_sets"]["dev_regression"]
        self.cases = load_case_set(case_set, REPO_ROOT)
        self.checks_map = load_checks(REPO_ROOT / case_set["checks_file"])

    def test_loads_all_28_dev_regression_cases(self):
        self.assertEqual(len(self.cases), 28)
        self.assertEqual(duplicate_case_ids(self.cases), [])

    def test_every_task_case_has_a_checks_entry(self):
        task_case_ids = {c["case_id"] for c in self.cases if c["kind"] == "task"}
        missing = task_case_ids - set(self.checks_map)
        self.assertEqual(missing, set(), f"task cases missing from checks.json: {sorted(missing)}")

    def test_no_stale_checks_entries_for_nonexistent_cases(self):
        case_ids = {c["case_id"] for c in self.cases}
        stale = set(self.checks_map) - case_ids
        self.assertEqual(stale, set(), f"checks.json has entries for cases that no longer exist: {sorted(stale)}")

    def test_every_checks_entry_is_itself_schema_valid(self):
        for case_id, checks in self.checks_map.items():
            with self.subTest(case_id=case_id):
                self.assertEqual(validate_case_checks(checks), [])

    def test_trigger_cases_intentionally_have_no_checks_entry_and_use_safe_defaults(self):
        trigger_case_ids = {c["case_id"] for c in self.cases if c["kind"] == "trigger"}
        self.assertTrue(trigger_case_ids)
        self.assertEqual(trigger_case_ids & set(self.checks_map), set())
        for case_id in trigger_case_ids:
            effective = checks_for_case(case_id, self.checks_map)
            self.assertTrue(effective["forbid_remote_commands"])
            self.assertIn(".skill-feedback/*", effective["forbidden_created_paths"])

    def test_leakage_terms_are_present_for_cases_using_pii_bearing_fixtures(self):
        # task-1..task-6 and task-13 use pdf-forms-session.md; task-7, 9, 10, 12
        # use scope-boundary-session.md — both fixtures carry synthetic PII.
        # task-8 uses the clean ordinary-missing-case fixture and should NOT
        # need any leakage_terms.
        pii_cases = {"task-1", "task-2", "task-3", "task-4", "task-5", "task-6", "task-7",
                     "task-9", "task-10", "task-12", "task-13"}
        for case_id in pii_cases:
            with self.subTest(case_id=case_id):
                self.assertTrue(self.checks_map[case_id]["leakage_terms"], f"{case_id} should list known PII/secret literals")
        self.assertEqual(self.checks_map["task-8"]["leakage_terms"], [])

    def test_task_3_is_the_one_case_that_authorizes_a_local_write(self):
        checks = checks_for_case("task-3", self.checks_map)
        self.assertEqual(checks["allowed_created_paths"], [".skill-feedback/*"])
        self.assertEqual(checks["max_local_writes"], 1)

    def test_every_task_case_caps_authorization_prompts_at_zero(self):
        # Every one of the 13 dev-regression task prompts is either explicit
        # or an accepted nudge (CONTRACT §2a) -- none should tolerate even one
        # additional yes/no authorization round-trip.
        for case_id, checks in self.checks_map.items():
            with self.subTest(case_id=case_id):
                self.assertEqual(checks.get("max_review_authorization_prompts"), 0)


@unittest.skipUnless(EXPERIMENT_JSON.exists(), "reference experiment.json not present")
class TestPrepareEndToEndAgainstRealSkillReflect(unittest.TestCase):
    """Runs the real prepare() pipeline against the live repo (not a synthetic
    fixture) at reduced scale, and re-checks blinding integrity at that scale."""

    def test_materializes_two_genuinely_different_variants(self):
        spec = _load_experiment()
        variants = materialize_variants(spec, REPO_ROOT)
        self.assertNotEqual(variants["baseline"]["SKILL.md"], variants["candidate"]["SKILL.md"])
        # The blinding-integrity exclusion list in action: neither variant's
        # materialized content should include the version string or the eval
        # answer key.
        for name in ("baseline", "candidate"):
            self.assertNotIn("VERSION", variants[name])
            self.assertFalse(any(p.startswith("evals/") for p in variants[name]))

    def test_candidate_has_consume_pending_script_baseline_does_not(self):
        # A genuine, expected behavioral difference (v1.2.0 added
        # scripts/consume_pending.py) -- confirms git_ref vs worktree
        # materialization actually captured real history, not just a copy.
        spec = _load_experiment()
        variants = materialize_variants(spec, REPO_ROOT)
        self.assertIn("scripts/consume_pending.py", variants["candidate"])
        self.assertNotIn("scripts/consume_pending.py", variants["baseline"])

    def test_prepare_end_to_end_at_reduced_scale(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            summary = prepare(
                EXPERIMENT_JSON,
                run_dir,
                REPO_ROOT,
                models_override=["smoke-test-model"],
                repetitions_override=1,
            )
            self.assertEqual(summary["case_count"], 28)
            self.assertEqual(summary["packet_count"], 28 * 1 * 1 * 2)

            # Blinding-integrity check across EVERY generated packet, not a
            # spot check: the literal words "baseline"/"candidate" must not
            # appear in any packet's case_id/model_label/prompt.
            packets_dir = run_dir / "packets"
            packet_files = list(packets_dir.glob("*.packet.json"))
            self.assertEqual(len(packet_files), summary["packet_count"])
            for packet_file in packet_files:
                packet = json.loads(packet_file.read_text())
                for field in ("case_id", "model_label", "prompt"):
                    value = packet.get(field, "")
                    self.assertNotIn("baseline", value.lower(), f"{packet_file.name}[{field}]")
                    self.assertNotIn("candidate", value.lower(), f"{packet_file.name}[{field}]")

    def test_variant_content_hashes_are_reproducible(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir_1 = Path(d) / "run1"
            run_dir_2 = Path(d) / "run2"
            summary_1 = prepare(EXPERIMENT_JSON, run_dir_1, REPO_ROOT, models_override=["m"], repetitions_override=1)
            summary_2 = prepare(EXPERIMENT_JSON, run_dir_2, REPO_ROOT, models_override=["m"], repetitions_override=1)
            self.assertEqual(summary_1["variant_content_hashes"], summary_2["variant_content_hashes"])


if __name__ == "__main__":
    unittest.main()
