#!/usr/bin/env python3
"""
hashing.py — deterministic content hashing for the ab_eval harness.

Every reproducibility guarantee in ab_eval (variant snapshots, packets, blind
tokens) rests on hashing being: (1) stdlib-only, (2) stable across processes
and machines, and (3) stable across dict key order. All functions here are
pure and side-effect free.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def sha256_hexdigest(data: bytes) -> str:
    """Return the sha256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Return the sha256 hex digest of a text string (UTF-8 encoded)."""
    return sha256_hexdigest(text.encode("utf-8"))


def canonical_json(obj: Any) -> str:
    """Serialize obj as JSON with sorted keys and no incidental whitespace.

    This is the single normalization point every hash in this module relies
    on — two logically-equal dicts always produce the same string regardless
    of original key order, which is what makes content hashes reproducible.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def hash_json(obj: Any) -> str:
    """Return a `sha256:<hex>`-prefixed content hash for any JSON-serializable value."""
    return "sha256:" + sha256_text(canonical_json(obj))


def hash_file_tree(files: Mapping[str, str]) -> str:
    """Return a reproducible content hash for a {relative_path: text_content} mapping.

    Used to fingerprint a materialized skill-variant snapshot so two prepare()
    runs against the same source produce an identical hash, and so a tampered
    or drifted run-bundle can be detected by grade.py/collect.py.
    """
    return hash_json({"files": dict(sorted(files.items()))})


def short_hash(value: str, length: int = 12) -> str:
    """Return a short, human-friendly slice of a hash string for filenames/ids."""
    digest = value.split(":", 1)[-1] if ":" in value else value
    return digest[:length]
