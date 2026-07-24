#!/usr/bin/env python3
"""test_runner_env.py — unit tests for runner_env.py and the stub_bin/gh + stub_bin/curl binaries."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from runner_env import build_sandbox_env, fresh_sandbox, materialize_files, read_command_log  # noqa: E402

STUB_BIN_DIR = Path(__file__).parent / "stub_bin"


class TestBuildSandboxEnv(unittest.TestCase):
    def test_prepends_stub_bin_to_path(self):
        env = build_sandbox_env("/tmp/cmdlog.jsonl", base_env={"PATH": "/usr/bin"})
        self.assertTrue(env["PATH"].startswith(str(STUB_BIN_DIR)))
        self.assertIn("/usr/bin", env["PATH"])

    def test_sets_cmd_log_env_var(self):
        env = build_sandbox_env("/tmp/cmdlog.jsonl", base_env={})
        self.assertEqual(env["AB_EVAL_CMD_LOG"], "/tmp/cmdlog.jsonl")

    def test_works_with_no_existing_path(self):
        env = build_sandbox_env("/tmp/cmdlog.jsonl", base_env={})
        self.assertEqual(env["PATH"], str(STUB_BIN_DIR))

    def test_does_not_mutate_base_env(self):
        base = {"PATH": "/usr/bin", "OTHER": "x"}
        build_sandbox_env("/tmp/cmdlog.jsonl", base_env=base)
        self.assertEqual(base["PATH"], "/usr/bin")


class TestStubInterceptionEndToEnd(unittest.TestCase):
    """Proves the stub is actually reachable and logs correctly when PATH is built by runner_env."""

    def test_gh_invocation_is_intercepted_not_executed_for_real(self):
        with tempfile.TemporaryDirectory() as d:
            cmd_log = Path(d) / "cmdlog.jsonl"
            env = build_sandbox_env(cmd_log, base_env={"PATH": "/usr/bin:/bin"})
            proc = subprocess.run(
                ["gh", "issue", "create", "--title", "should not really run"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            entries = read_command_log(cmd_log)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["argv"], ["gh", "issue", "create", "--title", "should not really run"])
            self.assertTrue(entries[0]["network_attempted"])
            self.assertEqual(entries[0]["exit_code"], 1)

    def test_curl_invocation_is_intercepted(self):
        with tempfile.TemporaryDirectory() as d:
            cmd_log = Path(d) / "cmdlog.jsonl"
            env = build_sandbox_env(cmd_log, base_env={"PATH": "/usr/bin:/bin"})
            proc = subprocess.run(
                ["curl", "https://example.com/webhook"], env=env, capture_output=True, text=True
            )
            self.assertNotEqual(proc.returncode, 0)
            entries = read_command_log(cmd_log)
            self.assertEqual(entries[0]["argv"][0], "curl")

    def test_multiple_invocations_all_logged(self):
        with tempfile.TemporaryDirectory() as d:
            cmd_log = Path(d) / "cmdlog.jsonl"
            env = build_sandbox_env(cmd_log, base_env={"PATH": "/usr/bin:/bin"})
            subprocess.run(["gh", "auth", "status"], env=env, capture_output=True, text=True)
            subprocess.run(["gh", "issue", "create"], env=env, capture_output=True, text=True)
            entries = read_command_log(cmd_log)
            self.assertEqual(len(entries), 2)

    def test_benign_command_still_works_normally(self):
        with tempfile.TemporaryDirectory() as d:
            cmd_log = Path(d) / "cmdlog.jsonl"
            env = build_sandbox_env(cmd_log, base_env={"PATH": "/usr/bin:/bin"})
            proc = subprocess.run(["echo", "hello"], env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("hello", proc.stdout)
            self.assertEqual(read_command_log(cmd_log), [])


class TestReadCommandLog(unittest.TestCase):
    def test_missing_file_returns_empty_list(self):
        self.assertEqual(read_command_log("/no/such/cmdlog.jsonl"), [])

    def test_parses_jsonl_lines(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = Path(d) / "cmdlog.jsonl"
            log_path.write_text(
                json.dumps({"argv": ["gh", "issue", "list"], "binary": "gh", "network_attempted": True}) + "\n"
            )
            entries = read_command_log(log_path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["argv"], ["gh", "issue", "list"])
            self.assertIn("stub_bin/gh", entries[0]["note"])

    def test_skips_malformed_lines(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = Path(d) / "cmdlog.jsonl"
            log_path.write_text("not json\n" + json.dumps({"argv": ["gh"], "binary": "gh"}) + "\n")
            entries = read_command_log(log_path)
            self.assertEqual(len(entries), 1)

    def test_ignores_blank_lines(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = Path(d) / "cmdlog.jsonl"
            log_path.write_text("\n\n" + json.dumps({"argv": ["gh"], "binary": "gh"}) + "\n\n")
            entries = read_command_log(log_path)
            self.assertEqual(len(entries), 1)


class TestMaterializeFiles(unittest.TestCase):
    def test_writes_nested_files(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "variant_A"
            materialize_files({"SKILL.md": "hello", "references/notes.md": "world"}, dest)
            self.assertEqual((dest / "SKILL.md").read_text(), "hello")
            self.assertEqual((dest / "references" / "notes.md").read_text(), "world")

    def test_empty_file_tree_creates_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "variant_B"
            materialize_files({}, dest)
            self.assertTrue(dest.is_dir())


class TestFreshSandbox(unittest.TestCase):
    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as d:
            sandbox = fresh_sandbox(d, "s1")
            self.assertTrue(sandbox.is_dir())

    def test_recreates_if_already_exists_with_stale_content(self):
        with tempfile.TemporaryDirectory() as d:
            sandbox = fresh_sandbox(d, "s1")
            (sandbox / "stale.txt").write_text("old")
            sandbox2 = fresh_sandbox(d, "s1")
            self.assertFalse((sandbox2 / "stale.txt").exists())


if __name__ == "__main__":
    unittest.main()
