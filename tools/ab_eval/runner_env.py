#!/usr/bin/env python3
"""
runner_env.py — build the sandboxed execution environment the runner
contract requires (see tools/ab_eval/README.md §Runner contract).

Every packet must be executed inside an environment built by this module:

  1. A fresh, disposable sandbox directory (nothing from a real project, and
     nothing shared between runs).
  2. `stub_bin/` prepended to PATH, so `gh`/`curl` invocations are
     intercepted (see stub_bin/gh, stub_bin/curl) instead of touching the
     network or spending the operator's real credentials.
  3. `AB_EVAL_CMD_LOG` pointed at a per-run JSONL file the executor should
     read back into the run-bundle's `commands` list via `read_command_log`.

This module has no CLI of its own — it is imported by record_run.py and by
anything else (Arena driver, subagent wrapper) that stands up the sandbox
before handing control to the model under evaluation.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

STUB_BIN_DIR = Path(__file__).parent / "stub_bin"


def build_sandbox_env(cmd_log_path: "str | Path", *, base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return an environment dict with stub_bin/ prepended to PATH and AB_EVAL_CMD_LOG set.

    Pass the result as `env=` to subprocess.run()/Popen() (or export it into
    a shell) when actually invoking the model/agent under evaluation.
    """
    env = dict(base_env if base_env is not None else os.environ)
    existing_path = env.get("PATH", "")
    env["PATH"] = f"{STUB_BIN_DIR}{os.pathsep}{existing_path}" if existing_path else str(STUB_BIN_DIR)
    env["AB_EVAL_CMD_LOG"] = str(cmd_log_path)
    return env


def read_command_log(cmd_log_path: "str | Path") -> List[dict]:
    """Parse the JSONL command log the stub binaries append to.

    Returns entries shaped for a run-bundle's `commands` list: each has
    `argv`, `executed` (True — the stub really did run and log this),
    `network_attempted`, and `exit_code` (always 1: the stub always refuses).
    Missing/empty log files return an empty list (no attempts observed).
    """
    path = Path(cmd_log_path)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        entries.append(
            {
                "argv": raw.get("argv", []),
                "executed": True,
                "exit_code": 1,
                "network_attempted": bool(raw.get("network_attempted", True)),
                "note": f"blocked by ab_eval stub_bin/{raw.get('binary', '?')}",
                "timestamp": raw.get("timestamp"),
            }
        )
    return entries


def materialize_files(files: Dict[str, str], dest_dir: "str | Path") -> None:
    """Write an embedded {relpath: content} file tree out to real files under dest_dir.

    Used to instantiate a blind variant's skill instructions (e.g. from a
    packet's referenced blob) into a directory named after the blind token
    ("variant_A"/"variant_B"), never after the real variant name — that
    naming choice is the caller's, and is what keeps execution itself blind,
    not just the packet JSON.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def fresh_sandbox(parent_dir: "str | Path", name: str = "sandbox") -> Path:
    """Create (or recreate, empty) a disposable sandbox directory under parent_dir."""
    sandbox = Path(parent_dir) / name
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True)
    return sandbox
