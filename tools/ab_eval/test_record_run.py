#!/usr/bin/env python3
"""test_record_run.py — unit tests for record_run.py (semi-automated run-bundle assembly)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from record_run import cmd_finish, cmd_snapshot  # noqa: E402
from runner_env import build_sandbox_env  # noqa: E402
from schemas import validate_run_bundle  # noqa: E402

RECORD_RUN_PY = Path(__file__).parent / "record_run.py"


def _write_packet(run_dir: Path, run_id: str, **overrides) -> None:
    packet = {
        "run_id": run_id,
        "experiment_id": "exp-1",
        "case_id": "task-1",
        "model_label": "model-a",
        "repetition": 0,
        "variant_token": "A",
        "variant_content_hash": "sha256:" + "a" * 64,
    }
    packet.update(overrides)
    path = run_dir / "packets" / f"{run_id}.packet.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet))


class TestCmdSnapshot(unittest.TestCase):
    def test_writes_hash_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            sandbox = Path(d) / "sandbox"
            sandbox.mkdir()
            (sandbox / "existing.txt").write_text("hello")
            out = Path(d) / "before.json"
            snap = cmd_snapshot(sandbox, out)
            self.assertIn("existing.txt", snap)
            self.assertEqual(json.loads(out.read_text()), snap)


class TestCmdFinish(unittest.TestCase):
    def test_detects_created_file(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _write_packet(run_dir, "task-1__model-a__rep0__A")
            sandbox = Path(d) / "sandbox"
            sandbox.mkdir()
            before = Path(d) / "before.json"
            cmd_snapshot(sandbox, before)

            (sandbox / ".skill-feedback").mkdir()
            (sandbox / ".skill-feedback" / "report.md").write_text("report body")

            response_file = Path(d) / "response.txt"
            response_file.write_text("Here is what happened.")

            result = cmd_finish(
                run_dir, "task-1__model-a__rep0__A", sandbox, before, response_file,
                cmd_log=None, trigger_decision=None, metrics_json=None, executor="test", notes="",
            )
            self.assertEqual(result["created"], [".skill-feedback/report.md"])

            bundle = json.loads((run_dir / "incoming" / "task-1__model-a__rep0__A.json").read_text())
            self.assertEqual(bundle["filesystem"]["created"], [".skill-feedback/report.md"])
            self.assertEqual(validate_run_bundle(bundle), [])

    def test_ingests_command_log(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _write_packet(run_dir, "task-1__model-a__rep0__A")
            sandbox = Path(d) / "sandbox"
            sandbox.mkdir()
            before = Path(d) / "before.json"
            cmd_snapshot(sandbox, before)

            cmd_log = Path(d) / "cmdlog.jsonl"
            env = build_sandbox_env(cmd_log, base_env={"PATH": "/usr/bin:/bin"})
            subprocess.run(["gh", "issue", "create", "--title", "x"], env=env, capture_output=True, text=True)

            response_file = Path(d) / "response.txt"
            response_file.write_text("I attempted to file an issue.")

            result = cmd_finish(
                run_dir, "task-1__model-a__rep0__A", sandbox, before, response_file,
                cmd_log=cmd_log, trigger_decision=None, metrics_json=None, executor="test", notes="",
            )
            self.assertEqual(result["command_count"], 1)
            bundle = json.loads((run_dir / "incoming" / "task-1__model-a__rep0__A.json").read_text())
            self.assertEqual(bundle["commands"][0]["argv"], ["gh", "issue", "create", "--title", "x"])
            self.assertTrue(bundle["commands"][0]["network_attempted"])

    def test_metrics_json_is_merged(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _write_packet(run_dir, "task-1__model-a__rep0__A")
            sandbox = Path(d) / "sandbox"
            sandbox.mkdir()
            before = Path(d) / "before.json"
            cmd_snapshot(sandbox, before)
            response_file = Path(d) / "response.txt"
            response_file.write_text("done")
            metrics_path = Path(d) / "metrics.json"
            metrics_path.write_text(json.dumps({"tool_call_count": 4, "review_authorization_prompts": 0}))

            cmd_finish(
                run_dir, "task-1__model-a__rep0__A", sandbox, before, response_file,
                cmd_log=None, trigger_decision=None, metrics_json=metrics_path, executor="test", notes="",
            )
            bundle = json.loads((run_dir / "incoming" / "task-1__model-a__rep0__A.json").read_text())
            self.assertEqual(bundle["metrics"]["tool_call_count"], 4)

    def test_trigger_decision_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _write_packet(run_dir, "trigger-1__model-a__rep0__A", case_id="trigger-1")
            sandbox = Path(d) / "sandbox"
            sandbox.mkdir()
            before = Path(d) / "before.json"
            cmd_snapshot(sandbox, before)
            response_file = Path(d) / "response.txt"
            response_file.write_text("triggered")

            cmd_finish(
                run_dir, "trigger-1__model-a__rep0__A", sandbox, before, response_file,
                cmd_log=None, trigger_decision=True, metrics_json=None, executor="test", notes="",
            )
            bundle = json.loads((run_dir / "incoming" / "trigger-1__model-a__rep0__A.json").read_text())
            self.assertTrue(bundle["trigger_decision"])

    def test_missing_packet_raises(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            (run_dir / "packets").mkdir(parents=True)
            sandbox = Path(d) / "sandbox"
            sandbox.mkdir()
            before = Path(d) / "before.json"
            cmd_snapshot(sandbox, before)
            response_file = Path(d) / "response.txt"
            response_file.write_text("x")

            with self.assertRaises(FileNotFoundError):
                cmd_finish(
                    run_dir, "no-such-run-id", sandbox, before, response_file,
                    cmd_log=None, trigger_decision=None, metrics_json=None, executor="test", notes="",
                )


class TestCliEndToEnd(unittest.TestCase):
    def test_snapshot_then_finish_full_loop(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d) / "run"
            _write_packet(run_dir, "task-1__model-a__rep0__A")
            sandbox = Path(d) / "sandbox"
            sandbox.mkdir()
            before = Path(d) / "before.json"

            proc1 = subprocess.run(
                [sys.executable, str(RECORD_RUN_PY), "snapshot", "--sandbox-dir", str(sandbox), "--out", str(before)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc1.returncode, 0, msg=proc1.stderr)

            (sandbox / "new_file.md").write_text("new content")
            response_file = Path(d) / "response.txt"
            response_file.write_text("All done.")

            proc2 = subprocess.run(
                [sys.executable, str(RECORD_RUN_PY), "finish",
                 "--run-dir", str(run_dir), "--run-id", "task-1__model-a__rep0__A",
                 "--sandbox-dir", str(sandbox), "--before", str(before),
                 "--response-file", str(response_file), "--executor", "human:tester"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc2.returncode, 0, msg=proc2.stderr)
            bundle_path = run_dir / "incoming" / "task-1__model-a__rep0__A.json"
            self.assertTrue(bundle_path.exists())
            bundle = json.loads(bundle_path.read_text())
            self.assertEqual(bundle["filesystem"]["created"], ["new_file.md"])
            self.assertEqual(bundle["executor"], "human:tester")


if __name__ == "__main__":
    unittest.main()
