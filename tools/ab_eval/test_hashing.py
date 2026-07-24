#!/usr/bin/env python3
"""
test_hashing.py — unit tests for hashing.py

Run from tools/ab_eval/:
    python3 -m unittest -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hashing import (  # noqa: E402
    canonical_json,
    hash_file_tree,
    hash_json,
    sha256_hexdigest,
    sha256_text,
    short_hash,
)


class TestCanonicalJson(unittest.TestCase):
    def test_key_order_does_not_matter(self):
        a = canonical_json({"b": 1, "a": 2})
        b = canonical_json({"a": 2, "b": 1})
        self.assertEqual(a, b)

    def test_nested_key_order_does_not_matter(self):
        a = canonical_json({"outer": {"z": 1, "y": 2}})
        b = canonical_json({"outer": {"y": 2, "z": 1}})
        self.assertEqual(a, b)

    def test_distinct_values_differ(self):
        self.assertNotEqual(canonical_json({"a": 1}), canonical_json({"a": 2}))


class TestSha256(unittest.TestCase):
    def test_text_hash_is_deterministic(self):
        self.assertEqual(sha256_text("hello"), sha256_text("hello"))

    def test_text_hash_matches_bytes_hash(self):
        self.assertEqual(sha256_text("hello"), sha256_hexdigest(b"hello"))

    def test_different_text_differs(self):
        self.assertNotEqual(sha256_text("hello"), sha256_text("hellp"))

    def test_hash_length_is_64_hex_chars(self):
        digest = sha256_text("anything")
        self.assertEqual(len(digest), 64)
        int(digest, 16)  # raises if not valid hex


class TestHashJson(unittest.TestCase):
    def test_prefixed_with_sha256(self):
        self.assertTrue(hash_json({"a": 1}).startswith("sha256:"))

    def test_reordered_keys_hash_identically(self):
        self.assertEqual(hash_json({"a": 1, "b": 2}), hash_json({"b": 2, "a": 1}))

    def test_different_content_hashes_differently(self):
        self.assertNotEqual(hash_json({"a": 1}), hash_json({"a": 2}))


class TestHashFileTree(unittest.TestCase):
    def test_reproducible_across_dict_construction_order(self):
        files_a = {"SKILL.md": "hello", "references/a.md": "world"}
        files_b = {"references/a.md": "world", "SKILL.md": "hello"}
        self.assertEqual(hash_file_tree(files_a), hash_file_tree(files_b))

    def test_content_change_changes_hash(self):
        base = {"SKILL.md": "hello"}
        changed = {"SKILL.md": "hello!"}
        self.assertNotEqual(hash_file_tree(base), hash_file_tree(changed))

    def test_added_file_changes_hash(self):
        base = {"SKILL.md": "hello"}
        more = {"SKILL.md": "hello", "extra.md": "x"}
        self.assertNotEqual(hash_file_tree(base), hash_file_tree(more))

    def test_empty_tree_is_stable(self):
        self.assertEqual(hash_file_tree({}), hash_file_tree({}))


class TestShortHash(unittest.TestCase):
    def test_strips_sha256_prefix(self):
        full = hash_json({"a": 1})
        self.assertEqual(short_hash(full, 8), full.split(":", 1)[1][:8])

    def test_default_length_is_12(self):
        full = hash_json({"a": 1})
        self.assertEqual(len(short_hash(full)), 12)

    def test_handles_bare_digest_without_prefix(self):
        digest = sha256_text("x")
        self.assertEqual(short_hash(digest, 6), digest[:6])


if __name__ == "__main__":
    unittest.main()
