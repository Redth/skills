#!/usr/bin/env python3
"""
fs_snapshot.py — deterministic before/after filesystem evidence.

CONTRACT (see tools/ab_eval/README.md): "Never rely only on output prose to
assert that no side effect happened." This module gives the harness an
independent, mechanical way to know what files a run actually created,
modified, or deleted inside its sandbox — regardless of what the transcript
claims.

The runner contract asks the executor to snapshot the sandbox directory
*before* handing control to the model and *again after* it finishes; both
snapshots travel in the run-bundle's `filesystem` block. `diff_snapshots`
(hash-aware) turns that pair into created/modified/deleted sets that grade.py
checks against each case's `forbidden_created_paths` /
`allowed_created_paths` globs. `diff_paths` remains a utility for local
listing comparisons, but schema-valid run-bundles require hash snapshots.
"""
from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Union

_SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", ".venv"}


def _normalize(path: str) -> str:
    """Convert backslashes to '/' and strip a literal './' PREFIX (not a character set).

    `str.lstrip("./")` is a classic trap here: it strips any leading run of
    '.' or '/' characters, which corrupts a genuine dotfile/dotdir path like
    '.skill-feedback/report.md' into 'skill-feedback/report.md'. That
    directory is exactly what this harness exists to watch, so this helper
    only removes a real './' two-character prefix, repeated if doubled
    (e.g. './/foo' or './/./foo'), and leaves every other leading dot alone.
    """
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def snapshot_paths(root: Union[str, Path]) -> List[str]:
    """Return a sorted list of file paths relative to root (paths only, no content)."""
    root = Path(root)
    if not root.exists():
        return []
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in p.relative_to(root).parts):
            continue
        out.append(_normalize(str(p.relative_to(root))))
    return sorted(out)


def snapshot_with_hashes(root: Union[str, Path]) -> Dict[str, str]:
    """Return {relative_path: sha256_hex} for every file under root.

    Hashing lets diff_snapshots() distinguish a genuinely *modified* file
    from one that was merely touched/rewritten with identical content.
    """
    root = Path(root)
    out: Dict[str, str] = {}
    for rel in snapshot_paths(root):
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        out[rel] = hashlib.sha256(data).hexdigest()
    return out


def diff_paths(before: Iterable[str], after: Iterable[str]) -> Dict[str, List[str]]:
    """Compute created/deleted sets from two path listings (no modification detection)."""
    b, a = {_normalize(p) for p in before}, {_normalize(p) for p in after}
    return {
        "created": sorted(a - b),
        "deleted": sorted(b - a),
        "modified": [],
    }


def diff_snapshots(before: Mapping[str, str], after: Mapping[str, str]) -> Dict[str, List[str]]:
    """Compute created/modified/deleted sets from two {path: hash} snapshots."""
    b_paths, a_paths = set(before), set(after)
    created = sorted(a_paths - b_paths)
    deleted = sorted(b_paths - a_paths)
    modified = sorted(p for p in (b_paths & a_paths) if before[p] != after[p])
    return {"created": created, "modified": modified, "deleted": deleted}


def path_matches_any(path: str, patterns: Iterable[str]) -> bool:
    """True if `path` matches any glob in `patterns`.

    Uses fnmatch, whose '*' already spans path separators (it is a plain text
    glob, not a POSIX-path-aware one) — so a single '*' behaves like '**' and
    patterns like ".skill-feedback/*" match ".skill-feedback/2026-x.md" and
    "sandbox/.skill-feedback/2026-x.md" alike.
    """
    norm = _normalize(path)
    return any(fnmatch.fnmatch(norm, _normalize(pat)) for pat in patterns)


def unmatched_paths(paths: Iterable[str], allowed_patterns: Iterable[str]) -> List[str]:
    """Return every path in `paths` that does NOT match any of `allowed_patterns`."""
    allowed = list(allowed_patterns)
    return [p for p in paths if not path_matches_any(p, allowed)]


def matched_paths(paths: Iterable[str], patterns: Iterable[str]) -> List[str]:
    """Return every path in `paths` that DOES match at least one of `patterns`."""
    pats = list(patterns)
    return [p for p in paths if path_matches_any(p, pats)]
