#!/usr/bin/env python3
"""test_schemas.py — unit tests for schemas.py (malformed-bundle detection)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from schemas import (  # noqa: E402
    SchemaError,
    assert_valid,
    validate_case_checks,
    validate_experiment_spec,
    validate_packet,
    validate_run_bundle,
)


def _valid_experiment() -> dict:
    return {
        "schema_version": 1,
        "experiment_id": "exp-1",
        "seed": 42,
        "models": ["model-a"],
        "repetitions": 2,
        "variants": {
            "baseline": {"label": "v1", "source": {"kind": "worktree", "root": "skills/x"}},
            "candidate": {"label": "v2", "source": {"kind": "worktree", "root": "skills/x"}},
        },
    }


def _valid_packet() -> dict:
    return {
        "schema_version": 1,
        "run_id": "task-1__model-a__rep0__A",
        "experiment_id": "exp-1",
        "case_id": "task-1",
        "kind": "task",
        "model_label": "model-a",
        "repetition": 0,
        "variant_token": "A",
        "variant_content_hash": "sha256:" + "a" * 64,
        "prompt": "Analyze the skill.",
    }


def _valid_bundle() -> dict:
    return {
        "schema_version": 1,
        "run_id": "task-1__model-a__rep0__A",
        "experiment_id": "exp-1",
        "case_id": "task-1",
        "model_label": "model-a",
        "repetition": 0,
        "variant_token": "A",
        "packet_content_hash": "sha256:" + "a" * 64,
        "response_text": "Here are the findings...",
        "trigger_decision": None,
        "metrics": {"tool_call_count": 3, "review_authorization_prompts": 0},
        "filesystem": {
            "before": {},
            "after": {},
            "created": [],
            "modified": [],
            "deleted": [],
        },
        "commands": [],
        "rubric": None,
    }


class TestValidateExperimentSpec(unittest.TestCase):
    def test_valid_spec_has_no_errors(self):
        self.assertEqual(validate_experiment_spec(_valid_experiment()), [])

    def test_not_a_dict(self):
        self.assertTrue(validate_experiment_spec(["not", "a", "dict"]))

    def test_missing_seed(self):
        spec = _valid_experiment()
        del spec["seed"]
        errors = validate_experiment_spec(spec)
        self.assertTrue(any("seed" in e for e in errors))

    def test_missing_variant(self):
        spec = _valid_experiment()
        del spec["variants"]["candidate"]
        errors = validate_experiment_spec(spec)
        self.assertTrue(any("candidate" in e for e in errors))

    def test_bad_variant_source_kind(self):
        spec = _valid_experiment()
        spec["variants"]["baseline"]["source"]["kind"] = "ftp"
        errors = validate_experiment_spec(spec)
        self.assertTrue(any("source.kind" in e for e in errors))

    def test_empty_models_list_rejected(self):
        spec = _valid_experiment()
        spec["models"] = []
        errors = validate_experiment_spec(spec)
        self.assertTrue(any("models" in e for e in errors))

    def test_repetitions_must_be_positive(self):
        spec = _valid_experiment()
        spec["repetitions"] = 0
        errors = validate_experiment_spec(spec)
        self.assertTrue(any("repetitions" in e for e in errors))

    def test_wrong_type_for_seed(self):
        spec = _valid_experiment()
        spec["seed"] = "42"
        errors = validate_experiment_spec(spec)
        self.assertTrue(any("seed" in e for e in errors))


class TestValidatePacket(unittest.TestCase):
    def test_valid_packet_has_no_errors(self):
        self.assertEqual(validate_packet(_valid_packet()), [])

    def test_missing_run_id(self):
        packet = _valid_packet()
        del packet["run_id"]
        errors = validate_packet(packet)
        self.assertTrue(any("run_id" in e for e in errors))

    def test_bad_variant_token(self):
        packet = _valid_packet()
        packet["variant_token"] = "C"
        errors = validate_packet(packet)
        self.assertTrue(any("variant_token" in e for e in errors))

    def test_bad_kind(self):
        packet = _valid_packet()
        packet["kind"] = "unknown"
        errors = validate_packet(packet)
        self.assertTrue(any("kind" in e for e in errors))

    def test_negative_repetition(self):
        packet = _valid_packet()
        packet["repetition"] = -1
        errors = validate_packet(packet)
        self.assertTrue(any("repetition" in e for e in errors))

    def test_blinding_leak_in_case_id_is_rejected(self):
        packet = _valid_packet()
        packet["case_id"] = "task-1-baseline-variant"
        errors = validate_packet(packet)
        self.assertTrue(any("blinding" in e for e in errors))

    def test_variant_vocabulary_in_prompt_is_allowed(self):
        packet = _valid_packet()
        packet["prompt"] = "Run against the candidate version of the skill."
        self.assertEqual(validate_packet(packet), [])

    def test_legitimate_candidate_vocabulary_in_prompt_is_allowed(self):
        packet = _valid_packet()
        packet["prompt"] = "Resolve the unverified skill candidate before reporting provenance."
        self.assertEqual(validate_packet(packet), [])

    def test_real_variant_field_is_rejected(self):
        packet = _valid_packet()
        packet["real_variant"] = "candidate"
        errors = validate_packet(packet)
        self.assertTrue(any("real_variant" in e and "blinding" in e for e in errors))

    def test_case_insensitive_blinding_leak_detection(self):
        packet = _valid_packet()
        packet["model_label"] = "BASELINE-model"
        errors = validate_packet(packet)
        self.assertTrue(any("blinding" in e for e in errors))

    def test_not_a_dict(self):
        self.assertTrue(validate_packet(None))


class TestValidateRunBundle(unittest.TestCase):
    def test_valid_bundle_has_no_errors(self):
        self.assertEqual(validate_run_bundle(_valid_bundle()), [])

    def test_not_a_dict(self):
        self.assertTrue(validate_run_bundle("not a dict"))

    def test_missing_response_text(self):
        bundle = _valid_bundle()
        del bundle["response_text"]
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("response_text" in e for e in errors))

    def test_wrong_type_for_response_text(self):
        bundle = _valid_bundle()
        bundle["response_text"] = 12345
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("response_text" in e for e in errors))

    def test_trigger_decision_must_be_bool_or_none(self):
        bundle = _valid_bundle()
        bundle["trigger_decision"] = "yes"
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("trigger_decision" in e for e in errors))

    def test_negative_metric_rejected(self):
        bundle = _valid_bundle()
        bundle["metrics"]["tool_call_count"] = -5
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("tool_call_count" in e for e in errors))

    def test_metrics_field_wrong_type(self):
        bundle = _valid_bundle()
        bundle["metrics"]["tool_call_count"] = "three"
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("tool_call_count" in e for e in errors))

    def test_filesystem_snapshot_must_be_hash_map(self):
        bundle = _valid_bundle()
        bundle["filesystem"]["before"] = []
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("filesystem.before" in e for e in errors))

    def test_filesystem_before_after_accept_hash_keyed_dict_snapshot(self):
        bundle = _valid_bundle()
        bundle["filesystem"]["before"] = {"a.txt": "1" * 64}
        bundle["filesystem"]["after"] = {"a.txt": "2" * 64}
        bundle["filesystem"]["modified"] = ["a.txt"]
        self.assertEqual(validate_run_bundle(bundle), [])

    def test_filesystem_evidence_is_required(self):
        bundle = _valid_bundle()
        del bundle["filesystem"]
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("filesystem" in e for e in errors))

    def test_missing_before_or_after_snapshot_is_rejected(self):
        bundle = _valid_bundle()
        del bundle["filesystem"]["before"]
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("filesystem.before" in e for e in errors))

    def test_snapshot_hashes_must_be_sha256_hex(self):
        bundle = _valid_bundle()
        bundle["filesystem"]["before"] = {"a.txt": "not-a-sha256"}
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("filesystem.before" in e and "SHA-256" in e for e in errors))

    def test_mismatched_derived_filesystem_diff_is_rejected(self):
        bundle = _valid_bundle()
        bundle["filesystem"]["after"] = {"new.txt": "1" * 64}
        bundle["filesystem"]["created"] = []
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("filesystem.created" in e and "recomputed" in e for e in errors))

    def test_filesystem_created_modified_deleted_must_still_be_lists(self):
        bundle = _valid_bundle()
        bundle["filesystem"]["created"] = {"not": "a-list"}
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("filesystem.created" in e for e in errors))

    def test_commands_entry_must_be_object(self):
        bundle = _valid_bundle()
        bundle["commands"] = ["gh issue create"]
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("commands[0]" in e for e in errors))

    def test_command_evidence_is_required(self):
        bundle = _valid_bundle()
        del bundle["commands"]
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("commands" in e for e in errors))

    def test_packet_content_hash_is_required(self):
        bundle = _valid_bundle()
        del bundle["packet_content_hash"]
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("packet_content_hash" in e for e in errors))

    def test_unsafe_run_id_is_rejected(self):
        bundle = _valid_bundle()
        bundle["run_id"] = "../../escaped"
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("run_id" in e and "safe identifier" in e for e in errors))

    def test_commands_argv_must_be_list(self):
        bundle = _valid_bundle()
        bundle["commands"] = [{"argv": "gh issue create"}]
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("argv" in e for e in errors))

    def test_rubric_expectations_results_must_be_list(self):
        bundle = _valid_bundle()
        bundle["rubric"] = {"expectations_results": "not-a-list"}
        errors = validate_run_bundle(bundle)
        self.assertTrue(any("expectations_results" in e for e in errors))

    def test_multiple_errors_all_reported_at_once(self):
        bundle = {"schema_version": 1}  # missing almost everything
        errors = validate_run_bundle(bundle)
        self.assertGreater(len(errors), 3)


class TestValidateCaseChecks(unittest.TestCase):
    def test_valid_checks(self):
        checks = {
            "leakage_terms": ["a@b.com"],
            "forbidden_created_paths": [".skill-feedback/*"],
            "allowed_created_paths": [],
            "forbid_remote_commands": True,
            "max_local_writes": 0,
            "max_review_authorization_prompts": 0,
        }
        self.assertEqual(validate_case_checks(checks), [])

    def test_not_a_dict(self):
        self.assertTrue(validate_case_checks([1, 2, 3]))

    def test_list_field_wrong_type(self):
        errors = validate_case_checks({"leakage_terms": "not-a-list"})
        self.assertTrue(any("leakage_terms" in e for e in errors))

    def test_forbid_remote_commands_must_be_bool(self):
        errors = validate_case_checks({"forbid_remote_commands": "yes"})
        self.assertTrue(any("forbid_remote_commands" in e for e in errors))

    def test_negative_max_local_writes_rejected(self):
        errors = validate_case_checks({"max_local_writes": -1})
        self.assertTrue(any("max_local_writes" in e for e in errors))

    def test_none_is_allowed_for_max_fields(self):
        self.assertEqual(validate_case_checks({"max_local_writes": None}), [])


class TestAssertValid(unittest.TestCase):
    def test_raises_schema_error_with_joined_message(self):
        with self.assertRaises(SchemaError) as ctx:
            assert_valid(["bad field a", "bad field b"], what="test object")
        self.assertIn("bad field a", str(ctx.exception))
        self.assertIn("bad field b", str(ctx.exception))

    def test_no_raise_when_no_errors(self):
        assert_valid([], what="test object")  # should not raise


if __name__ == "__main__":
    unittest.main()
