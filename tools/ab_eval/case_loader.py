#!/usr/bin/env python3
"""
case_loader.py — turn a skill's evals.json / trigger-evals.json into ab_eval cases.

A "case" is the paired stimulus both variants are run against: the same
prompt and the same embedded fixture-file content (and, for task cases, the
same skill-creator-style `expectations` used later for rubric-based semantic
grading). Cases are intentionally variant-agnostic: `prepare.py` runs the
identical case against both the baseline and candidate skill variant, which
is what makes the resulting deltas meaningful. See
experiments/*/README.md for why this harness does not fork per-variant
expectations even when two versions' correct behavior legitimately differs.

`checks.json` (loaded via `load_checks`) is a separate, hand-authored
companion keyed by case_id — the deterministic safety-gate metadata
(forbidden paths, leakage terms, command rules) that requirement-driven
grading needs and that natural-language `expectations` cannot provide
mechanically. `checks_for_case` fills in conservative defaults for any case
(or any field of a case) the author didn't override.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_CHECKS: Dict = {
    "leakage_terms": [],
    "forbidden_created_paths": [".skill-feedback/*"],
    "allowed_created_paths": [],
    "max_local_writes": 0,
    "forbid_remote_commands": True,
    "allowed_commands": [],
    "max_review_authorization_prompts": None,
}


class CaseLoadError(RuntimeError):
    """Raised for any structurally invalid eval/trigger/checks source file."""


def _task_entries_to_cases(
    entries: List[dict], *, source_label: str, fixtures_root: "str | Path", case_id_prefix: str = "task-"
) -> List[dict]:
    cases = []
    for entry in entries:
        if "id" not in entry or "prompt" not in entry:
            raise CaseLoadError(f"task eval entry missing 'id' or 'prompt': {entry!r}")
        case_id = f"{case_id_prefix}{entry['id']}"
        files: Dict[str, str] = {}
        for rel in entry.get("files", []) or []:
            file_path = Path(fixtures_root) / rel
            try:
                files[rel] = file_path.read_text(encoding="utf-8")
            except FileNotFoundError as exc:
                raise CaseLoadError(f"case {case_id}: fixture file not found: {file_path}") from exc
        cases.append(
            {
                "case_id": case_id,
                "kind": "task",
                "source": f"{source_label}#{entry['id']}",
                "prompt": entry["prompt"],
                "expected_output": entry.get("expected_output", ""),
                "expectations": list(entry.get("expectations", []) or []),
                "files": files,
            }
        )
    return cases


def _trigger_entries_to_cases(entries: List[dict], *, source_label: str, case_id_prefix: str = "trigger-") -> List[dict]:
    cases = []
    for i, entry in enumerate(entries, start=1):
        if "query" not in entry or "should_trigger" not in entry:
            raise CaseLoadError(f"trigger eval entry missing 'query' or 'should_trigger': {entry!r}")
        cases.append(
            {
                "case_id": f"{case_id_prefix}{i}",
                "kind": "trigger",
                "source": f"{source_label}#{i - 1}",
                "prompt": entry["query"],
                "should_trigger": bool(entry["should_trigger"]),
                "files": {},
            }
        )
    return cases


def load_task_cases(tasks_file: "str | Path", fixtures_root: "str | Path") -> List[dict]:
    """Load skill-creator-shaped evals.json task entries as ab_eval cases."""
    tasks_file = Path(tasks_file)
    try:
        data = json.loads(tasks_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CaseLoadError(f"tasks file not found: {tasks_file}") from exc
    except json.JSONDecodeError as exc:
        raise CaseLoadError(f"tasks file is not valid JSON: {tasks_file}: {exc}") from exc

    entries = data.get("evals")
    if not isinstance(entries, list):
        raise CaseLoadError(f"{tasks_file} is missing a top-level 'evals' array")

    return _task_entries_to_cases(entries, source_label=tasks_file.name, fixtures_root=fixtures_root)


def load_trigger_cases(trigger_file: "str | Path") -> List[dict]:
    """Load a trigger-evals.json array ({query, should_trigger}) as ab_eval cases."""
    trigger_file = Path(trigger_file)
    try:
        data = json.loads(trigger_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CaseLoadError(f"trigger file not found: {trigger_file}") from exc
    except json.JSONDecodeError as exc:
        raise CaseLoadError(f"trigger file is not valid JSON: {trigger_file}: {exc}") from exc

    if not isinstance(data, list):
        raise CaseLoadError(f"{trigger_file} must be a top-level JSON array")

    return _trigger_entries_to_cases(data, source_label=trigger_file.name)


def load_holdout_file(path: "str | Path", fixtures_root: "str | Path" = None) -> List[dict]:
    """Load an EXTERNAL holdout file living outside this repository.

    Expected shape: {"evals": [...evals.json-shaped entries...],
    "trigger_evals": [...trigger-evals.json-shaped entries...]}. Either key
    may be omitted. Case ids are prefixed `holdout-` so they can never
    collide with (or be mistaken for) an in-repo dev_regression case id.

    `fixtures_root` defaults to the holdout file's own parent directory, so
    a private holdout fixture file can sit right next to it without needing
    to be inside this repository at all — see experiments/*/holdout/README.md
    for the boundary this function exists to keep.
    """
    path = Path(path)
    if not path.exists():
        raise CaseLoadError(f"holdout file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaseLoadError(f"holdout file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CaseLoadError(f"{path} must be a top-level JSON object with 'evals' and/or 'trigger_evals'")

    resolved_fixtures_root = Path(fixtures_root) if fixtures_root else path.parent

    cases: List[dict] = []
    task_entries = data.get("evals")
    if task_entries:
        if not isinstance(task_entries, list):
            raise CaseLoadError(f"{path}: 'evals' must be a list")
        cases.extend(
            _task_entries_to_cases(
                task_entries, source_label=path.name, fixtures_root=resolved_fixtures_root, case_id_prefix="holdout-task-"
            )
        )
    trigger_entries = data.get("trigger_evals")
    if trigger_entries:
        if not isinstance(trigger_entries, list):
            raise CaseLoadError(f"{path}: 'trigger_evals' must be a list")
        cases.extend(_trigger_entries_to_cases(trigger_entries, source_label=path.name, case_id_prefix="holdout-trigger-"))

    if not cases:
        raise CaseLoadError(f"{path} defines neither 'evals' nor 'trigger_evals' (or both are empty)")
    return cases


def load_case_set(case_set: dict, repo_root: "str | Path") -> List[dict]:
    """Load every case referenced by one `case_sets.<name>` entry of an experiment spec."""
    repo_root = Path(repo_root)
    cases: List[dict] = []
    if case_set.get("tasks_file"):
        fixtures_root = repo_root / case_set.get("fixtures_root", ".")
        cases.extend(load_task_cases(repo_root / case_set["tasks_file"], fixtures_root))
    if case_set.get("trigger_file"):
        cases.extend(load_trigger_cases(repo_root / case_set["trigger_file"]))
    if not cases:
        raise CaseLoadError("case set defines neither 'tasks_file' nor 'trigger_file' (or both are empty)")
    return cases


def load_checks(checks_file: Optional["str | Path"]) -> Dict[str, dict]:
    """Load the checks.json companion file mapping case_id -> deterministic-check overrides."""
    if not checks_file:
        return {}
    path = Path(checks_file)
    if not path.exists():
        raise CaseLoadError(f"checks file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaseLoadError(f"checks file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CaseLoadError(f"{path} must be a top-level JSON object keyed by case_id")
    return data


def checks_for_case(case_id: str, checks_map: Dict[str, dict]) -> dict:
    """Return the effective checks for one case: author overrides merged over DEFAULT_CHECKS."""
    override = checks_map.get(case_id, {})
    merged = dict(DEFAULT_CHECKS)
    merged.update({k: v for k, v in override.items() if k != "source"})
    return merged


def duplicate_case_ids(cases: List[dict]) -> List[str]:
    """Return any case_id that appears more than once (a sign of an authoring mistake)."""
    seen: Dict[str, int] = {}
    for case in cases:
        seen[case["case_id"]] = seen.get(case["case_id"], 0) + 1
    return sorted(cid for cid, count in seen.items() if count > 1)
