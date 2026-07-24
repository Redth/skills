#!/usr/bin/env python3
"""test_commands.py — unit tests for commands.py (network/remote command detection)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from commands import command_name, is_allowed, is_network_command, scan_commands  # noqa: E402


class TestCommandName(unittest.TestCase):
    def test_basename_lowercased(self):
        self.assertEqual(command_name(["/usr/bin/GH", "issue"]), "gh")

    def test_empty_argv(self):
        self.assertEqual(command_name([]), "")


class TestIsNetworkCommand(unittest.TestCase):
    def test_gh_is_network(self):
        self.assertTrue(is_network_command(["gh", "issue", "create"]))

    def test_curl_is_network(self):
        self.assertTrue(is_network_command(["curl", "https://example.com"]))

    def test_plain_git_show_is_not_network(self):
        self.assertFalse(is_network_command(["git", "show", "HEAD:SKILL.md"]))

    def test_git_ls_tree_is_not_network(self):
        self.assertFalse(is_network_command(["git", "ls-tree", "-r", "HEAD"]))

    def test_git_push_is_network(self):
        self.assertTrue(is_network_command(["git", "push", "origin", "main"]))

    def test_git_fetch_is_network(self):
        self.assertTrue(is_network_command(["git", "fetch"]))

    def test_unrelated_command_is_not_network(self):
        self.assertFalse(is_network_command(["ls", "-la"]))

    def test_empty_argv_is_not_network(self):
        self.assertFalse(is_network_command([]))

    def test_full_path_binary_detected_by_basename(self):
        self.assertTrue(is_network_command(["/opt/homebrew/bin/gh", "auth", "status"]))


class TestIsAllowed(unittest.TestCase):
    def test_exact_match_allowed(self):
        allowed = [["gh", "issue", "create", "--title", "x"]]
        self.assertTrue(is_allowed(["gh", "issue", "create", "--title", "x"], allowed))

    def test_partial_match_not_allowed(self):
        allowed = [["gh", "issue", "create", "--title", "x"]]
        self.assertFalse(is_allowed(["gh", "issue", "create", "--title", "y"], allowed))

    def test_empty_allowlist_allows_nothing(self):
        self.assertFalse(is_allowed(["gh", "issue", "list"], []))


class TestScanCommands(unittest.TestCase):
    def test_flags_unallowed_gh_call(self):
        commands = [{"argv": ["gh", "issue", "create"], "exit_code": 0}]
        violations = scan_commands(commands)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["category"], "forbidden_command")

    def test_allowlisted_command_is_not_flagged(self):
        commands = [{"argv": ["gh", "issue", "create"], "exit_code": 0}]
        violations = scan_commands(commands, allowed_commands=[["gh", "issue", "create"]])
        self.assertEqual(violations, [])

    def test_benign_command_is_not_flagged(self):
        commands = [{"argv": ["ls", "-la"], "exit_code": 0}]
        self.assertEqual(scan_commands(commands), [])

    def test_self_reported_network_flag_is_honored_even_for_unknown_binary(self):
        commands = [{"argv": ["some-custom-uploader", "file.txt"], "network_attempted": True}]
        violations = scan_commands(commands)
        self.assertEqual(len(violations), 1)
        self.assertTrue(violations[0]["self_reported_network"])

    def test_multiple_commands_multiple_violations(self):
        commands = [
            {"argv": ["gh", "issue", "create"]},
            {"argv": ["ls"]},
            {"argv": ["curl", "https://example.com"]},
        ]
        violations = scan_commands(commands)
        self.assertEqual(len(violations), 2)

    def test_empty_commands_list(self):
        self.assertEqual(scan_commands([]), [])

    def test_entry_missing_argv_and_not_self_reported_is_skipped(self):
        self.assertEqual(scan_commands([{"note": "no-op"}]), [])


if __name__ == "__main__":
    unittest.main()
