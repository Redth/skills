#!/usr/bin/env python3
"""
variant_source.py — materialize a skill variant's file contents from a source.

A variant's `source` in experiment.json is one of:

  {"kind": "git_ref",  "ref": "<sha-or-tag>", "root": "skills/x", "include": [...]}
      Reads files at a historical commit via local `git show`/`git ls-tree`
      (no network — this only touches the repo's own local object store).
      This is how the reference skill-reflect experiment pins "v1.1.0" to the
      exact commit before the in-progress v1.2.0 edits, without needing a
      release tag.

  {"kind": "worktree", "root": "skills/x", "include": [...]}
      Reads files directly off disk as they currently exist — this is how the
      reference experiment captures "v1.2.0", including uncommitted changes.

  {"kind": "directory", "root": "/abs/or/relative/path", "include": [...]}
      Reads files from an arbitrary directory — for comparing two skills that
      don't share a git history at all (e.g. two independent forks).

`include` is a safelist of fnmatch globs (relative to `root`); when present,
only matching files are materialized. This is a *blinding* control as much as
a size control: for the packaged skill-reflect experiment it deliberately
excludes `evals/**` and `VERSION` so an executor never sees the eval answer
key or an explicit version string that would give away which blind token
maps to which real variant. See experiments/*/README.md for the specific
list used there.

All materialization returns {relative_path: text_content}; binary or
undecodable files are skipped defensively (skill instructions are always
text) rather than raising, so one stray asset never aborts an entire run.
"""
from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional

_SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", ".venv"}


class VariantSourceError(RuntimeError):
    """Raised when a variant source cannot be resolved (bad ref, missing path, etc.)."""


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def _filter_include(paths: Iterable[str], include: Optional[Iterable[str]]) -> List[str]:
    if not include:
        return list(paths)
    patterns = list(include)
    return [p for p in paths if any(fnmatch.fnmatch(_normalize(p), _normalize(pat)) for pat in patterns)]


def materialize_worktree(repo_root: Path, root: str, include: Optional[Iterable[str]] = None) -> Dict[str, str]:
    """Read files directly from disk under `repo_root/root` (current working tree state)."""
    base = Path(repo_root) / root
    if not base.exists():
        raise VariantSourceError(f"worktree root does not exist: {base}")
    rel_paths = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if any(part in _SKIP_DIR_NAMES for part in rel.parts):
            continue
        rel_paths.append(_normalize(str(rel)))
    files: Dict[str, str] = {}
    for rel in _filter_include(rel_paths, include):
        try:
            files[rel] = (base / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return files


def materialize_directory(root: "str | Path", include: Optional[Iterable[str]] = None) -> Dict[str, str]:
    """Read files from an arbitrary directory path (not necessarily inside the repo)."""
    return _materialize_abs_dir(Path(root), include)


def _materialize_abs_dir(base: Path, include: Optional[Iterable[str]]) -> Dict[str, str]:
    if not base.exists():
        raise VariantSourceError(f"directory does not exist: {base}")
    rel_paths = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if any(part in _SKIP_DIR_NAMES for part in rel.parts):
            continue
        rel_paths.append(_normalize(str(rel)))
    files: Dict[str, str] = {}
    for rel in _filter_include(rel_paths, include):
        try:
            files[rel] = (base / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return files


def _git(repo_root: Path, args: List[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise VariantSourceError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def materialize_git_ref(
    repo_root: Path, ref: str, root: str, include: Optional[Iterable[str]] = None
) -> Dict[str, str]:
    """Read files at a historical git ref via local `git show`/`git ls-tree` — no network."""
    root_norm = root.rstrip("/")
    listing = _git(repo_root, ["ls-tree", "-r", "--name-only", ref, "--", root_norm])
    rel_paths = []
    for line in listing.splitlines():
        line = line.strip()
        if not line:
            continue
        rel = line[len(root_norm) + 1 :] if line.startswith(root_norm + "/") else line
        rel_paths.append(_normalize(rel))
    files: Dict[str, str] = {}
    for rel in _filter_include(rel_paths, include):
        full_path = f"{root_norm}/{rel}"
        try:
            content = _git(repo_root, ["show", f"{ref}:{full_path}"])
        except VariantSourceError:
            continue
        files[rel] = content
    return files


def materialize_source(source: dict, repo_root: "str | Path") -> Dict[str, str]:
    """Dispatch on source['kind'] to the appropriate materialize_* function."""
    repo_root = Path(repo_root)
    kind = source.get("kind")
    include = source.get("include")
    if kind == "git_ref":
        return materialize_git_ref(repo_root, source["ref"], source["root"], include)
    if kind == "worktree":
        return materialize_worktree(repo_root, source["root"], include)
    if kind == "directory":
        root = source["root"]
        base = Path(root)
        if not base.is_absolute():
            base = repo_root / root
        return _materialize_abs_dir(base, include)
    raise VariantSourceError(f"unknown variant source kind: {kind!r}")
