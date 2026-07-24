#!/usr/bin/env python3
"""
collect.py — validate and ingest externally-produced run-bundles.

    python3 collect.py --run-dir /tmp/ab-run-1 --from /path/to/returned-bundles/

Reads every `*.json` file under `--from` (or explicit file args), validates
each against schemas.validate_run_bundle, cross-checks its `run_id` against
`manifest.json` and its identity/content hash against the prepared packet,
then copies validated bundles into
`<run-dir>/collected/<run_id>.json`.

This is the one deliberate checkpoint between "something an external
executor handed back" and "something grade.py/aggregate.py will trust":
malformed, unrecognized, or duplicate bundles are rejected with a clear
reason rather than silently accepted — per the harness's core rule, nothing
here infers success from prose; it inspects the structured fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent))
from schemas import validate_run_bundle  # noqa: E402

SCHEMA_VERSION = 1


class CollectReport:
    def __init__(self) -> None:
        self.collected: List[str] = []
        self.invalid: Dict[str, List[str]] = {}
        self.unknown_run_id: List[str] = []
        self.duplicate: List[str] = []

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "collected": sorted(self.collected),
            "collected_count": len(self.collected),
            "invalid": self.invalid,
            "invalid_count": len(self.invalid),
            "unknown_run_id": sorted(self.unknown_run_id),
            "duplicate": sorted(self.duplicate),
        }

    @property
    def ok(self) -> bool:
        return not self.invalid and not self.unknown_run_id and not self.duplicate


def _iter_bundle_files(sources: List[Path]) -> List[Path]:
    files: List[Path] = []
    for source in sources:
        if source.is_dir():
            files.extend(sorted(source.rglob("*.json")))
        elif source.is_file():
            files.append(source)
    return files


def load_manifest(run_dir: Path) -> dict:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in {run_dir} — run prepare.py first")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _packet_binding_errors(run_dir: Path, bundle: dict) -> List[str]:
    run_id = bundle["run_id"]
    packet_path = run_dir / "packets" / f"{run_id}.packet.json"
    if not packet_path.exists():
        return [f"prepared packet is missing for known run_id {run_id!r}"]
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"prepared packet for run_id {run_id!r} is unreadable: {exc}"]

    errors = []
    for field in ("run_id", "experiment_id", "case_id", "model_label", "repetition", "variant_token"):
        if bundle.get(field) != packet.get(field):
            errors.append(
                f"bundle field {field!r} does not match prepared packet "
                f"(bundle={bundle.get(field)!r}, packet={packet.get(field)!r})"
            )
    if bundle.get("packet_content_hash") != packet.get("variant_content_hash"):
        errors.append(
            "bundle field 'packet_content_hash' does not match prepared packet "
            f"(bundle={bundle.get('packet_content_hash')!r}, "
            f"packet={packet.get('variant_content_hash')!r})"
        )
    return errors


def collect(run_dir: Path, sources: List[Path], *, allow_unknown: bool = False) -> CollectReport:
    run_dir = Path(run_dir)
    manifest = load_manifest(run_dir)
    known_run_ids = set(manifest.get("run_ids", []))

    collected_dir = run_dir / "collected"
    collected_dir.mkdir(parents=True, exist_ok=True)
    already_collected = {p.stem for p in collected_dir.glob("*.json")}

    report = CollectReport()
    for path in _iter_bundle_files(sources):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            report.invalid[str(path)] = [f"could not read file: {exc}"]
            continue
        try:
            bundle = json.loads(raw)
        except json.JSONDecodeError as exc:
            report.invalid[str(path)] = [f"invalid JSON: {exc}"]
            continue

        errors = validate_run_bundle(bundle)
        if errors:
            report.invalid[str(path)] = errors
            continue

        run_id = bundle["run_id"]
        if not allow_unknown and run_id not in known_run_ids:
            report.unknown_run_id.append(run_id)
            continue
        if run_id in known_run_ids:
            binding_errors = _packet_binding_errors(run_dir, bundle)
            if binding_errors:
                report.invalid[str(path)] = binding_errors
                continue

        dest = collected_dir / f"{run_id}.json"
        if run_id in already_collected and dest.exists():
            existing = json.loads(dest.read_text(encoding="utf-8"))
            if existing != bundle:
                report.duplicate.append(run_id)
                continue
        dest.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
        already_collected.add(run_id)
        report.collected.append(run_id)

    (run_dir / "collect_report.json").write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--from",
        dest="sources",
        required=True,
        nargs="+",
        type=Path,
        help="One or more run-bundle JSON files and/or directories to scan recursively",
    )
    parser.add_argument(
        "--allow-unknown",
        action="store_true",
        help="Accept run_ids not present in manifest.json (for ad-hoc/manual testing only)",
    )
    args = parser.parse_args()

    try:
        report = collect(args.run_dir, args.sources, allow_unknown=args.allow_unknown)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    if not report.ok:
        print(
            f"\n{len(report.invalid)} invalid, {len(report.unknown_run_id)} unknown run_id(s), "
            f"{len(report.duplicate)} conflicting duplicate(s) — see above",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
