#!/usr/bin/env python3
"""
record_run.py — turn raw sandbox evidence into a schema-valid run-bundle.

This is the tool an executor (human, subagent wrapper, or Arena driver runs
between "the model finished" and "hand a run-bundle to collect.py") uses so
they never have to hand-compute a filesystem diff or transcribe the command
log themselves — the two things this harness insists on measuring
mechanically rather than trusting prose about.

    # 1) Before invoking the model, snapshot the empty/starting sandbox:
    python3 record_run.py snapshot --sandbox-dir ./sandbox --out before.json

    # 2) Run the model against the packet's prompt inside that sandbox, with
    #    its environment built by runner_env.build_sandbox_env(...) (so any
    #    gh/curl attempt is intercepted — see stub_bin/).

    # 3) After the model finishes, assemble the run-bundle:
    python3 record_run.py finish --run-dir /tmp/ab-run-1 --run-id <run_id> \
        --sandbox-dir ./sandbox --before before.json \
        --response-file response.txt --cmd-log ./sandbox_cmdlog.jsonl \
        [--trigger-decision true] [--metrics-json metrics.json] \
        [--executor "human:alice"]

`finish` looks up the packet for `--run-id` (to recover experiment_id,
case_id, model_label, repetition, variant_token, and — for trigger cases —
nothing else is inferred automatically; you still must supply
--trigger-decision yourself, since only the executor watching the run knows
whether the skill actually got invoked) and writes a validated run-bundle to
`<run-dir>/incoming/<run_id>.json`, ready for `collect.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from fs_snapshot import diff_snapshots, snapshot_with_hashes  # noqa: E402
from runner_env import read_command_log  # noqa: E402
from schemas import validate_run_bundle  # noqa: E402

SCHEMA_VERSION = 1


def cmd_snapshot(sandbox_dir: Path, out: Path) -> dict:
    snap = snapshot_with_hashes(sandbox_dir)
    Path(out).write_text(json.dumps(snap, indent=2, sort_keys=True), encoding="utf-8")
    return snap


def _load_packet(run_dir: Path, run_id: str) -> dict:
    packet_path = run_dir / "packets" / f"{run_id}.packet.json"
    if not packet_path.exists():
        raise FileNotFoundError(f"no packet found for run_id {run_id!r} under {run_dir}/packets/")
    return json.loads(packet_path.read_text(encoding="utf-8"))


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "y"}


def cmd_finish(
    run_dir: Path,
    run_id: str,
    sandbox_dir: Path,
    before_path: Path,
    response_file: Path,
    cmd_log: Optional[Path],
    trigger_decision: Optional[bool],
    metrics_json: Optional[Path],
    executor: str,
    notes: str,
) -> dict:
    packet = _load_packet(run_dir, run_id)

    before = json.loads(Path(before_path).read_text(encoding="utf-8"))
    after = snapshot_with_hashes(sandbox_dir)
    fs_diff = diff_snapshots(before, after)

    commands = read_command_log(cmd_log) if cmd_log else []

    metrics = {}
    if metrics_json and Path(metrics_json).exists():
        metrics = json.loads(Path(metrics_json).read_text(encoding="utf-8"))

    response_text = Path(response_file).read_text(encoding="utf-8")

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": packet["experiment_id"],
        "case_id": packet["case_id"],
        "model_label": packet["model_label"],
        "repetition": packet["repetition"],
        "variant_token": packet["variant_token"],
        "packet_content_hash": packet.get("variant_content_hash"),
        "response_text": response_text,
        "trigger_decision": trigger_decision,
        "metrics": metrics,
        "filesystem": {
            "sandbox_root": str(sandbox_dir),
            "before": before,
            "after": after,
            "created": fs_diff["created"],
            "modified": fs_diff["modified"],
            "deleted": fs_diff["deleted"],
        },
        "commands": commands,
        "rubric": None,
        "executor": executor,
        "notes": notes,
    }

    errors = validate_run_bundle(bundle)
    if errors:
        raise ValueError(f"assembled run-bundle for {run_id} is invalid: {errors}")

    incoming_dir = Path(run_dir) / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    out_path = incoming_dir / f"{run_id}.json"
    out_path.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    return {"written": str(out_path), "created": fs_diff["created"], "modified": fs_diff["modified"],
            "deleted": fs_diff["deleted"], "command_count": len(commands)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)

    p_snap = sub.add_parser("snapshot", help="Snapshot a sandbox directory's file hashes")
    p_snap.add_argument("--sandbox-dir", required=True, type=Path)
    p_snap.add_argument("--out", required=True, type=Path)

    p_finish = sub.add_parser("finish", help="Assemble a validated run-bundle from sandbox evidence")
    p_finish.add_argument("--run-dir", required=True, type=Path)
    p_finish.add_argument("--run-id", required=True)
    p_finish.add_argument("--sandbox-dir", required=True, type=Path)
    p_finish.add_argument("--before", required=True, type=Path, help="Path to the snapshot written by `snapshot`")
    p_finish.add_argument("--response-file", required=True, type=Path, help="Text file containing the model's response")
    p_finish.add_argument("--cmd-log", type=Path, default=None, help="AB_EVAL_CMD_LOG path from the sandbox run")
    p_finish.add_argument("--trigger-decision", default=None, help="true/false — only meaningful for trigger-kind cases")
    p_finish.add_argument("--metrics-json", type=Path, default=None, help="JSON file with tool_call_count etc.")
    p_finish.add_argument("--executor", default="unspecified")
    p_finish.add_argument("--notes", default="")

    args = parser.parse_args()

    try:
        if args.action == "snapshot":
            snap = cmd_snapshot(args.sandbox_dir, args.out)
            print(json.dumps({"snapshot_path": str(args.out), "file_count": len(snap)}, indent=2))
        else:
            result = cmd_finish(
                args.run_dir,
                args.run_id,
                args.sandbox_dir,
                args.before,
                args.response_file,
                args.cmd_log,
                _parse_bool(args.trigger_decision),
                args.metrics_json,
                args.executor,
                args.notes,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
