#!/usr/bin/env python3
"""test_collect.py — unit tests for collect.py (run-bundle ingestion/validation)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from collect import collect  # noqa: E402

COLLECT_PY = Path(__file__).parent / "collect.py"
CONTENT_HASH = "sha256:" + "a" * 64


def _valid_bundle(run_id: str = "task-1__model-a__rep0__A") -> dict:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "experiment_id": "exp-1",
        "case_id": "task-1",
        "model_label": "model-a",
        "repetition": 0,
        "variant_token": "A",
        "packet_content_hash": CONTENT_HASH,
        "response_text": "the findings are...",
        "filesystem": {
            "before": {},
            "after": {},
            "created": [],
            "modified": [],
            "deleted": [],
        },
        "commands": [],
    }


def _make_run_dir_with_manifest(root: Path, run_ids) -> Path:
    run_dir = root / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({"run_ids": list(run_ids)}))
    packets_dir = run_dir / "packets"
    packets_dir.mkdir()
    for run_id in run_ids:
        parts = run_id.split("__")
        if len(parts) != 4 or not parts[2].startswith("rep") or parts[3] not in ("A", "B"):
            continue
        packet = {
            "run_id": run_id,
            "experiment_id": "exp-1",
            "case_id": parts[0],
            "model_label": parts[1],
            "repetition": int(parts[2][3:]),
            "variant_token": parts[3],
            "variant_content_hash": CONTENT_HASH,
        }
        (packets_dir / f"{run_id}.packet.json").write_text(json.dumps(packet))
    return run_dir


class TestCollect(unittest.TestCase):
    def test_collects_a_valid_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, ["task-1__model-a__rep0__A"])
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "bundle1.json").write_text(json.dumps(_valid_bundle()))

            report = collect(run_dir, [incoming])
            self.assertTrue(report.ok)
            self.assertEqual(report.collected, ["task-1__model-a__rep0__A"])
            self.assertTrue((run_dir / "collected" / "task-1__model-a__rep0__A.json").exists())

    def test_rejects_malformed_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, ["task-1__model-a__rep0__A"])
            incoming = root / "incoming"
            incoming.mkdir()
            bad = _valid_bundle()
            del bad["response_text"]
            (incoming / "bad.json").write_text(json.dumps(bad))

            report = collect(run_dir, [incoming])
            self.assertFalse(report.ok)
            self.assertEqual(report.collected, [])
            self.assertEqual(len(report.invalid), 1)

    def test_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, [])
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "broken.json").write_text("{not json")

            report = collect(run_dir, [incoming])
            self.assertFalse(report.ok)
            self.assertEqual(len(report.invalid), 1)

    def test_rejects_unknown_run_id_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, ["some-other-run-id"])
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "bundle.json").write_text(json.dumps(_valid_bundle()))

            report = collect(run_dir, [incoming])
            self.assertFalse(report.ok)
            self.assertEqual(report.unknown_run_id, ["task-1__model-a__rep0__A"])

    def test_rejects_bundle_metadata_that_does_not_match_packet(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, ["task-1__model-a__rep0__A"])
            incoming = root / "incoming"
            incoming.mkdir()
            bundle = _valid_bundle()
            bundle["model_label"] = "different-model"
            (incoming / "bundle.json").write_text(json.dumps(bundle))

            report = collect(run_dir, [incoming])

            self.assertFalse(report.ok)
            self.assertEqual(report.collected, [])
            self.assertTrue(any("model_label" in error for errors in report.invalid.values() for error in errors))

    def test_rejects_packet_content_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, ["task-1__model-a__rep0__A"])
            incoming = root / "incoming"
            incoming.mkdir()
            bundle = _valid_bundle()
            bundle["packet_content_hash"] = "sha256:" + "b" * 64
            (incoming / "bundle.json").write_text(json.dumps(bundle))

            report = collect(run_dir, [incoming])

            self.assertFalse(report.ok)
            self.assertEqual(report.collected, [])
            self.assertTrue(
                any("packet_content_hash" in error for errors in report.invalid.values() for error in errors)
            )

    def test_rejects_known_run_when_prepared_packet_is_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, ["task-1__model-a__rep0__A"])
            (run_dir / "packets" / "task-1__model-a__rep0__A.packet.json").unlink()
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "bundle.json").write_text(json.dumps(_valid_bundle()))

            report = collect(run_dir, [incoming])

            self.assertFalse(report.ok)
            self.assertEqual(report.collected, [])
            self.assertTrue(any("prepared packet" in error for errors in report.invalid.values() for error in errors))

    def test_allow_unknown_flag_accepts_it_anyway(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, [])
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "bundle.json").write_text(json.dumps(_valid_bundle()))

            report = collect(run_dir, [incoming], allow_unknown=True)
            self.assertTrue(report.ok)
            self.assertEqual(report.collected, ["task-1__model-a__rep0__A"])

    def test_reingesting_identical_bundle_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, ["task-1__model-a__rep0__A"])
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "bundle.json").write_text(json.dumps(_valid_bundle()))

            report1 = collect(run_dir, [incoming])
            report2 = collect(run_dir, [incoming])
            self.assertTrue(report1.ok)
            self.assertTrue(report2.ok)
            self.assertEqual(report2.duplicate, [])

    def test_conflicting_resubmission_flagged_as_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, ["task-1__model-a__rep0__A"])
            incoming1 = root / "incoming1"
            incoming1.mkdir()
            (incoming1 / "bundle.json").write_text(json.dumps(_valid_bundle()))
            collect(run_dir, [incoming1])

            incoming2 = root / "incoming2"
            incoming2.mkdir()
            conflicting = _valid_bundle()
            conflicting["response_text"] = "a completely different response"
            (incoming2 / "bundle.json").write_text(json.dumps(conflicting))
            report2 = collect(run_dir, [incoming2])
            self.assertEqual(report2.duplicate, ["task-1__model-a__rep0__A"])
            self.assertFalse(report2.ok)

    def test_missing_manifest_raises(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = root / "run"
            run_dir.mkdir()
            with self.assertRaises(FileNotFoundError):
                collect(run_dir, [root])

    def test_collect_report_written_to_disk(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, ["task-1__model-a__rep0__A"])
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "bundle.json").write_text(json.dumps(_valid_bundle()))
            collect(run_dir, [incoming])
            self.assertTrue((run_dir / "collect_report.json").exists())

    def test_multiple_bundles_in_one_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(
                root, ["task-1__model-a__rep0__A", "task-1__model-a__rep0__B"]
            )
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "a.json").write_text(json.dumps(_valid_bundle("task-1__model-a__rep0__A")))
            b = _valid_bundle("task-1__model-a__rep0__B")
            b["variant_token"] = "B"
            (incoming / "b.json").write_text(json.dumps(b))

            report = collect(run_dir, [incoming])
            self.assertTrue(report.ok)
            self.assertEqual(sorted(report.collected), ["task-1__model-a__rep0__A", "task-1__model-a__rep0__B"])

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, ["task-1__model-a__rep0__A"])
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "bundle.json").write_text(json.dumps(_valid_bundle()))

            proc = subprocess.run(
                [sys.executable, str(COLLECT_PY), "--run-dir", str(run_dir), "--from", str(incoming)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue((run_dir / "collected" / "task-1__model-a__rep0__A.json").exists())

    def test_cli_exits_nonzero_on_invalid_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_dir = _make_run_dir_with_manifest(root, [])
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "bad.json").write_text(json.dumps({"schema_version": 1}))

            proc = subprocess.run(
                [sys.executable, str(COLLECT_PY), "--run-dir", str(run_dir), "--from", str(incoming)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
