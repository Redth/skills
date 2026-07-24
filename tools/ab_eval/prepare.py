#!/usr/bin/env python3
"""
prepare.py — build blinded A/B packets from an experiment spec.

    python3 prepare.py --experiment experiments/<name>/experiment.json \
        --run-dir /tmp/ab-run-1

Produces, under `--run-dir`:

    manifest.json           expected run_ids + case/model/rep/token + variant
                             content hashes. Safe to share with the executor.
    packets/<run_id>.packet.json
                             one per (case, model, repetition, token). Each
                             references a variant blob by content hash only —
                             never by the real variant name. Safe to share.
    blobs/<hash>.json        content-addressed {files: {relpath: content}}
                             for each unique materialized variant. Safe to
                             share (the executor needs it to run the case).
    .private/blinding_key.json
                             the ground-truth token->real-variant map + seed.
                             NOT for the executor or a blind grader — only
                             summarize.py (the final, de-blinding analysis
                             step) should read this.

Re-running prepare.py with the same experiment.json (same seed, same variant
sources, same case files) regenerates byte-identical packets and blobs —
that reproducibility is the point of seeding everything through blinding.py
and hashing.py rather than using unseeded randomness.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent))
from blinding import assign_token_map  # noqa: E402
from case_loader import (  # noqa: E402
    CaseLoadError,
    checks_for_case,
    duplicate_case_ids,
    load_case_set,
    load_checks,
    load_holdout_file,
)
from hashing import hash_file_tree  # noqa: E402
from schemas import SchemaError, assert_valid, validate_experiment_spec, validate_packet  # noqa: E402
from variant_source import VariantSourceError, materialize_source  # noqa: E402

SCHEMA_VERSION = 1


def _repo_root_default() -> Path:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        ).stdout.strip()
        if out:
            return Path(out)
    except Exception:
        pass
    return Path(__file__).resolve().parents[2]


def load_experiment(path: Path) -> dict:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SchemaError(f"experiment file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SchemaError(f"experiment file is not valid JSON: {path}: {exc}") from exc
    assert_valid(validate_experiment_spec(spec), what=f"experiment spec ({path})")
    return spec


def materialize_variants(spec: dict, repo_root: Path) -> Dict[str, Dict[str, str]]:
    """Return {"baseline": {relpath: content}, "candidate": {relpath: content}}."""
    out = {}
    for name in ("baseline", "candidate"):
        source = spec["variants"][name]["source"]
        try:
            out[name] = materialize_source(source, repo_root)
        except VariantSourceError as exc:
            raise SchemaError(f"failed to materialize variant '{name}': {exc}") from exc
        if not out[name]:
            raise SchemaError(f"variant '{name}' materialized zero files — check source config")
    return out


def load_holdout_cases(spec: dict, repo_root: Path) -> "tuple[List[dict], Dict[str, dict]]":
    """Resolve the `--case-set holdout` request via experiment.json's `holdout.import_path_env`.

    True holdouts must never live inside this repository (see
    experiments/*/holdout/README.md) — this function enforces that boundary
    operationally: it only ever reads a path supplied through an environment
    variable, and raises a clear, actionable error (not a stack trace) if
    that variable isn't set, so a trainer can't accidentally fall back to
    some in-repo file and mislabel it "holdout".

    Returns (cases, checks_map). checks_map is loaded from an OPTIONAL sibling
    file named `<holdout>.checks.json` next to the holdout file itself (e.g.
    `/private/holdout.json` -> `/private/holdout.checks.json`), for parity
    with the in-repo dev_regression case set's checks.json. If that sibling
    doesn't exist, holdout cases simply fall back to case_loader.DEFAULT_CHECKS
    (still a real safety net: forbid_remote_commands + forbidden_created_paths).
    """
    holdout_cfg = spec.get("holdout") or {}
    env_var = holdout_cfg.get("import_path_env")
    if not env_var:
        raise SchemaError("experiment spec has no holdout.import_path_env configured — cannot load a holdout case set")
    path_str = os.environ.get(env_var)
    if not path_str:
        raise SchemaError(
            f"--case-set holdout requested but ${env_var} is not set. Holdout cases must live "
            f"outside this repository — set {env_var} to the path of your private holdout file "
            "(see experiments/<name>/holdout/README.md for the boundary and a template)."
        )
    path = Path(path_str)
    try:
        path.resolve().relative_to(Path(repo_root).resolve())
    except ValueError:
        pass
    else:
        raise SchemaError(
            f"${env_var} points inside the repository ({path}); a holdout must live outside "
            "the repository so its cases are not visible to the evaluated skill."
        )
    try:
        cases = load_holdout_file(path)
    except CaseLoadError as exc:
        raise SchemaError(f"failed to load holdout file from ${env_var}={path_str!r}: {exc}") from exc

    checks_map: Dict[str, dict] = {}
    sibling_checks = path.with_suffix("").with_suffix(".checks.json") if path.suffix == ".json" else None
    if sibling_checks and sibling_checks.exists():
        try:
            checks_map = load_checks(sibling_checks)
        except CaseLoadError as exc:
            raise SchemaError(f"failed to load holdout checks file {sibling_checks}: {exc}") from exc
    return cases, checks_map


def build_run_id(case_id: str, model_label: str, repetition: int, token: str) -> str:
    return f"{case_id}__{model_label}__rep{repetition}__{token}"


def build_packets(
    spec: dict,
    cases: List[dict],
    checks_map: Dict[str, dict],
    variant_hashes: Dict[str, str],
) -> List[dict]:
    """Build one packet per (case, model, repetition, token). Pure function — no I/O."""
    experiment_id = spec["experiment_id"]
    seed = spec["seed"]
    models = spec["models"]
    repetitions = spec["repetitions"]

    packets: List[dict] = []
    for case in cases:
        case_checks = checks_for_case(case["case_id"], checks_map)
        for model_label in models:
            for repetition in range(repetitions):
                token_map = assign_token_map(seed, experiment_id, case["case_id"], model_label, repetition)
                for token, real_variant in token_map.items():
                    packet = {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": build_run_id(case["case_id"], model_label, repetition, token),
                        "experiment_id": experiment_id,
                        "case_id": case["case_id"],
                        "kind": case["kind"],
                        "model_label": model_label,
                        "repetition": repetition,
                        "variant_token": token,
                        "variant_content_hash": variant_hashes[real_variant],
                        "prompt": case["prompt"],
                        "files": case.get("files", {}),
                        "checks": case_checks,
                        "runner_contract_version": 1,
                        "instructions_for_executor": (
                            f"Run the assistant as Variant {token} (resolve its skill "
                            "instructions from the blob referenced by variant_content_hash — "
                            "see tools/ab_eval/README.md's runner contract) against `prompt` "
                            "and any embedded `files`, inside the sandboxed environment from "
                            "runner_env.py. Record the result with record_run.py."
                        ),
                    }
                    if case["kind"] == "task":
                        packet["expectations"] = case.get("expectations", [])
                        packet["expected_output"] = case.get("expected_output", "")
                    elif case["kind"] == "trigger":
                        packet["should_trigger"] = case.get("should_trigger")
                    errors = validate_packet(packet)
                    if errors:
                        raise SchemaError(f"generated an invalid packet for {packet.get('run_id')}: {errors}")
                    packets.append(packet)
    return packets


def write_run_dir(run_dir: Path, spec: dict, packets: List[dict], variants: Dict[str, Dict[str, str]],
                   variant_hashes: Dict[str, str], token_maps: Dict[str, Dict[str, str]]) -> None:
    packets_dir = run_dir / "packets"
    blobs_dir = run_dir / "blobs"
    private_dir = run_dir / ".private"
    for d in (packets_dir, blobs_dir, private_dir):
        d.mkdir(parents=True, exist_ok=True)

    for name, content_hash in variant_hashes.items():
        blob_path = blobs_dir / f"{content_hash.split(':', 1)[-1]}.json"
        blob_path.write_text(
            json.dumps({"content_hash": content_hash, "files": variants[name]}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    for packet in packets:
        (packets_dir / f"{packet['run_id']}.packet.json").write_text(
            json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8"
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": spec["experiment_id"],
        "seed": spec["seed"],
        "models": spec["models"],
        "repetitions": spec["repetitions"],
        "variant_content_hashes": {"A_or_B_only": "see .private/blinding_key.json for ground truth"},
        "run_ids": sorted(p["run_id"] for p in packets),
        "run_count": len(packets),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    blinding_key = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": spec["experiment_id"],
        "seed": spec["seed"],
        "warning": (
            "GROUND TRUTH — do not share with an executor or a blind grader. "
            "Only summarize.py (final de-blinding aggregation) should read this file."
        ),
        "variant_content_hashes": variant_hashes,
        "token_maps": token_maps,  # keyed by f"{case_id}|{model_label}|{repetition}"
    }
    (private_dir / "blinding_key.json").write_text(
        json.dumps(blinding_key, indent=2, sort_keys=True), encoding="utf-8"
    )
    (private_dir / "README.md").write_text(
        "# Private\n\n"
        "`blinding_key.json` maps blind tokens (A/B) back to real variant names "
        "(baseline/candidate). Keep this out of anything handed to an executor "
        "or a blind grader — only `summarize.py` needs it, at the very end.\n",
        encoding="utf-8",
    )


def prepare(
    experiment_path: Path,
    run_dir: Path,
    repo_root: Path,
    case_set_name: str = None,
    models_override: List[str] = None,
    repetitions_override: int = None,
    seed_override: int = None,
) -> dict:
    spec = load_experiment(experiment_path)
    if models_override:
        spec["models"] = models_override
    if repetitions_override:
        spec["repetitions"] = repetitions_override
    if seed_override is not None:
        spec["seed"] = seed_override

    case_sets = spec.get("case_sets", {})
    name = case_set_name or (next(iter(case_sets)) if case_sets else None)

    if name == "holdout":
        cases, checks_map = load_holdout_cases(spec, repo_root)
    else:
        if not case_sets:
            raise SchemaError("experiment spec has no case_sets")
        if name not in case_sets:
            raise SchemaError(f"unknown case set {name!r}; available: {sorted(case_sets)} (or 'holdout')")
        case_set = case_sets[name]
        try:
            cases = load_case_set(case_set, repo_root)
        except CaseLoadError as exc:
            raise SchemaError(f"failed to load case set {name!r}: {exc}") from exc
        checks_map = load_checks((Path(repo_root) / case_set["checks_file"]) if case_set.get("checks_file") else None)

    dupes = duplicate_case_ids(cases)
    if dupes:
        raise SchemaError(f"duplicate case_id(s) in case set {name!r}: {dupes}")

    variants = materialize_variants(spec, repo_root)
    variant_hashes = {name_: hash_file_tree(files) for name_, files in variants.items()}

    packets = build_packets(spec, cases, checks_map, variant_hashes)

    token_maps: Dict[str, Dict[str, str]] = {}
    for case in cases:
        for model_label in spec["models"]:
            for repetition in range(spec["repetitions"]):
                key = f"{case['case_id']}|{model_label}|{repetition}"
                token_maps[key] = assign_token_map(spec["seed"], spec["experiment_id"], case["case_id"], model_label, repetition)

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    write_run_dir(run_dir, spec, packets, variants, variant_hashes, token_maps)

    return {
        "case_count": len(cases),
        "packet_count": len(packets),
        "models": spec["models"],
        "repetitions": spec["repetitions"],
        "variant_content_hashes": variant_hashes,
        "run_dir": str(run_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--experiment", required=True, type=Path, help="Path to experiment.json")
    parser.add_argument("--run-dir", required=True, type=Path, help="Output directory for this run")
    parser.add_argument("--repo-root", type=Path, default=None, help="Repo root (default: git toplevel)")
    parser.add_argument(
        "--case-set", default=None,
        help="Name of a case_sets entry to use (default: first), or 'holdout' to load an "
             "external private holdout file via the env var named in experiment.json's "
             "holdout.import_path_env",
    )
    parser.add_argument("--models", default=None, help="Comma-separated model-label override")
    parser.add_argument("--repetitions", type=int, default=None, help="Repetition-count override")
    parser.add_argument("--seed", type=int, default=None, help="Seed override")
    args = parser.parse_args()

    repo_root = args.repo_root or _repo_root_default()
    models_override = args.models.split(",") if args.models else None

    try:
        summary = prepare(
            args.experiment,
            args.run_dir,
            repo_root,
            case_set_name=args.case_set,
            models_override=models_override,
            repetitions_override=args.repetitions,
            seed_override=args.seed,
        )
    except (SchemaError, CaseLoadError, VariantSourceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nprepared {summary['packet_count']} packets for {summary['case_count']} cases "
          f"under {summary['run_dir']}", file=sys.stderr)
    print("hand packets/ + blobs/ + manifest.json to the executor. "
          "KEEP .private/ out of that handoff.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
