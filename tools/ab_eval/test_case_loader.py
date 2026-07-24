#!/usr/bin/env python3
"""test_case_loader.py — unit tests for case_loader.py."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from case_loader import (  # noqa: E402
    CaseLoadError,
    checks_for_case,
    duplicate_case_ids,
    load_case_set,
    load_checks,
    load_holdout_file,
    load_task_cases,
    load_trigger_cases,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_REFLECT_EVALS = REPO_ROOT / "skills" / "skill-reflect" / "evals" / "evals.json"
SKILL_REFLECT_TRIGGERS = REPO_ROOT / "skills" / "skill-reflect" / "evals" / "trigger-evals.json"
HOLDOUT_TEMPLATE = (
    REPO_ROOT
    / "tools"
    / "ab_eval"
    / "experiments"
    / "skill-reflect-v1.1.0-vs-v1.2.0"
    / "holdout"
    / "holdout.template.json"
)
SKILL_REFLECT_ROOT = REPO_ROOT / "skills" / "skill-reflect"


class TestLoadTaskCases(unittest.TestCase):
    def test_loads_entries_with_case_id_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tasks_file = root / "evals.json"
            tasks_file.write_text(
                json.dumps(
                    {
                        "skill_name": "x",
                        "evals": [
                            {"id": 1, "prompt": "do a thing", "files": [], "expectations": ["did the thing"]}
                        ],
                    }
                )
            )
            cases = load_task_cases(tasks_file, root)
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["case_id"], "task-1")
            self.assertEqual(cases[0]["kind"], "task")
            self.assertEqual(cases[0]["expectations"], ["did the thing"])

    def test_embeds_fixture_file_content(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "evals" / "files").mkdir(parents=True)
            (root / "evals" / "files" / "fixture.md").write_text("fixture body")
            tasks_file = root / "evals.json"
            tasks_file.write_text(
                json.dumps({"evals": [{"id": 1, "prompt": "p", "files": ["evals/files/fixture.md"]}]})
            )
            cases = load_task_cases(tasks_file, root)
            self.assertEqual(cases[0]["files"], {"evals/files/fixture.md": "fixture body"})

    def test_missing_fixture_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tasks_file = root / "evals.json"
            tasks_file.write_text(json.dumps({"evals": [{"id": 1, "prompt": "p", "files": ["missing.md"]}]}))
            with self.assertRaises(CaseLoadError):
                load_task_cases(tasks_file, root)

    def test_missing_file_raises(self):
        with self.assertRaises(CaseLoadError):
            load_task_cases("/no/such/evals.json", ".")

    def test_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as d:
            tasks_file = Path(d) / "evals.json"
            tasks_file.write_text("not json{{{")
            with self.assertRaises(CaseLoadError):
                load_task_cases(tasks_file, d)

    def test_missing_evals_key_raises(self):
        with tempfile.TemporaryDirectory() as d:
            tasks_file = Path(d) / "evals.json"
            tasks_file.write_text(json.dumps({"skill_name": "x"}))
            with self.assertRaises(CaseLoadError):
                load_task_cases(tasks_file, d)

    def test_entry_missing_prompt_raises(self):
        with tempfile.TemporaryDirectory() as d:
            tasks_file = Path(d) / "evals.json"
            tasks_file.write_text(json.dumps({"evals": [{"id": 1}]}))
            with self.assertRaises(CaseLoadError):
                load_task_cases(tasks_file, d)


class TestLoadTriggerCases(unittest.TestCase):
    def test_loads_entries_1_indexed(self):
        with tempfile.TemporaryDirectory() as d:
            trigger_file = Path(d) / "trigger-evals.json"
            trigger_file.write_text(
                json.dumps([{"query": "a", "should_trigger": True}, {"query": "b", "should_trigger": False}])
            )
            cases = load_trigger_cases(trigger_file)
            self.assertEqual([c["case_id"] for c in cases], ["trigger-1", "trigger-2"])
            self.assertEqual(cases[0]["should_trigger"], True)
            self.assertEqual(cases[1]["should_trigger"], False)
            self.assertEqual(cases[0]["kind"], "trigger")

    def test_not_a_list_raises(self):
        with tempfile.TemporaryDirectory() as d:
            trigger_file = Path(d) / "trigger-evals.json"
            trigger_file.write_text(json.dumps({"should_trigger": True}))
            with self.assertRaises(CaseLoadError):
                load_trigger_cases(trigger_file)

    def test_entry_missing_should_trigger_raises(self):
        with tempfile.TemporaryDirectory() as d:
            trigger_file = Path(d) / "trigger-evals.json"
            trigger_file.write_text(json.dumps([{"query": "a"}]))
            with self.assertRaises(CaseLoadError):
                load_trigger_cases(trigger_file)


class TestLoadChecks(unittest.TestCase):
    def test_none_returns_empty_dict(self):
        self.assertEqual(load_checks(None), {})

    def test_missing_file_raises(self):
        with self.assertRaises(CaseLoadError):
            load_checks("/no/such/checks.json")

    def test_loads_valid_checks(self):
        with tempfile.TemporaryDirectory() as d:
            checks_file = Path(d) / "checks.json"
            checks_file.write_text(json.dumps({"task-1": {"forbid_remote_commands": True}}))
            self.assertEqual(load_checks(checks_file), {"task-1": {"forbid_remote_commands": True}})

    def test_non_object_raises(self):
        with tempfile.TemporaryDirectory() as d:
            checks_file = Path(d) / "checks.json"
            checks_file.write_text(json.dumps(["not", "an", "object"]))
            with self.assertRaises(CaseLoadError):
                load_checks(checks_file)


class TestChecksForCase(unittest.TestCase):
    def test_unknown_case_id_gets_full_defaults(self):
        checks = checks_for_case("task-99", {})
        self.assertEqual(checks["forbid_remote_commands"], True)
        self.assertEqual(checks["max_local_writes"], 0)

    def test_partial_override_merges_with_defaults(self):
        checks_map = {"task-1": {"max_local_writes": 1, "source": "evals.json#1"}}
        checks = checks_for_case("task-1", checks_map)
        self.assertEqual(checks["max_local_writes"], 1)
        self.assertEqual(checks["forbid_remote_commands"], True)  # default retained
        self.assertNotIn("source", checks)  # provenance metadata is not a check

    def test_leakage_terms_override(self):
        checks_map = {"task-1": {"leakage_terms": ["a@b.com"]}}
        checks = checks_for_case("task-1", checks_map)
        self.assertEqual(checks["leakage_terms"], ["a@b.com"])


class TestDuplicateCaseIds(unittest.TestCase):
    def test_no_duplicates(self):
        cases = [{"case_id": "a"}, {"case_id": "b"}]
        self.assertEqual(duplicate_case_ids(cases), [])

    def test_finds_duplicates(self):
        cases = [{"case_id": "a"}, {"case_id": "a"}, {"case_id": "b"}]
        self.assertEqual(duplicate_case_ids(cases), ["a"])


@unittest.skipUnless(SKILL_REFLECT_EVALS.exists(), "skill-reflect evals.json not present in this checkout")
class TestLoadCaseSetAgainstRealSkillReflectEvals(unittest.TestCase):
    """Smoke-tests case loading against the real, current skill-reflect eval suite."""

    def test_loads_all_13_task_cases(self):
        cases = load_task_cases(SKILL_REFLECT_EVALS, SKILL_REFLECT_ROOT)
        self.assertEqual(len(cases), 13)
        self.assertEqual(duplicate_case_ids(cases), [])

    def test_loads_all_15_trigger_cases(self):
        cases = load_trigger_cases(SKILL_REFLECT_TRIGGERS)
        self.assertEqual(len(cases), 15)

    def test_load_case_set_combines_both(self):
        case_set = {
            "tasks_file": str(SKILL_REFLECT_EVALS.relative_to(REPO_ROOT)),
            "trigger_file": str(SKILL_REFLECT_TRIGGERS.relative_to(REPO_ROOT)),
            "fixtures_root": str(SKILL_REFLECT_ROOT.relative_to(REPO_ROOT)),
        }
        cases = load_case_set(case_set, REPO_ROOT)
        self.assertEqual(len(cases), 28)


class TestLoadHoldoutFile(unittest.TestCase):
    """Exercise external holdout loading and keep the public template schema-valid."""

    def test_shipped_holdout_template_matches_loader_schema(self):
        cases = load_holdout_file(HOLDOUT_TEMPLATE)
        self.assertEqual({case["kind"] for case in cases}, {"task", "trigger"})
        self.assertTrue(all(case["case_id"].startswith("holdout-") for case in cases))

    def test_loads_evals_and_trigger_evals_with_holdout_prefixed_ids(self):
        with tempfile.TemporaryDirectory() as d:
            holdout_path = Path(d) / "holdout.json"
            holdout_path.write_text(
                json.dumps(
                    {
                        "evals": [{"id": 1, "prompt": "a held-out task", "expectations": ["x"]}],
                        "trigger_evals": [{"query": "a held-out trigger query", "should_trigger": True}],
                    }
                )
            )
            cases = load_holdout_file(holdout_path)
            self.assertEqual(len(cases), 2)
            case_ids = {c["case_id"] for c in cases}
            self.assertEqual(case_ids, {"holdout-task-1", "holdout-trigger-1"})

    def test_holdout_case_ids_can_never_collide_with_dev_regression_ids(self):
        with tempfile.TemporaryDirectory() as d:
            holdout_path = Path(d) / "holdout.json"
            holdout_path.write_text(json.dumps({"evals": [{"id": 1, "prompt": "p"}]}))
            holdout_cases = load_holdout_file(holdout_path)
            dev_cases = load_task_cases(SKILL_REFLECT_EVALS, SKILL_REFLECT_ROOT) if SKILL_REFLECT_EVALS.exists() else []
            self.assertEqual(
                {c["case_id"] for c in holdout_cases} & {c["case_id"] for c in dev_cases},
                set(),
            )

    def test_fixtures_resolve_relative_to_the_holdout_files_own_directory_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            holdout_dir = Path(d)
            (holdout_dir / "held_out_fixture.md").write_text("private fixture content")
            holdout_path = holdout_dir / "holdout.json"
            holdout_path.write_text(
                json.dumps({"evals": [{"id": 1, "prompt": "p", "files": ["held_out_fixture.md"]}]})
            )
            cases = load_holdout_file(holdout_path)
            self.assertEqual(cases[0]["files"]["held_out_fixture.md"], "private fixture content")

    def test_missing_holdout_file_raises_a_clear_error(self):
        with self.assertRaises(CaseLoadError):
            load_holdout_file("/no/such/private/holdout.json")

    def test_evals_only_holdout_file_is_valid(self):
        with tempfile.TemporaryDirectory() as d:
            holdout_path = Path(d) / "holdout.json"
            holdout_path.write_text(json.dumps({"evals": [{"id": 1, "prompt": "p"}]}))
            cases = load_holdout_file(holdout_path)
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["kind"], "task")

    def test_empty_holdout_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            holdout_path = Path(d) / "holdout.json"
            holdout_path.write_text(json.dumps({"evals": [], "trigger_evals": []}))
            with self.assertRaises(CaseLoadError):
                load_holdout_file(holdout_path)


if __name__ == "__main__":
    unittest.main()
