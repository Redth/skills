#!/usr/bin/env python3
"""test_variant_source.py — unit tests for variant_source.py (variant materialization)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from variant_source import (  # noqa: E402
    VariantSourceError,
    materialize_directory,
    materialize_git_ref,
    materialize_source,
    materialize_worktree,
)


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_git_repo(root: Path) -> str:
    """Build a tiny throwaway git repo with two commits; return the first commit's sha."""
    _run(root, "git", "init", "-q")
    _run(root, "git", "config", "user.email", "test@example.invalid")
    _run(root, "git", "config", "user.name", "Test")
    skill_dir = root / "skills" / "x"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("v1 content\n")
    (skill_dir / "VERSION").write_text("1.0.0\n")
    evals_dir = skill_dir / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text('{"evals": []}\n')
    _run(root, "git", "add", "-A")
    _run(root, "git", "commit", "-q", "-m", "v1")
    first_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, check=True
    ).stdout.strip()

    (skill_dir / "SKILL.md").write_text("v2 content (changed)\n")
    (skill_dir / "VERSION").write_text("2.0.0\n")
    _run(root, "git", "add", "-A")
    _run(root, "git", "commit", "-q", "-m", "v2")
    return first_sha


class TestMaterializeWorktree(unittest.TestCase):
    def test_reads_current_disk_content(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "skills" / "x").mkdir(parents=True)
            (root / "skills" / "x" / "SKILL.md").write_text("hello")
            files = materialize_worktree(root, "skills/x")
            self.assertEqual(files, {"SKILL.md": "hello"})

    def test_missing_root_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(VariantSourceError):
                materialize_worktree(Path(d), "does/not/exist")

    def test_include_filter_restricts_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            base = root / "skills" / "x"
            base.mkdir(parents=True)
            (base / "SKILL.md").write_text("a")
            (base / "VERSION").write_text("1.0.0")
            (base / "evals").mkdir()
            (base / "evals" / "evals.json").write_text("{}")
            files = materialize_worktree(root, "skills/x", include=["SKILL.md", "references/*"])
            self.assertEqual(files, {"SKILL.md": "a"})

    def test_skips_dot_git_and_pycache(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            base = root / "skills" / "x"
            base.mkdir(parents=True)
            (base / "SKILL.md").write_text("a")
            (base / "__pycache__").mkdir()
            (base / "__pycache__" / "m.pyc").write_text("x")
            files = materialize_worktree(root, "skills/x")
            self.assertEqual(files, {"SKILL.md": "a"})


class TestMaterializeDirectory(unittest.TestCase):
    def test_reads_arbitrary_absolute_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "notes.md").write_text("hi")
            files = materialize_directory(root)
            self.assertEqual(files, {"notes.md": "hi"})

    def test_missing_directory_raises(self):
        with self.assertRaises(VariantSourceError):
            materialize_directory("/definitely/not/a/real/path/xyz")


@unittest.skipUnless(subprocess.run(["git", "--version"], capture_output=True).returncode == 0, "git not available")
class TestMaterializeGitRef(unittest.TestCase):
    def test_reads_historical_commit_not_current_disk_state(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first_sha = _make_git_repo(root)

            historical = materialize_git_ref(root, first_sha, "skills/x", include=["SKILL.md"])
            self.assertEqual(historical, {"SKILL.md": "v1 content\n"})

            current = materialize_git_ref(root, "HEAD", "skills/x", include=["SKILL.md"])
            self.assertEqual(current, {"SKILL.md": "v2 content (changed)\n"})

    def test_include_excludes_evals_and_version(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first_sha = _make_git_repo(root)
            files = materialize_git_ref(root, first_sha, "skills/x", include=["SKILL.md", "references/*"])
            self.assertEqual(set(files), {"SKILL.md"})
            self.assertNotIn("VERSION", files)
            self.assertNotIn("evals/evals.json", files)

    def test_no_include_returns_everything(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first_sha = _make_git_repo(root)
            files = materialize_git_ref(root, first_sha, "skills/x")
            self.assertIn("VERSION", files)
            self.assertIn("evals/evals.json", files)

    def test_bad_ref_raises(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_git_repo(root)
            with self.assertRaises(VariantSourceError):
                materialize_git_ref(root, "not-a-real-ref-abc123", "skills/x")


class TestMaterializeSource(unittest.TestCase):
    def test_dispatches_to_worktree(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "skills" / "x").mkdir(parents=True)
            (root / "skills" / "x" / "SKILL.md").write_text("hi")
            files = materialize_source({"kind": "worktree", "root": "skills/x"}, root)
            self.assertEqual(files, {"SKILL.md": "hi"})

    def test_dispatches_to_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "notes.md").write_text("hi")
            files = materialize_source({"kind": "directory", "root": str(root)}, root)
            self.assertEqual(files, {"notes.md": "hi"})

    def test_unknown_kind_raises(self):
        with self.assertRaises(VariantSourceError):
            materialize_source({"kind": "ftp"}, ".")


if __name__ == "__main__":
    unittest.main()
