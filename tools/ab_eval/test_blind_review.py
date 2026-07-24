#!/usr/bin/env python3
"""test_blind_review.py — unit tests for blind_review.py (pairwise blind preference flow)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from blind_review import build_preference_packets, ingest_preferences  # noqa: E402

BLIND_REVIEW_PY = Path(__file__).parent / "blind_review.py"


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True))


def _setup_pair(run_dir: Path, response_a="response A text", response_b="response B text") -> None:
    _write(
        run_dir / "packets" / "task-1__model-a__rep0__A.packet.json",
        {"run_id": "task-1__model-a__rep0__A", "prompt": "do the task", "case_id": "task-1"},
    )
    _write(
        run_dir / "collected" / "task-1__model-a__rep0__A.json",
        {"run_id": "task-1__model-a__rep0__A", "case_id": "task-1", "model_label": "model-a",
         "repetition": 0, "variant_token": "A", "response_text": response_a},
    )
    _write(
        run_dir / "collected" / "task-1__model-a__rep0__B.json",
        {"run_id": "task-1__model-a__rep0__B", "case_id": "task-1", "model_label": "model-a",
         "repetition": 0, "variant_token": "B", "response_text": response_b},
    )


class TestBuildPreferencePackets(unittest.TestCase):
    def test_builds_packet_for_complete_pair(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _setup_pair(run_dir)
            result = build_preference_packets(run_dir)
            self.assertEqual(result["built_count"], 1)
            pending = list((run_dir / "preference_packets" / "pending").glob("*.json"))
            self.assertEqual(len(pending), 1)
            packet = json.loads(pending[0].read_text())
            self.assertEqual(packet["response_A"], "response A text")
            self.assertEqual(packet["response_B"], "response B text")

    def test_packet_never_mentions_baseline_or_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _setup_pair(run_dir)
            build_preference_packets(run_dir)
            pending = list((run_dir / "preference_packets" / "pending").glob("*.json"))
            dumped = pending[0].read_text().lower()
            self.assertNotIn("baseline", dumped)
            self.assertNotIn("candidate", dumped)

    def test_packet_omits_model_label(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _setup_pair(run_dir)
            build_preference_packets(run_dir)
            packet = json.loads(next((run_dir / "preference_packets" / "pending").glob("*.json")).read_text())
            self.assertNotIn("model_label", packet)

    def test_incomplete_pair_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _write(
                run_dir / "collected" / "task-1__model-a__rep0__A.json",
                {"run_id": "task-1__model-a__rep0__A", "case_id": "task-1", "model_label": "model-a",
                 "repetition": 0, "variant_token": "A", "response_text": "only A"},
            )
            result = build_preference_packets(run_dir)
            self.assertEqual(result["built_count"], 0)

    def test_already_judged_pair_not_rebuilt(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _setup_pair(run_dir)
            build_preference_packets(run_dir)
            pending = list((run_dir / "preference_packets" / "pending").glob("*.json"))
            packet = json.loads(pending[0].read_text())
            pair_id = packet["pair_id"]
            (run_dir / "preference_packets" / "judged").mkdir(parents=True, exist_ok=True)
            judged_path = run_dir / "preference_packets" / "judged" / pending[0].name
            pending[0].rename(judged_path)
            packet["preference"] = "tie"
            judged_path.write_text(json.dumps(packet))

            result = build_preference_packets(run_dir)
            self.assertEqual(result["built_count"], 0)
            self.assertEqual(list((run_dir / "preference_packets" / "pending").glob("*.json")), [])

    def test_force_rebuilds_even_if_judged(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _setup_pair(run_dir)
            build_preference_packets(run_dir)
            pending = list((run_dir / "preference_packets" / "pending").glob("*.json"))
            pair_id = json.loads(pending[0].read_text())["pair_id"]
            (run_dir / "preference_packets" / "judged").mkdir(parents=True, exist_ok=True)
            (run_dir / "preference_packets" / "judged" / f"{pair_id}.pref_packet.json").write_text(
                json.dumps({"pair_id": pair_id})
            )

            result = build_preference_packets(run_dir, force=True)
            self.assertEqual(result["built_count"], 1)


class TestIngestPreferences(unittest.TestCase):
    def test_ingests_valid_judgment(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _setup_pair(run_dir)
            build_preference_packets(run_dir)
            pending = list((run_dir / "preference_packets" / "pending").glob("*.json"))
            packet = json.loads(pending[0].read_text())

            judged_dir = run_dir / "preference_packets" / "judged"
            judged_dir.mkdir(parents=True, exist_ok=True)
            judged = dict(packet)
            judged["preference"] = "A"
            judged["rationale"] = "A was clearer"
            (judged_dir / f"{packet['pair_id']}.json").write_text(json.dumps(judged))

            result = ingest_preferences(run_dir)
            self.assertEqual(result["ingested_count"], 1)
            prefs = json.loads((run_dir / "preferences.json").read_text())
            self.assertEqual(prefs[packet["pair_key"]]["preference"], "A")

    def test_rejects_invalid_preference_value(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            judged_dir = run_dir / "preference_packets" / "judged"
            judged_dir.mkdir(parents=True, exist_ok=True)
            (judged_dir / "bad.json").write_text(
                json.dumps({"pair_id": "x", "pair_key": "k", "preference": "C"})
            )
            result = ingest_preferences(run_dir)
            self.assertEqual(result["ingested_count"], 0)
            self.assertEqual(len(result["invalid"]), 1)

    def test_tie_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            judged_dir = run_dir / "preference_packets" / "judged"
            judged_dir.mkdir(parents=True, exist_ok=True)
            (judged_dir / "t.json").write_text(
                json.dumps({"pair_id": "x", "pair_key": "k", "preference": "tie"})
            )
            result = ingest_preferences(run_dir)
            self.assertEqual(result["ingested_count"], 1)

    def test_ingest_is_cumulative_across_calls(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            judged_dir = run_dir / "preference_packets" / "judged"
            judged_dir.mkdir(parents=True, exist_ok=True)
            (judged_dir / "p1.json").write_text(json.dumps({"pair_id": "p1", "pair_key": "k1", "preference": "A"}))
            ingest_preferences(run_dir)
            (judged_dir / "p2.json").write_text(json.dumps({"pair_id": "p2", "pair_key": "k2", "preference": "B"}))
            result = ingest_preferences(run_dir)
            self.assertEqual(result["total_preferences"], 2)

    def test_cli_build_and_ingest(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _setup_pair(run_dir)
            proc = subprocess.run(
                [sys.executable, str(BLIND_REVIEW_PY), "build", "--run-dir", str(run_dir)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            pending = list((run_dir / "preference_packets" / "pending").glob("*.json"))
            self.assertEqual(len(pending), 1)

            packet = json.loads(pending[0].read_text())
            judged_dir = run_dir / "preference_packets" / "judged"
            judged_dir.mkdir(parents=True, exist_ok=True)
            judged = dict(packet)
            judged["preference"] = "tie"
            (judged_dir / f"{packet['pair_id']}.json").write_text(json.dumps(judged))

            proc2 = subprocess.run(
                [sys.executable, str(BLIND_REVIEW_PY), "ingest", "--run-dir", str(run_dir)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc2.returncode, 0, msg=proc2.stderr)
            self.assertTrue((run_dir / "preferences.json").exists())


if __name__ == "__main__":
    unittest.main()
