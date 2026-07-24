#!/usr/bin/env python3
"""
schemas.py — structural validation for ab_eval's stable file formats.

Three formats travel between "prepare" (this repo) and "execute" (external —
Arena, a subagent, or a human): the ExperimentSpec (authored by a trainer),
the Packet (machine-generated, handed to the executor), and the RunBundle
(hand-authored or tool-assisted by the executor, handed back).

Every `validate_*` function returns a list of human-readable error strings
(empty list == valid) rather than raising, so callers can report every
problem in one pass instead of a single "first error" — this matters a lot
for `collect.py`, which must not silently accept a malformed run-bundle.
`assert_valid` wraps that pattern for callers that do want an exception.
"""
from __future__ import annotations

import re
from typing import Any, List

from fs_snapshot import diff_snapshots

SCHEMA_VERSION = 1
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_CONTENT_HASH_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
_BLINDED_METADATA_RE = re.compile(r"(?:^|[-_.\s])(baseline|candidate)(?:$|[-_.\s])", re.IGNORECASE)
_FORBIDDEN_VARIANT_FIELDS = {
    "variant",
    "real_variant",
    "variant_name",
    "variant_label",
    "baseline",
    "candidate",
}


class SchemaError(ValueError):
    """Raised by assert_valid() with every validation problem joined into one message."""


def assert_valid(errors: List[str], *, what: str) -> None:
    if errors:
        joined = "; ".join(errors)
        raise SchemaError(f"invalid {what}: {joined}")


def _require_type(obj: Any, key: str, expected_type, errors: List[str], required: bool = True) -> None:
    if key not in obj:
        if required:
            errors.append(f"missing required field '{key}'")
        return
    if not isinstance(obj[key], expected_type):
        errors.append(f"field '{key}' must be {expected_type}, got {type(obj[key]).__name__}")


def _validate_safe_identifier(value: Any, field: str, errors: List[str]) -> None:
    if isinstance(value, str) and not _SAFE_IDENTIFIER_RE.fullmatch(value):
        errors.append(
            f"field '{field}' must be a safe identifier containing only letters, digits, '.', '_', or '-'"
        )


def _validate_content_hash(value: Any, field: str, errors: List[str]) -> None:
    if isinstance(value, str) and not _CONTENT_HASH_RE.fullmatch(value):
        errors.append(f"field '{field}' must be a sha256:<64 hex characters> content hash")


def _validate_snapshot(snapshot: Any, field: str, errors: List[str]) -> bool:
    if not isinstance(snapshot, dict):
        errors.append(f"{field} must be a hash-map object of relative path to SHA-256")
        return False

    valid = True
    for path, digest in snapshot.items():
        normalized = path.replace("\\", "/") if isinstance(path, str) else ""
        unsafe_path = (
            not isinstance(path, str)
            or not path
            or normalized.startswith("/")
            or re.match(r"^[A-Za-z]:/", normalized) is not None
            or ".." in normalized.split("/")
        )
        if unsafe_path:
            errors.append(f"{field} contains unsafe or non-relative path {path!r}")
            valid = False
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            errors.append(f"{field}[{path!r}] must be a 64-character SHA-256 hex digest")
            valid = False
    return valid


def validate_experiment_spec(spec: Any) -> List[str]:
    """Validate an experiment.json document. Returns a list of error strings."""
    errors: List[str] = []
    if not isinstance(spec, dict):
        return ["experiment spec must be a JSON object"]

    _require_type(spec, "schema_version", int, errors)
    _require_type(spec, "experiment_id", str, errors)
    _require_type(spec, "seed", int, errors)
    _require_type(spec, "variants", dict, errors)
    _require_type(spec, "models", list, errors)
    _require_type(spec, "repetitions", int, errors)

    variants = spec.get("variants")
    if isinstance(variants, dict):
        for name in ("baseline", "candidate"):
            if name not in variants:
                errors.append(f"variants.{name} is required")
                continue
            variant = variants[name]
            if not isinstance(variant, dict):
                errors.append(f"variants.{name} must be an object")
                continue
            if "label" not in variant:
                errors.append(f"variants.{name}.label is required")
            source = variant.get("source")
            if not isinstance(source, dict):
                errors.append(f"variants.{name}.source must be an object")
            elif source.get("kind") not in {"git_ref", "worktree", "directory"}:
                errors.append(
                    f"variants.{name}.source.kind must be one of git_ref|worktree|directory, "
                    f"got {source.get('kind')!r}"
                )

    models = spec.get("models")
    if isinstance(models, list):
        if not models:
            errors.append("models must be a non-empty list")
        elif not all(isinstance(m, str) and m for m in models):
            errors.append("models must be a list of non-empty strings")

    repetitions = spec.get("repetitions")
    if isinstance(repetitions, int) and repetitions < 1:
        errors.append("repetitions must be >= 1")

    return errors


def validate_packet(packet: Any) -> List[str]:
    """Validate a prepared packet (the unit handed to an external executor)."""
    errors: List[str] = []
    if not isinstance(packet, dict):
        return ["packet must be a JSON object"]

    for key, typ in (
        ("schema_version", int),
        ("run_id", str),
        ("experiment_id", str),
        ("case_id", str),
        ("kind", str),
        ("model_label", str),
        ("repetition", int),
        ("variant_token", str),
        ("variant_content_hash", str),
        ("prompt", str),
    ):
        _require_type(packet, key, typ, errors)

    if packet.get("variant_token") not in (None, "A", "B"):
        errors.append("variant_token must be 'A' or 'B'")
    if packet.get("kind") not in (None, "task", "trigger"):
        errors.append("kind must be 'task' or 'trigger'")
    if isinstance(packet.get("repetition"), int) and packet["repetition"] < 0:
        errors.append("repetition must be >= 0")
    _validate_safe_identifier(packet.get("run_id"), "run_id", errors)
    _validate_content_hash(packet.get("variant_content_hash"), "variant_content_hash", errors)

    # Metadata remains label-neutral. Free-text prompt/fixture/rubric content
    # may legitimately discuss a skill "candidate"; both variants receive the
    # same case content, so vocabulary there does not reveal the A/B mapping.
    for field in ("case_id", "model_label"):
        value = packet.get(field)
        if isinstance(value, str) and _BLINDED_METADATA_RE.search(value):
            errors.append(f"packet field '{field}' contains a baseline/candidate label — this would break blinding")
    for field in sorted(_FORBIDDEN_VARIANT_FIELDS.intersection(packet)):
        errors.append(f"packet field '{field}' exposes real-variant metadata — this would break blinding")

    return errors


def validate_run_bundle(bundle: Any) -> List[str]:
    """Validate a run-bundle (the unit an executor hands back after running a packet)."""
    errors: List[str] = []
    if not isinstance(bundle, dict):
        return ["run bundle must be a JSON object"]

    for key, typ in (
        ("schema_version", int),
        ("run_id", str),
        ("experiment_id", str),
        ("case_id", str),
        ("model_label", str),
        ("repetition", int),
        ("variant_token", str),
        ("packet_content_hash", str),
        ("response_text", str),
        ("filesystem", dict),
        ("commands", list),
    ):
        _require_type(bundle, key, typ, errors)

    if bundle.get("variant_token") not in (None, "A", "B"):
        errors.append("variant_token must be 'A' or 'B'")
    if isinstance(bundle.get("repetition"), int) and bundle["repetition"] < 0:
        errors.append("repetition must be >= 0")
    _validate_safe_identifier(bundle.get("run_id"), "run_id", errors)
    _validate_content_hash(bundle.get("packet_content_hash"), "packet_content_hash", errors)

    trigger_decision = bundle.get("trigger_decision")
    if trigger_decision is not None and not isinstance(trigger_decision, bool):
        errors.append("trigger_decision must be a boolean or null")

    metrics = bundle.get("metrics", {})
    if metrics is not None and not isinstance(metrics, dict):
        errors.append("metrics must be an object")
    elif isinstance(metrics, dict):
        for key in (
            "tool_call_count",
            "user_turn_count",
            "review_authorization_prompts",
            "duplicate_authorization_prompts",
        ):
            if key in metrics and metrics[key] is not None and not isinstance(metrics[key], int):
                errors.append(f"metrics.{key} must be an integer or null")
            if isinstance(metrics.get(key), int) and metrics[key] < 0:
                errors.append(f"metrics.{key} must be >= 0")
        for key in ("time_to_first_finding_seconds", "elapsed_seconds"):
            if key in metrics and metrics[key] is not None and not isinstance(metrics[key], (int, float)):
                errors.append(f"metrics.{key} must be a number or null")

    filesystem = bundle.get("filesystem")
    if isinstance(filesystem, dict):
        before_valid = _validate_snapshot(filesystem.get("before"), "filesystem.before", errors)
        after_valid = _validate_snapshot(filesystem.get("after"), "filesystem.after", errors)
        derived_valid = True
        for key in ("created", "modified", "deleted"):
            value = filesystem.get(key)
            if value is not None:
                if not isinstance(value, list) or not all(isinstance(path, str) for path in value):
                    errors.append(f"filesystem.{key} must be a list of strings or omitted")
                    derived_valid = False

        if before_valid and after_valid and derived_valid:
            recomputed = diff_snapshots(filesystem["before"], filesystem["after"])
            for key in ("created", "modified", "deleted"):
                reported = filesystem.get(key)
                if reported is not None and sorted(reported) != recomputed[key]:
                    errors.append(
                        f"filesystem.{key} does not match the recomputed hash-snapshot diff "
                        f"(reported={sorted(reported)!r}, recomputed={recomputed[key]!r})"
                    )

    commands = bundle.get("commands")
    if isinstance(commands, list):
        for i, entry in enumerate(commands):
            if not isinstance(entry, dict):
                errors.append(f"commands[{i}] must be an object")
            elif "argv" in entry and (
                not isinstance(entry["argv"], list)
                or not all(isinstance(arg, str) for arg in entry["argv"])
            ):
                errors.append(f"commands[{i}].argv must be a list of strings")

    rubric = bundle.get("rubric")
    if rubric is not None:
        if not isinstance(rubric, dict):
            errors.append("rubric must be an object or null")
        elif "expectations_results" in rubric and not isinstance(rubric["expectations_results"], list):
            errors.append("rubric.expectations_results must be a list")

    return errors


def validate_case_checks(checks: Any) -> List[str]:
    """Validate one entry of checks.json (the deterministic-gate metadata for one case)."""
    errors: List[str] = []
    if not isinstance(checks, dict):
        return ["case checks must be an object"]

    list_fields = ("leakage_terms", "forbidden_created_paths", "allowed_created_paths", "allowed_commands")
    for field in list_fields:
        if field in checks and not isinstance(checks[field], list):
            errors.append(f"{field} must be a list")

    if "forbid_remote_commands" in checks and not isinstance(checks["forbid_remote_commands"], bool):
        errors.append("forbid_remote_commands must be a boolean")

    for field in ("max_local_writes", "max_review_authorization_prompts"):
        if field in checks and checks[field] is not None:
            if not isinstance(checks[field], int) or checks[field] < 0:
                errors.append(f"{field} must be a non-negative integer or null")

    return errors
