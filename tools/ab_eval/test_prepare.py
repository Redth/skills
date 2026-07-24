#!/usr/bin/env python3
"""test_prepare.py — unit tests for prepare.py (packet generation, blinding, reproducibility)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from prepare import build_packets, materialize_variants, prepare  # noqa: E402
from case_loader import checks_for_case  # noqa: E402
from hashing import hash_file_tree  # noqa: E402
from schemas import SchemaError  # noqa: E402

PREPARE_PY = Path(__file__).parent / "prepare.py"
VARIANT_HASHES = {"baseline": "sha256:" + "a" * 64, "candidate": "sha256:" + "b" * 64}


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_fixture_repo(root: Path) -> None:
    """A minimal repo with a toy skill (2 files) and one task + one trigger eval."""
    skill_dir = root / "skills" / "toy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: toy\n---\n# Toy skill\ncurrent behavior\n")
    (skill_dir / "VERSION").write_text("2.0.0\n")
    refs_dir = skill_dir / "references"
    refs_dir.mkdir()
    (refs_dir / "notes.md").write_text("some reference notes")
    evals_dir = skill_dir / "evals"
    (evals_dir / "files").mkdir(parents=True)
    (evals_dir / "files" / "fixture.md").write_text("fixture body with secret@example.com")
    (evals_dir / "evals.json").write_text(
        json.dumps(
            {
                "skill_name": "toy",
                "evals": [
                    {
                        "id": 1,
                        "prompt": "Do the toy task using the fixture.",
                        "files": ["evals/files/fixture.md"],
                        "expectations": ["The output does the toy task"],
                    }
                ],
            }
        )
    )
    (evals_dir / "trigger-evals.json").write_text(
        json.dumps([{"query": "please do the toy thing", "should_trigger": True}])
    )

    checks_path = evals_dir / "checks.json"
    checks_path.write_text(
        json.dumps(
            {
                "task-1": {
                    "leakage_terms": ["secret@example.com"],
                    "forbidden_created_paths": [".toy-out/*"],
                    "max_local_writes": 0,
                    "forbid_remote_commands": True,
                }
            }
        )
    )

    _run(root, "git", "init", "-q")
    _run(root, "git", "config", "user.email", "test@example.invalid")
    _run(root, "git", "config", "user.name", "Test")
    _run(root, "git", "add", "-A")
    _run(root, "git", "commit", "-q", "-m", "baseline")
    baseline_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, check=True
    ).stdout.strip()

    # Candidate = current worktree, with an uncommitted change (mirrors the real
    # skill-reflect scenario: candidate is in-progress, uncommitted work).
    (skill_dir / "SKILL.md").write_text("---\nname: toy\n---\n# Toy skill\nNEW behavior\n")

    return baseline_sha


def _experiment_spec(baseline_sha: str) -> dict:
    return {
        "schema_version": 1,
        "experiment_id": "toy-experiment",
        "seed": 12345,
        "models": ["model-a", "model-b"],
        "repetitions": 2,
        "variants": {
            "baseline": {
                "label": "v1",
                "source": {
                    "kind": "git_ref",
                    "ref": baseline_sha,
                    "root": "skills/toy",
                    "include": ["SKILL.md", "references/*"],
                },
            },
            "candidate": {
                "label": "v2",
                "source": {
                    "kind": "worktree",
                    "root": "skills/toy",
                    "include": ["SKILL.md", "references/*"],
                },
            },
        },
        "case_sets": {
            "dev_regression": {
                "tasks_file": "skills/toy/evals/evals.json",
                "trigger_file": "skills/toy/evals/trigger-evals.json",
                "checks_file": "skills/toy/evals/checks.json",
                "fixtures_root": "skills/toy",
            }
        },
        "holdout": {
            "included": False,
            "import_path_env": "AB_EVAL_TEST_HOLDOUT_FILE",
        },
    }


class TestMaterializeVariants(unittest.TestCase):
    def test_baseline_and_candidate_differ(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            variants = materialize_variants(spec, root)
            self.assertIn("current behavior", variants["baseline"]["SKILL.md"])
            self.assertIn("NEW behavior", variants["candidate"]["SKILL.md"])

    def test_version_and_evals_excluded_by_include_list(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            variants = materialize_variants(spec, root)
            for name in ("baseline", "candidate"):
                self.assertNotIn("VERSION", variants[name])
                self.assertNotIn("evals/evals.json", variants[name])


class TestBuildPackets(unittest.TestCase):
    def _cases(self):
        return [
            {"case_id": "task-1", "kind": "task", "prompt": "do it", "files": {}, "expectations": ["x"]},
            {"case_id": "trigger-1", "kind": "trigger", "prompt": "please", "files": {}, "should_trigger": True},
        ]

    def _spec(self):
        return {
            "experiment_id": "exp",
            "seed": 1,
            "models": ["model-a"],
            "repetitions": 2,
        }

    def test_packet_count_is_cases_times_models_times_reps_times_2_tokens(self):
        packets = build_packets(self._spec(), self._cases(), {}, VARIANT_HASHES)
        self.assertEqual(len(packets), 2 * 1 * 2 * 2)

    def test_every_run_id_is_unique(self):
        packets = build_packets(self._spec(), self._cases(), {}, VARIANT_HASHES)
        run_ids = [p["run_id"] for p in packets]
        self.assertEqual(len(run_ids), len(set(run_ids)))

    def test_no_packet_contains_the_words_baseline_or_candidate(self):
        packets = build_packets(self._spec(), self._cases(), {}, VARIANT_HASHES)
        dumped = json.dumps(packets).lower()
        self.assertNotIn("baseline", dumped)
        self.assertNotIn("candidate", dumped)

    def test_each_case_gets_both_tokens_per_model_rep(self):
        packets = build_packets(self._spec(), self._cases(), {}, VARIANT_HASHES)
        task_packets = [p for p in packets if p["case_id"] == "task-1" and p["repetition"] == 0]
        tokens = sorted(p["variant_token"] for p in task_packets)
        self.assertEqual(tokens, ["A", "B"])

    def test_task_packet_carries_expectations_trigger_packet_does_not(self):
        packets = build_packets(self._spec(), self._cases(), {}, VARIANT_HASHES)
        task_packet = next(p for p in packets if p["case_id"] == "task-1")
        trigger_packet = next(p for p in packets if p["case_id"] == "trigger-1")
        self.assertIn("expectations", task_packet)
        self.assertNotIn("expectations", trigger_packet)
        self.assertIn("should_trigger", trigger_packet)

    def test_checks_are_attached_via_checks_for_case(self):
        checks_map = {"task-1": {"max_local_writes": 5}}
        packets = build_packets(self._spec(), self._cases(), checks_map, VARIANT_HASHES)
        task_packet = next(p for p in packets if p["case_id"] == "task-1")
        self.assertEqual(task_packet["checks"]["max_local_writes"], 5)
        self.assertEqual(task_packet["checks"], checks_for_case("task-1", checks_map))


class TestPrepareEndToEnd(unittest.TestCase):
    def test_prepare_produces_expected_layout(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            exp_path = root / "experiment.json"
            exp_path.write_text(json.dumps(spec))
            run_dir = Path(d) / "run"

            summary = prepare(exp_path, run_dir, root)

            self.assertEqual(summary["case_count"], 2)
            self.assertEqual(summary["packet_count"], 2 * 2 * 2 * 2)  # 2 cases * 2 models * 2 reps * 2 tokens
            self.assertTrue((run_dir / "manifest.json").exists())
            self.assertTrue((run_dir / ".private" / "blinding_key.json").exists())
            packet_files = list((run_dir / "packets").glob("*.packet.json"))
            self.assertEqual(len(packet_files), summary["packet_count"])
            blob_files = list((run_dir / "blobs").glob("*.json"))
            self.assertEqual(len(blob_files), 2)  # exactly baseline + candidate, content-addressed

    def test_reproducible_with_same_seed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            exp_path = root / "experiment.json"
            exp_path.write_text(json.dumps(spec))

            run_dir_1 = Path(d) / "run1"
            run_dir_2 = Path(d) / "run2"
            prepare(exp_path, run_dir_1, root)
            prepare(exp_path, run_dir_2, root)

            manifest_1 = json.loads((run_dir_1 / "manifest.json").read_text())
            manifest_2 = json.loads((run_dir_2 / "manifest.json").read_text())
            self.assertEqual(manifest_1["run_ids"], manifest_2["run_ids"])

            key_1 = json.loads((run_dir_1 / ".private" / "blinding_key.json").read_text())
            key_2 = json.loads((run_dir_2 / ".private" / "blinding_key.json").read_text())
            self.assertEqual(key_1["token_maps"], key_2["token_maps"])
            self.assertEqual(key_1["variant_content_hashes"], key_2["variant_content_hashes"])

    def test_packets_reference_content_addressed_blobs_correctly(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            exp_path = root / "experiment.json"
            exp_path.write_text(json.dumps(spec))
            run_dir = Path(d) / "run"

            prepare(exp_path, run_dir, root)

            blinding_key = json.loads((run_dir / ".private" / "blinding_key.json").read_text())
            candidate_hash = blinding_key["variant_content_hashes"]["candidate"]
            blob_path = run_dir / "blobs" / f"{candidate_hash.split(':', 1)[-1]}.json"
            self.assertTrue(blob_path.exists())
            blob = json.loads(blob_path.read_text())
            self.assertIn("NEW behavior", blob["files"]["SKILL.md"])

    def test_variant_hashes_differ_when_content_differs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            variants = materialize_variants(spec, root)
            self.assertNotEqual(hash_file_tree(variants["baseline"]), hash_file_tree(variants["candidate"]))

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            exp_path = root / "experiment.json"
            exp_path.write_text(json.dumps(spec))
            run_dir = Path(d) / "run"

            proc = subprocess.run(
                [sys.executable, str(PREPARE_PY), "--experiment", str(exp_path), "--run-dir", str(run_dir),
                 "--repo-root", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue((run_dir / "manifest.json").exists())

    def test_repetitions_override_via_cli(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            exp_path = root / "experiment.json"
            exp_path.write_text(json.dumps(spec))
            run_dir = Path(d) / "run"

            proc = subprocess.run(
                [sys.executable, str(PREPARE_PY), "--experiment", str(exp_path), "--run-dir", str(run_dir),
                 "--repo-root", str(root), "--repetitions", "1", "--models", "solo-model"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            manifest = json.loads((run_dir / "manifest.json").read_text())
            self.assertEqual(manifest["repetitions"], 1)
            self.assertEqual(manifest["models"], ["solo-model"])
            # 2 cases * 1 model * 1 rep * 2 tokens
            self.assertEqual(manifest["run_count"], 4)


class TestHoldoutCaseSet(unittest.TestCase):
    ENV_VAR = "AB_EVAL_TEST_HOLDOUT_FILE"

    def tearDown(self):
        os.environ.pop(self.ENV_VAR, None)

    def test_missing_env_var_raises_a_clear_error_not_a_stack_trace(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            exp_path = root / "experiment.json"
            exp_path.write_text(json.dumps(spec))

            with self.assertRaises(SchemaError) as ctx:
                prepare(exp_path, Path(d) / "run", root, case_set_name="holdout")
            self.assertIn(self.ENV_VAR, str(ctx.exception))

    def test_holdout_case_set_loads_from_the_env_var_path_outside_the_repo(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            exp_path = root / "experiment.json"
            exp_path.write_text(json.dumps(spec))

            # The private holdout file lives OUTSIDE `root` entirely.
            private_dir = Path(d) / "private-holdout-location"
            private_dir.mkdir()
            holdout_path = private_dir / "holdout.json"
            holdout_path.write_text(
                json.dumps({"evals": [{"id": 1, "prompt": "a private held-out task"}]})
            )
            os.environ[self.ENV_VAR] = str(holdout_path)

            run_dir = Path(d) / "run"
            summary = prepare(exp_path, run_dir, root, case_set_name="holdout")
            self.assertEqual(summary["case_count"], 1)
            manifest = json.loads((run_dir / "manifest.json").read_text())
            self.assertTrue(all("holdout-task-1" in run_id for run_id in manifest["run_ids"]))

    def test_holdout_path_inside_repo_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            exp_path = root / "experiment.json"
            exp_path.write_text(json.dumps(spec))
            holdout_path = root / "not-private-holdout.json"
            holdout_path.write_text(json.dumps({"evals": [{"id": 1, "prompt": "visible case"}]}))
            os.environ[self.ENV_VAR] = str(holdout_path)

            with self.assertRaisesRegex(SchemaError, "must live outside"):
                prepare(exp_path, Path(d) / "run", root, case_set_name="holdout")

    def test_holdout_sibling_checks_file_is_picked_up_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            baseline_sha = _make_fixture_repo(root)
            spec = _experiment_spec(baseline_sha)
            exp_path = root / "experiment.json"
            exp_path.write_text(json.dumps(spec))

            private_dir = Path(d) / "private-holdout-location"
            private_dir.mkdir()
            holdout_path = private_dir / "holdout.json"
            holdout_path.write_text(json.dumps({"evals": [{"id": 1, "prompt": "p"}]}))
            (private_dir / "holdout.checks.json").write_text(
                json.dumps({"holdout-task-1": {"max_local_writes": 3}})
            )
            os.environ[self.ENV_VAR] = str(holdout_path)

            run_dir = Path(d) / "run"
            prepare(exp_path, run_dir, root, case_set_name="holdout")
            packet_files = list((run_dir / "packets").glob("holdout-task-1__*.packet.json"))
            self.assertTrue(packet_files)
            packet = json.loads(packet_files[0].read_text())
            self.assertEqual(packet["checks"]["max_local_writes"], 3)


if __name__ == "__main__":
    unittest.main()
