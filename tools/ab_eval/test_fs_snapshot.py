#!/usr/bin/env python3
"""test_fs_snapshot.py — unit tests for fs_snapshot.py (path/side-effect detection)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fs_snapshot import (  # noqa: E402
    diff_paths,
    diff_snapshots,
    matched_paths,
    path_matches_any,
    snapshot_paths,
    snapshot_with_hashes,
    unmatched_paths,
)


class TestSnapshotPaths(unittest.TestCase):
    def test_missing_root_returns_empty(self):
        self.assertEqual(snapshot_paths("/no/such/path/at/all"), [])

    def test_lists_nested_files_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "b.txt").write_text("b")
            (root / "sub").mkdir()
            (root / "sub" / "a.txt").write_text("a")
            paths = snapshot_paths(root)
            self.assertEqual(paths, ["b.txt", "sub/a.txt"])

    def test_does_not_mangle_a_legitimate_dotdir_like_skill_feedback(self):
        # Regression test: a naive `str.lstrip("./")` strips the leading '.'
        # from a real dotdir name (treating "./" as a character set, not a
        # prefix), corrupting ".skill-feedback/report.md" into
        # "skill-feedback/report.md" — silently breaking detection of writes
        # to the exact directory this harness exists to police.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".skill-feedback").mkdir()
            (root / ".skill-feedback" / "report.md").write_text("body")
            self.assertEqual(snapshot_paths(root), [".skill-feedback/report.md"])

    def test_skips_dot_git_and_pycache(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text("ref: x")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "m.pyc").write_text("x")
            (root / "keep.md").write_text("keep")
            self.assertEqual(snapshot_paths(root), ["keep.md"])


class TestSnapshotWithHashes(unittest.TestCase):
    def test_hash_changes_when_content_changes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            f = root / "x.txt"
            f.write_text("v1")
            snap1 = snapshot_with_hashes(root)
            f.write_text("v2")
            snap2 = snapshot_with_hashes(root)
            self.assertNotEqual(snap1["x.txt"], snap2["x.txt"])

    def test_identical_content_hashes_identically(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "x.txt").write_text("same")
            snap1 = snapshot_with_hashes(root)
            (root / "x.txt").write_text("same")
            snap2 = snapshot_with_hashes(root)
            self.assertEqual(snap1, snap2)


class TestDiffPaths(unittest.TestCase):
    def test_created_and_deleted(self):
        before = ["a.md", "b.md"]
        after = ["a.md", "c.md"]
        d = diff_paths(before, after)
        self.assertEqual(d["created"], ["c.md"])
        self.assertEqual(d["deleted"], ["b.md"])
        self.assertEqual(d["modified"], [])

    def test_created_dotdir_path_is_not_mangled(self):
        # Same regression as snapshot_paths(): the created-path list is what
        # grade.py matches against forbidden_created_paths — if the leading
        # dot were stripped here, ".skill-feedback/x.md" would silently stop
        # matching ".skill-feedback/*" checks that assume the real path.
        d = diff_paths([], [".skill-feedback/x.md"])
        self.assertEqual(d["created"], [".skill-feedback/x.md"])

    def test_no_changes(self):
        d = diff_paths(["a.md"], ["a.md"])
        self.assertEqual(d, {"created": [], "deleted": [], "modified": []})

    def test_normalizes_backslashes(self):
        d = diff_paths(["a\\b.md"], ["a/b.md"])
        self.assertEqual(d["created"], [])
        self.assertEqual(d["deleted"], [])


class TestDiffSnapshots(unittest.TestCase):
    def test_detects_modification_via_hash(self):
        before = {"a.md": "hash1"}
        after = {"a.md": "hash2"}
        d = diff_snapshots(before, after)
        self.assertEqual(d["modified"], ["a.md"])
        self.assertEqual(d["created"], [])
        self.assertEqual(d["deleted"], [])

    def test_full_lifecycle(self):
        before = {"kept.md": "h0", "removed.md": "h1"}
        after = {"kept.md": "h0", "added.md": "h2"}
        d = diff_snapshots(before, after)
        self.assertEqual(d["created"], ["added.md"])
        self.assertEqual(d["deleted"], ["removed.md"])
        self.assertEqual(d["modified"], [])


class TestGlobMatching(unittest.TestCase):
    def test_single_star_spans_slashes(self):
        # This is the key property the whole harness relies on: a single '*'
        # behaves like a directory-spanning glob under fnmatch.
        self.assertTrue(path_matches_any(".skill-feedback/2026-x.md", [".skill-feedback/*"]))
        self.assertTrue(
            path_matches_any("sandbox/.skill-feedback/2026-x.md", ["*.skill-feedback/*"])
        )

    def test_no_match_when_outside_pattern(self):
        self.assertFalse(path_matches_any("notes/plan.md", [".skill-feedback/*"]))

    def test_empty_pattern_list_matches_nothing(self):
        self.assertFalse(path_matches_any("anything.md", []))

    def test_unmatched_paths_filters_correctly(self):
        paths = [".skill-feedback/a.md", "src/main.py", ".skill-feedback/b.md"]
        self.assertEqual(unmatched_paths(paths, [".skill-feedback/*"]), ["src/main.py"])

    def test_matched_paths_filters_correctly(self):
        paths = [".skill-feedback/a.md", "src/main.py"]
        self.assertEqual(matched_paths(paths, [".skill-feedback/*"]), [".skill-feedback/a.md"])


if __name__ == "__main__":
    unittest.main()
