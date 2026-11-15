#!/usr/bin/env python3
"""baseline.py: approve a rendered set as the baseline later updates keep to, say where things stand, or unlock it.

    baseline.py approve [--config store-screenshots.json] [--note "..."] [--report PATH]
    baseline.py status  [--config store-screenshots.json] [--json]
    baseline.py unlock  [--config store-screenshots.json] --reason "..."

``approve`` (only when the user has approved the set) needs a render report that is current for the config and its
style: every file the config asks for rendered from the inputs it has now (the same ``inputsSha256``) and on disk
as rendered, and ``check.py`` finding no errors. It moves any previous baseline to
``<design>/baseline/history/<date>/``, copies the rendered files, the report and the style into
``<design>/baseline/``, writes ``baseline.json``, sets the style's ``"locked": true`` and adds the approval to
``<design>/decisions.md``.

``status`` says whether there's a baseline, whether the style or the config changed since, whether the render
report is current, and which shots have no baseline counterpart.

``unlock`` (only when the user asks, with their reason) clears ``locked`` and logs the reason in ``decisions.md``.
Changing the look after that is a new approval.

Exit codes: 0 done; 1 status found the locked style changed; 2 refused (no current render report, check errors,
no style); 3 usage or environment.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check  # noqa: E402
import render  # noqa: E402
import styles  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402

EXIT_OK = 0
EXIT_CHANGED = 1
EXIT_REFUSED = 2
EXIT_USAGE = 3

BASELINE_JSON = "baseline.json"
REPORT_NAME = "render-report.json"
DECISIONS = "decisions.md"
DECISIONS_HEAD = ("# Design decisions\n\nWhat the user decided about the screenshots' look, in their words, newest "
                  "last.\n")


class Refused(Exception):
    """The command won't do what was asked; the message says why and what to do."""


def _now(now=None):
    return now or datetime.datetime.now(datetime.timezone.utc)


def _stamp(now):
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def log_decision(design, now, title, lines):
    """Add a dated entry to ``<design>/decisions.md`` (made with its heading when it isn't there)."""
    path = os.path.join(design, DECISIONS)
    os.makedirs(design, exist_ok=True)
    new = not os.path.isfile(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write(DECISIONS_HEAD)
        f.write("\n## %s: %s\n\n" % (now.strftime("%Y-%m-%d"), title))
        for line in lines:
            f.write(line + "\n")
    return path


class Project:
    """A config, its style and its design folder."""

    def __init__(self, config_path, report_path=None):
        self.config_path = config_path
        self.base = os.path.dirname(os.path.abspath(config_path))
        try:
            self.cfg = render.load_config(config_path)
        except render.UsageError as e:
            raise check.UsageError(str(e))
        self.raw = self.cfg["_raw"]
        self.style = self.cfg["_style"]
        self.design = styles.design_dir(config_path, self.raw)
        self.folder = os.path.join(self.design, "baseline")
        self.out = os.path.join(self.base, self.cfg.get("out") or "screenshots")
        self.report_path = report_path or os.path.join(self.out, REPORT_NAME)

    def rel(self, path):
        return os.path.relpath(path, self.base).replace(os.sep, "/")

    def baseline_meta(self):
        path = os.path.join(self.folder, BASELINE_JSON)
        return jsonio.load(path) if os.path.isfile(path) else None

    def report_state(self):
        """``(report or None, wanted {path: inputs}, problems [str])``: whether the render report is current."""
        _res, wanted = render.expected(self.config_path)
        problems = []
        broken = sorted(p for p, h in wanted.items() if h is None)
        if broken:
            problems.append("can't be rendered from the config as it is: %s" % ", ".join(broken))
        if not os.path.isfile(self.report_path):
            return None, wanted, problems + ["no render report at %s" % self.rel(self.report_path)]
        report = jsonio.load(self.report_path)
        files = dict((f.get("path"), f) for f in report.get("files") or [] if isinstance(f, dict))
        stale, missing, changed = [], [], []
        for path, inputs in sorted(wanted.items()):
            if inputs is None:
                continue
            entry = files.get(path)
            if entry is None:
                missing.append(path)
            elif entry.get("inputsSha256") != inputs or entry.get("errors"):
                stale.append(path)
            else:
                disk = os.path.join(self.out, path)
                if not os.path.isfile(disk) or png.sha256(disk) != entry.get("sha256"):
                    changed.append(path)
        if missing:
            problems.append("not rendered: %s" % _few(missing))
        if stale:
            problems.append("rendered from other inputs than the config and style have now: %s" % _few(stale))
        if changed:
            problems.append("changed on disk since rendering: %s" % _few(changed))
        return report, wanted, problems


def _few(items, n=6):
    return ", ".join(items[:n]) + (" and %d more" % (len(items) - n) if len(items) > n else "")


def _history_folder(folder, meta):
    day = str((meta or {}).get("approvedAt") or "undated")[:10]
    target = os.path.join(folder, "history", day)
    n = 2
    while os.path.exists(target):
        target = os.path.join(folder, "history", "%s-%d" % (day, n))
        n += 1
    return target


def approve(config_path, note=None, report_path=None, now=None, log=print):
    """Approve the current render as the baseline; return ``baseline.json``'s content. Raises ``Refused``."""
    now = _now(now)
    proj = Project(config_path, report_path)
    if not proj.style:
        raise Refused("the config names no style: a baseline locks one. Move the theme into a "
                      "screenshot-style.json (references/style.md), add \"style\" to the config, render, then approve")
    conflicts = styles.theme_conflicts(proj.raw.get("theme"), proj.style["data"].get("theme"))
    if conflicts:
        raise Refused("the config's theme sets what the style sets otherwise (%s): once the style is locked that's "
                      "an error, so take them out of the config (the style's are what rendered)" % "; ".join(
                          "%s %s, style %s" % (p, json.dumps(a), json.dumps(b)) for p, a, b in conflicts[:6]))
    report, wanted, problems = proj.report_state()
    if problems:
        raise Refused("the render report isn't current for this config and style, so it can't be approved:\n  %s\n"
                      "Render again (render.py), look at it with the user, then approve." % "\n  ".join(problems))
    result = check.run_check(config_path, report_path=proj.report_path, baseline=None)
    if result.errors:
        raise Refused("check.py finds %d error%s in this set (%s): fix them before approving it" % (
            len(result.errors), "" if len(result.errors) == 1 else "s",
            "; ".join("%s: %s" % (f.where, f.message) for f in result.errors[:3])))

    folder = proj.folder
    previous = proj.baseline_meta()
    moved = None
    if os.path.isdir(folder) and any(n != "history" for n in os.listdir(folder)):
        moved = _history_folder(folder, previous)
        os.makedirs(moved)
        for name in os.listdir(folder):
            if name != "history":
                shutil.move(os.path.join(folder, name), os.path.join(moved, name))
    os.makedirs(folder, exist_ok=True)

    style_path = proj.style["path"]
    data = dict(proj.style["data"])
    data["locked"] = True
    jsonio.dump(data, style_path)
    shutil.copyfile(style_path, os.path.join(folder, styles.STYLE_NAME))

    paths = [p for p in sorted(wanted) if wanted[p] is not None]
    by_path = dict((f.get("path"), f) for f in report.get("files") or [] if isinstance(f, dict))
    order = render._order(proj.cfg)
    kept = sorted((by_path[p] for p in paths), key=order)
    for f in kept:
        dest = os.path.join(folder, f["path"])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(os.path.join(proj.out, f["path"]), dest)
    copy = dict(report)
    copy["files"] = kept
    copy["errors"] = []
    copy["inputsSha256"] = hashlib.sha256("".join(f.get("inputsSha256", "") for f in kept).encode("ascii")).hexdigest()
    jsonio.dump(copy, os.path.join(folder, REPORT_NAME))

    meta = {"version": 1, "approvedAt": _stamp(now), "note": note or "",
            "style": proj.rel(style_path), "styleName": data.get("name"),
            "styleSha256": styles.style_sha256(data), "configSha256": styles.config_sha256(proj.raw),
            "inputsSha256": copy["inputsSha256"], "report": REPORT_NAME,
            "files": [f["path"] for f in kept]}
    jsonio.dump(meta, os.path.join(folder, BASELINE_JSON))
    lines = []
    if note:
        lines += [note, ""]
    lines.append("- Approved as the baseline: %d files, style \"%s\" (%s), now locked." % (
        len(kept), data.get("name"), proj.rel(style_path)))
    if moved:
        lines.append("- The previous baseline (%s) is in %s." % ((previous or {}).get("approvedAt", "undated"),
                                                               proj.rel(moved)))
    decisions = log_decision(proj.design, now, "baseline approved", lines)
    log("Approved %d files as the baseline in %s; %s is locked." % (len(kept), proj.rel(folder), proj.rel(style_path)))
    if moved:
        log("The previous baseline moved to %s." % proj.rel(moved))
    log("Logged in %s." % proj.rel(decisions))
    return meta


def status(config_path, report_path=None):
    """Where things stand against the baseline: a dict (``baseline``, ``style``, ``config``, ``report``,
    ``newShots``, ``goneShots``, ``lockedStyleChanged``)."""
    proj = Project(config_path, report_path)
    meta = proj.baseline_meta()
    out = {"config": proj.rel(config_path), "design": proj.rel(proj.design), "baseline": None, "style": None,
           "configChanged": None, "report": None, "newShots": [], "goneShots": [], "lockedStyleChanged": False}
    if proj.style:
        data = proj.style["data"]
        out["style"] = {"path": proj.rel(proj.style["path"]), "name": data.get("name"),
                        "locked": bool(data.get("locked")), "changed": None}
    _report, wanted, problems = proj.report_state()
    out["report"] = {"current": not problems, "problems": problems}
    if meta is None:
        return out
    out["baseline"] = {"folder": proj.rel(proj.folder), "approvedAt": meta.get("approvedAt"),
                       "note": meta.get("note"), "files": len(meta.get("files") or []), "style": meta.get("style")}
    if out["style"] is not None:
        changed = proj.style["sha256"] != meta.get("styleSha256")
        out["style"]["changed"] = changed
        out["lockedStyleChanged"] = changed and out["style"]["locked"]
    elif meta.get("styleSha256"):
        out["lockedStyleChanged"] = True
    out["configChanged"] = styles.config_sha256(proj.raw) != meta.get("configSha256")
    have = set()
    for p in meta.get("files") or []:
        parts = p.split("/")
        if len(parts) == 3:
            have.add((parts[1], parts[2][:-4] if parts[2].endswith(".png") else parts[2]))
    now = set()
    for p in wanted:
        parts = p.split("/")
        if len(parts) == 3:
            now.add((parts[1], parts[2][:-4]))
    out["newShots"] = sorted("%s/%s" % x for x in now - have)
    out["goneShots"] = sorted("%s/%s" % x for x in have - now)
    return out


def status_text(st):
    lines = []
    b = st["baseline"]
    if b is None:
        lines.append("No baseline approved yet (in %s/baseline)." % st["design"])
    else:
        lines.append("Baseline: %s, approved %s, %d files%s." % (b["folder"], b["approvedAt"], b["files"],
                                                              " (\"%s\")" % b["note"] if b.get("note") else ""))
    s = st["style"]
    if s is None:
        lines.append("Style: the config names none%s." % (" (the baseline locked %s)" % b["style"]
                                                         if b and b.get("style") else ""))
    else:
        bits = ["locked" if s["locked"] else "not locked"]
        if s["changed"] is not None:
            bits.append("changed since the baseline" if s["changed"] else "unchanged since the baseline")
        lines.append("Style: %s (\"%s\"), %s." % (s["path"], s["name"], ", ".join(bits)))
    if st["lockedStyleChanged"]:
        lines.append("  The locked style changed: approve a new baseline with the user, or put it back "
                     "(%s/screenshot-style.json is the approved one)." % b["folder"])
    if st["configChanged"] is not None:
        lines.append("Config: %s since the baseline." % ("changed" if st["configChanged"] else "unchanged"))
    r = st["report"]
    lines.append("Render report: %s." % ("current" if r["current"] else "not current"))
    for p in r["problems"]:
        lines.append("  %s" % p)
    if b is not None:
        if st["newShots"]:
            lines.append("No baseline counterpart (check.py compares them by role or layout): %s."
                         % ", ".join(st["newShots"]))
        if st["goneShots"]:
            lines.append("In the baseline, not in the set: %s." % ", ".join(st["goneShots"]))
    return "\n".join(lines) + "\n"


def unlock(config_path, reason, now=None, log=print):
    """Clear the style's ``locked`` and log the user's reason; return True if it was locked."""
    now = _now(now)
    if not reason or not reason.strip():
        raise check.UsageError("unlock needs the user's reason (--reason \"...\")")
    proj = Project(config_path)
    if not proj.style:
        raise Refused("the config names no style to unlock")
    data = dict(proj.style["data"])
    if not data.get("locked"):
        log("%s isn't locked: nothing to do." % proj.rel(proj.style["path"]))
        return False
    data["locked"] = False
    jsonio.dump(data, proj.style["path"])
    decisions = log_decision(proj.design, now, "style unlocked", [
        reason.strip(), "", "- %s unlocked: changing the look is a new approval (baseline.py approve)." %
        proj.rel(proj.style["path"])])
    log("Unlocked %s; logged in %s. Changing the look now is a new approval." % (
        proj.rel(proj.style["path"]), proj.rel(decisions)))
    return True


def parser():
    p = argparse.ArgumentParser(prog="baseline.py", description="Approve a rendered set as the baseline, say where "
                                "things stand against it, or unlock its style. Offline.")
    sub = p.add_subparsers(dest="command")
    a = sub.add_parser("approve", help="approve the current render as the baseline (the user's say) and lock the style")
    a.add_argument("--note", help="what the user approved, in their words")
    s = sub.add_parser("status", help="the baseline, the style and the render report")
    s.add_argument("--json", action="store_true")
    u = sub.add_parser("unlock", help="unlock the style (only when the user asks), logging their reason")
    u.add_argument("--reason", required=True, help="the user's reason, in their words")
    for x in (a, s, u):
        x.add_argument("--config", default="store-screenshots.json", help="the design config (default: %(default)s)")
    for x in (a, s):
        x.add_argument("--report", help="the render report (default: <out>/render-report.json)")
    return p


def main(argv=None):
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return EXIT_OK if e.code in (0, None) else EXIT_USAGE
    if not args.command:
        parser().print_usage(sys.stderr)
        return EXIT_USAGE
    try:
        if args.command == "approve":
            approve(args.config, args.note, args.report)
            return EXIT_OK
        if args.command == "status":
            st = status(args.config, args.report)
            sys.stdout.write(json.dumps(st, indent=2) + "\n" if args.json else status_text(st))
            return EXIT_CHANGED if st["lockedStyleChanged"] else EXIT_OK
        unlock(args.config, args.reason)
        return EXIT_OK
    except Refused as e:
        sys.stderr.write("baseline.py: refused: %s\n" % e)
        return EXIT_REFUSED
    except (check.UsageError, jsonio.JsonError) as e:
        sys.stderr.write("baseline.py: %s\n" % e)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
