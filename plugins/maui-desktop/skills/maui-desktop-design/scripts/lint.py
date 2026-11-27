#!/usr/bin/env python3
"""lint.py: find raw colours and sizes in hand-written UI code, where a design token belongs.

    lint.py [--root .] [--tokens design/tokens.json] [--json] [--write-baseline] [PATH ...]

Scans the folders in ``lint.scan`` (or the paths given) for the rules ``lint.rules`` enables (CONTRACT.md
section 7.5): ``raw-hex``, ``raw-rgb-hsl``, ``raw-modern-color`` (``oklch()``, ``oklab()``, ``lab()``,
``lch()``, ``color()``), ``named-color``, ``px-font-size``, ``magic-z-index`` (anything but a ``var()``,
``0``, ``-1``, ``auto`` or ``inherit``), ``raw-radius`` (a ``border-radius`` that isn't a ``var()``, ``0`` or
``50%``) and ``native-select`` (``<select`` in ``.razor`` and ``.html``). Generated outputs (``tokens.json``'s
and ``icons.json``'s) are skipped: they are where literal colour belongs.

A finding on a line carrying ``design-lint-ok: <reason>`` in a comment, or in the comment block directly above
it, is suppressed, so a justification can span lines.

With ``lint.baseline`` set, only findings beyond the baseline's count for each ``(file, rule)`` fail, so an
existing app can adopt the gate and ratchet it down; ``--write-baseline`` records today's counts. Without a
tokens file, the defaults below apply.

Exit codes: 0 clean (or a baseline written); 1 findings; 3 usage (a ``--tokens`` that isn't there, bad JSON).
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

import tokens as T  # noqa: E402
from mauidesktop_lib import findings as fnd  # noqa: E402
from mauidesktop_lib import jsonio  # noqa: E402
from mauidesktop_lib.findings import Finding  # noqa: E402

DEFAULTS = {
    "scan": ["src"],
    "extensions": [".css", ".razor", ".cs", ".html", ".js"],
    "skip": ["bin", "obj", "node_modules", "wwwroot/lib", "wwwroot/vendor"],
    "rules": {"raw-hex": True, "raw-rgb-hsl": True, "raw-modern-color": True, "named-color": True,
              "px-font-size": True, "magic-z-index": True, "raw-radius": False, "native-select": False},
}
ALWAYS_SKIP = frozenset([".git", ".vs", ".idea"])
DEFAULT_BASELINE = "design/lint-baseline.json"
MARKUP = (".razor", ".html", ".htm", ".cshtml")

# (id, pattern, message, the extensions it applies to or None for all)
RULES = [
    ("raw-hex",
     # 3, 4, 6 or 8 hex digits not after a word character, & or # (so not a sha256:… digest or &#…; entity)
     re.compile(r"(?<![\w&#])#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b"),
     "raw hex colour: use a semantic token (tokens.css, or the generated C# palette)", None),
    ("raw-rgb-hsl", re.compile(r"\b(?:rgba?|hsla?)\s*\("),
     "raw rgb()/hsl() colour: use a semantic token, or color-mix() over one", None),
    # OKLCH is how tokens.json authors colour, so a raw oklch() in a component isn't an unusual way to write a
    # colour: it's the same way, bypassing the generator, the gamut check and the contrast gate.
    ("raw-modern-color", re.compile(r"\b(?:oklch|oklab|lch|lab|color)\s*\("),
     "raw oklch()/lab()/color(): author it in design/tokens.json and use the generated token", None),
    ("named-color",
     re.compile(r"(?<![-\w])(?:color|background|background-color|border-color|fill|stroke)\s*:\s*"
                r"(?:red|green|blue|orange|yellow|purple|grey|gray|black|white|pink|cyan|magenta)\b", re.I),
     "CSS named colour: use a semantic token", None),
    ("px-font-size", re.compile(r"font-size\s*:\s*\d+(?:\.\d+)?px", re.I),
     "hardcoded px font-size: use a text token (var(--text-…))", None),
    ("magic-z-index", re.compile(r"z-index\s*:(?!\s*(?:var\(|0\b|-1\b|auto\b|inherit\b))\s*[^\s;\"'}]+", re.I),
     "raw z-index: use a z token (var(--z-…))", None),
    ("raw-radius",
     # The lookahead sits before the spaces so they can't backtrack past it.
     re.compile(r"border(?:-(?:top|bottom|start|end)-(?:left|right|start|end))?-radius\s*:"
                r"(?!\s*(?:var\(|0(?![\w.])|50%))\s*[^;\"'}]+", re.I),
     "raw border-radius: use a radius token (var(--radius-…))", None),
    ("native-select", re.compile(r"<select\b"),
     "native <select>: use the app's custom select component, which matches every platform", MARKUP),
]
RULE_IDS = [r[0] for r in RULES]

# design-lint-ok: <reason> suppresses a finding on its own line, or anywhere in the contiguous comment block
# directly above, so a justification may span lines without silently losing its effect.
ALLOW = re.compile(r"(?://|/\*|\*|<!--)\s*design-lint-ok\b")
COMMENT_LINE = re.compile(r"^\s*(?://|/\*|\*|<!--|\*/|@\*|-->)")


def suppressed(lines, index):
    if ALLOW.search(lines[index]):
        return True
    for i in range(index - 1, -1, -1):
        if ALLOW.search(lines[i]):
            return True
        if not COMMENT_LINE.match(lines[i]):
            return False
    return False


def _segments(path):
    return [s for s in path.replace("\\", "/").split("/") if s and s != "."]


def skipped(rel_path, skip):
    """True when a skip entry (a folder name, or a ``a/b`` run of folders) appears in ``rel_path``."""
    parts = _segments(rel_path)
    if any(p in ALWAYS_SKIP for p in parts):
        return True
    for entry in skip:
        want = _segments(entry)
        n = len(want)
        if any(parts[i:i + n] == want for i in range(len(parts) - n + 1)):
            return True
    return False


def config(tokens_data):
    """The lint settings: ``tokens.json``'s ``lint`` over the defaults."""
    lint = (tokens_data or {}).get("lint", {})
    cfg = {k: (list(v) if isinstance(v, list) else dict(v)) for k, v in DEFAULTS.items()}
    for key in ("scan", "extensions", "skip"):
        if key in lint:
            cfg[key] = list(lint[key])
    cfg["rules"].update(T.visible(lint.get("rules", {})))
    cfg["baseline"] = lint.get("baseline")
    return cfg


def generated_paths(tokens_data, tokens_file, root):
    """Every output ``tokens.json`` names, and ``icons.json``'s beside it: ``(files, folders)``, relative."""
    files, folders = set(), set()
    outputs = (tokens_data or {}).get("outputs", {})
    for key in ("css", "design"):
        if outputs.get(key):
            files.add(outputs[key])
    for key in ("csharp", "macosAccent"):
        if isinstance(outputs.get(key), dict):
            files.add(outputs[key]["path"])
    icons_file = os.path.join(os.path.dirname(tokens_file), "icons.json")
    if os.path.isfile(icons_file):
        try:
            icons = jsonio.load(icons_file)
        except (ValueError, OSError):
            icons = {}
        io = icons.get("outputs", {}) if isinstance(icons, dict) else {}
        for key in ("sprite", "razor"):
            if isinstance(io.get(key), str):
                files.add(io[key])
        if isinstance(io.get("csharp"), dict):
            files.add(io["csharp"].get("path", ""))
        if isinstance(io.get("macosMarks"), str):
            folders.add(io["macosMarks"])
    norm = lambda p: "/".join(_segments(p))  # noqa: E731
    return set(norm(p) for p in files if p), set(norm(p) for p in folders if p)


def walk(root, targets, cfg, generated):
    """Files to scan, relative to ``root`` with ``/``, sorted."""
    files, folders = generated
    found = []
    exts = tuple(cfg["extensions"])

    def wanted(rel_path):
        if rel_path in files or any(rel_path == f or rel_path.startswith(f + "/") for f in folders):
            return False
        return rel_path.endswith(exts) and not skipped(rel_path, cfg["skip"])

    for target in targets:
        if os.path.isfile(target):
            r = T.rel(target, root)
            if wanted(r):
                found.append(r)
            continue
        for dirpath, dirnames, filenames in os.walk(target):
            here = T.rel(dirpath, root)
            dirnames[:] = sorted(d for d in dirnames if not skipped(here + "/" + d, cfg["skip"]))
            for name in sorted(filenames):
                r = T.rel(os.path.join(dirpath, name), root)
                if wanted(r):
                    found.append(r)
    return sorted(set(found))


def scan_file(root, rel_path, rules):
    """``[(rule, line, column, match)]`` for one file."""
    path = T.under(root, rel_path)
    try:
        lines = T.read_text(path).split("\n")
    except OSError:
        return []
    out = []
    for i, line in enumerate(lines):
        hits = []
        for rule_id, pattern, _, exts in rules:
            if exts is not None and not rel_path.lower().endswith(exts):
                continue
            for m in pattern.finditer(line):
                hits.append((rule_id, i + 1, m.start() + 1, m.group(0).strip()))
        if hits and not suppressed(lines, i):
            out += hits
    return out


def load_baseline(path):
    """``{file: {rule: count}}``, or None when the file isn't there."""
    if not os.path.isfile(path):
        return None
    data = T.load_json(path)
    counts = data.get("counts", {}) if isinstance(data, dict) else {}
    return {f: dict(r) for f, r in counts.items() if not f.startswith("$") and isinstance(r, dict)}


def lint(root, tokens_file, given_tokens, paths, json_output=False, write_baseline=False, stream=None):
    stream = stream or sys.stdout
    data = None
    if os.path.isfile(tokens_file):
        label = T.rel(tokens_file, root)
        data = T.validate_against(T.load_json(tokens_file, label), "tokens.schema.json", label)
    elif given_tokens:
        raise T.UsageError("%s: no such file" % given_tokens)
    cfg = config(data)
    rules = [r for r in RULES if cfg["rules"].get(r[0])]
    found = []
    if paths:
        targets = []
        for p in paths:
            full = p if os.path.isabs(p) else os.path.abspath(p)
            if not os.path.exists(full) and not os.path.isabs(p):
                full = os.path.join(root, p)  # relative to the project when it isn't relative to here
            if not os.path.exists(full):
                raise T.UsageError("%s: no such file or folder" % p)
            targets.append(full)
    else:
        targets = []
        for s in cfg["scan"]:
            full = T.under(root, s)
            if os.path.exists(full):
                targets.append(full)
            else:
                found.append(Finding("scan-missing", "warning", s, "lint.scan names a folder that isn't there"))
    files = walk(root, targets, cfg, generated_paths(data, tokens_file, root))
    hits = collections.OrderedDict()
    for f in files:
        for rule_id, line, col, match in scan_file(root, f, rules):
            hits.setdefault((f, rule_id), []).append((line, col, match))
    messages = {r[0]: r[2] for r in RULES}

    baseline_rel = cfg.get("baseline")
    if write_baseline:
        target = baseline_rel or DEFAULT_BASELINE
        counts = collections.OrderedDict()
        for (f, rule_id), items in sorted(hits.items()):
            counts.setdefault(f, collections.OrderedDict())[rule_id] = len(items)
        jsonio.dump(collections.OrderedDict([
            ("$comment", "Written by lint.py --write-baseline: the raw values each file had when the gate was "
                         "adopted. Only findings beyond these counts fail; lower them as files are cleaned up."),
            ("version", 1), ("counts", counts)]), T.under(root, target))
        total = sum(len(v) for v in hits.values())
        stream.write("wrote %s: %d finding(s) in %d file(s)%s\n" % (
            target, total, len(counts), "" if baseline_rel else " (set lint.baseline to use it)"))
        return T.EXIT_OK

    baseline = load_baseline(T.under(root, baseline_rel)) if baseline_rel else None
    if baseline_rel and baseline is None:
        found.append(Finding("baseline-missing", "info", baseline_rel,
                             "lint.baseline names a file that isn't there: every finding counts"))
    covered = 0
    errors = []
    for (f, rule_id), items in hits.items():
        allowed = (baseline or {}).get(f, {}).get(rule_id, 0)
        if len(items) <= allowed:
            covered += len(items)
            if len(items) < allowed:
                found.append(Finding("baseline-improved", "info", f,
                                     "%s: %d now, the baseline allows %d: run lint.py --write-baseline to ratchet "
                                     "it down" % (rule_id, len(items), allowed)))
            continue
        note = " (%d in this file, the baseline allows %d)" % (len(items), allowed) if allowed else ""
        for line, col, match in items:
            errors.append(((f, line, col), Finding(rule_id, "error", "%s:%d:%d" % (f, line, col),
                                                   "%s: %s%s" % (match, messages[rule_id], note))))
    found = [e for _, e in sorted(errors, key=lambda x: x[0])] + found
    for f, rules_counts in sorted((baseline or {}).items()):
        for rule_id, allowed in sorted(rules_counts.items()):
            if allowed and (f, rule_id) not in hits and f in files:
                found.append(Finding("baseline-improved", "info", f,
                                     "%s: none now, the baseline allows %d: run lint.py --write-baseline to ratchet "
                                     "it down" % (rule_id, allowed)))
    summary = "%d file(s) scanned, %d rule(s)%s." % (
        len(files), len(rules), ", %d finding(s) covered by the baseline" % covered if covered else "")
    if json_output:
        fnd.print_findings(found, True, stream, scanned=len(files), covered=covered,
                           rules=[r[0] for r in rules])
    else:
        fnd.print_findings(found, False, stream, summary=summary)
        if fnd.errors(found):
            stream.write("Colour and type live in design/tokens.json. If a literal is genuinely unavoidable, say why "
                         "on the line: design-lint-ok: <reason>.\n")
    return fnd.exit_code(found)


def parse_args(argv):
    p = argparse.ArgumentParser(prog="lint.py", description="Find raw colours and sizes where a design token belongs.")
    p.add_argument("--root", default=".")
    p.add_argument("--tokens", help="design/tokens.json (its lint and outputs sections); default under --root")
    p.add_argument("--json", action="store_true")
    p.add_argument("--write-baseline", action="store_true", help="record today's counts per file and rule")
    p.add_argument("paths", nargs="*", help="files or folders to scan instead of lint.scan")
    return p.parse_args(argv)


def main(argv=None, stream=None):
    stream = stream or sys.stdout
    args = parse_args(argv)
    root = os.path.abspath(args.root)
    try:
        if not os.path.isdir(root):
            raise T.UsageError("--root %s isn't a folder" % args.root)
        given = args.tokens
        tokens_file = (given if os.path.isabs(given) else os.path.join(root, given)) if given else \
            os.path.join(root, T.DEFAULT_TOKENS)
        return lint(root, tokens_file, given, args.paths, args.json, args.write_baseline, stream)
    except T.UsageError as e:
        fnd.print_findings(e.findings, args.json, stream if args.json else sys.stderr)
        return T.EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
