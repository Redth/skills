#!/usr/bin/env python3
"""
blind_review.py — pairwise blind preference packets.

    python3 blind_review.py build  --run-dir /tmp/ab-run-1
    python3 blind_review.py ingest --run-dir /tmp/ab-run-1

`build` finds every (case, model, repetition) that has BOTH tokens (A and B)
collected and not yet judged, and writes one preference packet per pair with
the two responses labeled only "A" and "B" — never "baseline"/"candidate",
and the packet omits model_label/case metadata beyond the case prompt so a
grader's judgment can't be swayed by knowing which model or case family
they're looking at. `ingest` reads back judged packets (`{"preference":
"A"|"B"|"tie", "rationale": "..."}`) into `preferences.json`, keyed by pair
key. De-blinding (turning "A"/"B" into "baseline"/"candidate" win counts)
happens later, in aggregate.py/summarize.py — never here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent))
from aggregate import pair_key  # noqa: E402

SCHEMA_VERSION = 1


def _load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _judged_pair_ids(judged_dir: Path) -> set:
    ids = set()
    for path in judged_dir.glob("*.json"):
        try:
            payload = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        pair_id = payload.get("pair_id") if isinstance(payload, dict) else None
        if isinstance(pair_id, str) and pair_id:
            ids.add(pair_id)
    return ids


def _load_collected_by_pair(run_dir: Path) -> Dict[str, Dict[str, dict]]:
    pairs: Dict[str, Dict[str, dict]] = {}
    for path in sorted((run_dir / "collected").glob("*.json")):
        bundle = _load_json(path)
        key = pair_key(bundle)
        pairs.setdefault(key, {})[bundle["variant_token"]] = bundle
    return pairs


def build_preference_packets(run_dir: Path, *, force: bool = False) -> dict:
    run_dir = Path(run_dir)
    pending_dir = run_dir / "preference_packets" / "pending"
    judged_dir = run_dir / "preference_packets" / "judged"
    pending_dir.mkdir(parents=True, exist_ok=True)
    judged_dir.mkdir(parents=True, exist_ok=True)

    already_judged = _judged_pair_ids(judged_dir)
    packets = _load_json_packets_by_run_id(run_dir)

    written = []
    for key, tokens in sorted(_load_collected_by_pair(run_dir).items()):
        if "A" not in tokens or "B" not in tokens:
            continue
        pair_id = key.replace("|", "__").replace(" ", "_")
        if not force and pair_id in already_judged:
            continue
        case_prompt = (packets.get(tokens["A"]["run_id"]) or {}).get("prompt", "")
        pref_packet = {
            "schema_version": SCHEMA_VERSION,
            "pair_id": pair_id,
            "pair_key": key,
            "case_prompt": case_prompt,
            "response_A": tokens["A"].get("response_text", ""),
            "response_B": tokens["B"].get("response_text", ""),
            "instructions_for_grader": (
                "You are comparing two anonymous responses to the SAME prompt, produced by two "
                "different (unlabeled) skill instructions. Judge only on the response quality "
                "criteria your task specifies (e.g. correctness, unauthorized side effects, "
                "unnecessary friction). Preserve the SAME pair_id and pair_key, and add top-level fields "
                "{\"preference\": \"A\"|\"B\"|\"tie\", \"rationale\": <short note>}. "
                "Do not guess which underlying variant produced which response."
            ),
        }
        (pending_dir / f"{pair_id}.pref_packet.json").write_text(
            json.dumps(pref_packet, indent=2, sort_keys=True), encoding="utf-8"
        )
        written.append(pair_id)
    return {"built": written, "built_count": len(written)}


def _load_json_packets_by_run_id(run_dir: Path) -> Dict[str, dict]:
    out = {}
    for path in (run_dir / "packets").glob("*.packet.json"):
        packet = _load_json(path)
        out[packet["run_id"]] = packet
    return out


def ingest_preferences(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    judged_dir = run_dir / "preference_packets" / "judged"
    judged_dir.mkdir(parents=True, exist_ok=True)

    prefs_path = run_dir / "preferences.json"
    existing = _load_json(prefs_path) if prefs_path.exists() else {}

    ingested, invalid = [], {}
    for path in sorted(judged_dir.glob("*.json")):
        judged = _load_json(path)
        pair_id = judged.get("pair_id")
        pair_key_str = judged.get("pair_key")
        preference = judged.get("preference")
        if not pair_id or not pair_key_str or preference not in ("A", "B", "tie"):
            invalid[str(path)] = ["missing pair_id/pair_key or preference not in A|B|tie"]
            continue
        existing[pair_key_str] = {
            "pair_id": pair_id,
            "preference": preference,
            "rationale": judged.get("rationale", ""),
        }
        ingested.append(pair_key_str)

    prefs_path.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")
    return {"ingested": ingested, "ingested_count": len(ingested), "invalid": invalid, "total_preferences": len(existing)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)

    p_build = sub.add_parser("build", help="Write pairwise blind preference packets for complete A/B pairs")
    p_build.add_argument("--run-dir", required=True, type=Path)
    p_build.add_argument("--force", action="store_true")

    p_ingest = sub.add_parser("ingest", help="Ingest judged preference packets into preferences.json")
    p_ingest.add_argument("--run-dir", required=True, type=Path)

    args = parser.parse_args()
    if args.action == "build":
        result = build_preference_packets(args.run_dir, force=args.force)
    else:
        result = ingest_preferences(args.run_dir)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
