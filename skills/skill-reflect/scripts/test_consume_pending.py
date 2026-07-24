#!/usr/bin/env python3
"""Unit tests for consume_pending.py (stdlib unittest)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from consume_pending import consume_pending


class ConsumePendingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.pending = self.home / "pending"
        self.pending.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def write_marker(self, session_id: str, marker_id: str | None = None) -> Path:
        path = self.pending / f"{session_id}.json"
        path.write_text(
            json.dumps(
                {
                    "sessionId": marker_id or session_id,
                    "skills": ["example-skill"],
                    "candidate": True,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_consumes_matching_markers_once(self):
        first = self.write_marker("session-one")
        second = self.write_marker("session-two")

        result = consume_pending(
            ["session-one", "session-two", "session-one"],
            home=self.home,
        )

        self.assertEqual(result, {"consumed": 2, "missing": 0, "invalid": 0})
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())

    def test_rejects_unsafe_or_mismatched_ids(self):
        outside = self.home / "outside.json"
        outside.write_text("keep", encoding="utf-8")
        mismatched = self.write_marker("safe-id", marker_id="different-id")

        result = consume_pending(["../outside", "safe-id"], home=self.home)

        self.assertEqual(result, {"consumed": 0, "missing": 0, "invalid": 2})
        self.assertTrue(outside.exists())
        self.assertTrue(mismatched.exists())

    def test_missing_marker_is_not_an_error(self):
        self.assertEqual(
            consume_pending(["missing-id"], home=self.home),
            {"consumed": 0, "missing": 1, "invalid": 0},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
