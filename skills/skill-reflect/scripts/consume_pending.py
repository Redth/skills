#!/usr/bin/env python3
"""Consume reviewed skill-reflect pending markers without exposing session ids."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Iterable, Optional

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")


def _default_home() -> Path:
    configured = os.environ.get("SKILL_REFLECT_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".skill-reflect"


def consume_pending(
    session_ids: Iterable[str],
    *,
    home: Optional[Path] = None,
) -> dict[str, int]:
    pending = (home or _default_home()) / "pending"
    result = {"consumed": 0, "missing": 0, "invalid": 0}

    for session_id in dict.fromkeys(session_ids):
        if (
            not isinstance(session_id, str)
            or session_id in {".", ".."}
            or not _SESSION_ID_RE.fullmatch(session_id)
        ):
            result["invalid"] += 1
            continue

        marker_path = pending / f"{session_id}.json"
        if marker_path.is_symlink():
            result["invalid"] += 1
            continue
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            result["missing"] += 1
            continue
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            result["invalid"] += 1
            continue

        if not isinstance(marker, dict) or marker.get("sessionId") != session_id:
            result["invalid"] += 1
            continue

        try:
            marker_path.unlink()
        except FileNotFoundError:
            result["missing"] += 1
        except OSError:
            result["invalid"] += 1
        else:
            result["consumed"] += 1

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consume reviewed pending markers. Output contains counts only."
    )
    parser.add_argument(
        "--session-id",
        action="append",
        required=True,
        dest="session_ids",
        help="Opaque reviewed session id (repeatable)",
    )
    parser.add_argument(
        "--home",
        type=Path,
        help="Override SKILL_REFLECT_HOME (primarily for tests)",
    )
    args = parser.parse_args()

    result = consume_pending(args.session_ids, home=args.home)
    print(json.dumps(result, sort_keys=True))
    return 1 if result["invalid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
