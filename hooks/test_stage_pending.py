#!/usr/bin/env python3
"""Focused automation tests for the Claude and Gemini staging hooks."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLAUDE = _load("claude_stage_pending", ROOT / "hooks" / "stage_pending.py")
GEMINI = _load(
    "gemini_stage_pending",
    ROOT / "integrations" / "adapters" / "gemini-cli" / "stage_pending.py",
)
MODULES = (CLAUDE, GEMINI)


def _config():
    return {
        "scope": {
            "skills": [],
            "excludeSkills": ["skill-reflect", "skill-reflect-auto"],
        },
        "nudge": {"enabled": True, "frictionThreshold": 2},
    }


class StagePendingTests(unittest.TestCase):
    def write_jsonl(self, root: Path, events: list[dict]) -> str:
        path = root / "transcript.jsonl"
        path.write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
        return str(path)

    def test_signatures_use_argument_keys_and_types_only(self):
        for module in MODULES:
            with self.subTest(module=module.__name__):
                first = module._tool_signature(
                    "run",
                    {"command": "TOP-SECRET-ONE", "options": {"timeout": 5}},
                )
                second = module._tool_signature(
                    "run",
                    {"command": "TOP-SECRET-TWO", "options": {"timeout": 10}},
                )
                self.assertEqual(first, second)
                self.assertNotIn("TOP-SECRET", first)
                self.assertNotIn("5", first)
                self.assertNotIn("10", first)

    def test_unsafe_session_ids_are_hashed(self):
        for module in MODULES:
            with self.subTest(module=module.__name__):
                self.assertEqual(
                    module._opaque_session_id("safe-session_123"),
                    "safe-session_123",
                )
                normalized = module._opaque_session_id("../../private/path")
                self.assertRegex(normalized, r"^session-[a-f0-9]{24}$")
                self.assertNotIn("private", normalized)
                self.assertIsNone(module._opaque_session_id(""))

    def test_friction_is_attributed_only_to_latest_skill(self):
        events = [
            {"type": "tool_use", "name": "skill", "input": {"skill": "first-skill"}},
            {"type": "tool_use", "name": "skill", "input": {"skill": "second-skill"}},
            {"type": "tool_use", "name": "run", "input": {"command": "one"}},
            {"type": "tool_use", "name": "run", "input": {"command": "two"}},
            {"type": "tool_use", "name": "run", "input": {"command": "three"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.write_jsonl(Path(tmp), events)
            for module in MODULES:
                with self.subTest(module=module.__name__):
                    skills, friction = module.detect_skills_and_friction(
                        transcript, _config()
                    )
                    self.assertEqual(skills, {"first-skill", "second-skill"})
                    self.assertEqual(friction, {"second-skill": 1})

    def test_attribution_expires_after_bounded_tool_window(self):
        events = [
            {"type": "tool_use", "name": "skill", "input": {"skill": "old-skill"}},
            *[
                {
                    "type": "tool_use",
                    "name": f"tool-{index}",
                    "input": {"value": index},
                }
                for index in range(7)
            ],
            {"type": "tool_result", "is_error": True},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.write_jsonl(Path(tmp), events)
            for module in MODULES:
                with self.subTest(module=module.__name__):
                    skills, friction = module.detect_skills_and_friction(
                        transcript, _config()
                    )
                    self.assertEqual(skills, {"old-skill"})
                    self.assertEqual(friction, {})

    def test_user_correction_prose_is_not_scanned(self):
        events = [
            {"type": "tool_use", "name": "skill", "input": {"skill": "example-skill"}},
            {
                "type": "user",
                "content": "That's wrong. Please fix this and try again.",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.write_jsonl(Path(tmp), events)
            for module in MODULES:
                with self.subTest(module=module.__name__):
                    _, friction = module.detect_skills_and_friction(
                        transcript, _config()
                    )
                    self.assertEqual(friction, {})

    def test_marker_is_explicitly_an_unverified_candidate(self):
        events = [
            {"type": "tool_use", "name": "skill", "input": {"skill": "example-skill"}},
            *[
                {
                    "type": "tool_use",
                    "name": "run",
                    "input": {"command": f"private-value-{index}"},
                }
                for index in range(4)
            ],
        ]
        for module in MODULES:
            with self.subTest(module=module.__name__):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    transcript = self.write_jsonl(root, events)
                    hook_input = {
                        "session_id": "opaque-session-id",
                        "transcript_path": transcript,
                        "cwd": str(root),
                        "reason": "complete",
                    }
                    with (
                        mock.patch.dict(
                            os.environ,
                            {"SKILL_REFLECT_HOME": str(root / "state")},
                        ),
                        mock.patch.object(
                            module.sys,
                            "stdin",
                            io.StringIO(json.dumps(hook_input)),
                        ),
                    ):
                        module.main()

                    marker_path = (
                        root / "state" / "pending" / "opaque-session-id.json"
                    )
                    marker = json.loads(marker_path.read_text(encoding="utf-8"))
                    self.assertIs(marker["candidate"], True)
                    self.assertEqual(marker["skills"], ["example-skill"])
                    self.assertNotIn(str(root), json.dumps(marker))
                    self.assertNotIn("private-value", json.dumps(marker))


if __name__ == "__main__":
    unittest.main(verbosity=2)
