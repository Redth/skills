#!/usr/bin/env python3
"""check_captures.py: check the captures against the plan (and the stores' accepted sizes) from their headers.

    check_captures.py [--plan capture-plan.json] [--rules apple,google] [--json]

For every locale x device x screen the plan asks for, ``<out>/<locale>/<device id>/<screen id>.png`` must exist
and be what CONTRACT.md 10.4 says a capture is: a PNG of exactly the device's ``width`` x ``height``, 8-bit RGB
(no alpha channel, no ``tRNS``), sRGB (an ``sRGB`` chunk, an sRGB profile, or untagged) and not interlaced. A picture
``capture-report.json`` says was kept from an earlier run (the shot was missed this time) is a warning.

With ``--rules``, each device's size is also checked against the stores' rules data (``rules/<store>.json``):
``apple``: an App Store display type of the device's platform takes that size (either orientation unless the
display type says otherwise); ``google`` (Android devices): it's within a Play screenshot slot's size range and
aspect (for the device's ``kind``: phone, tablet, tv, watch). Devices of other platforms aren't checked against a
store.

Exit codes: 0 nothing wrong (warnings allowed); 1 an error; 3 usage (no plan, an invalid plan, unknown rules).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import rules as rules_lib  # noqa: E402
import capture  # noqa: E402

SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
RULES_DIR = os.path.join(SKILL_DIR, "rules")

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_USAGE = 3

APPLE_PLATFORMS = {"ios": "IOS", "ipados": "IOS", "watchos": "IOS", "tvos": "TV_OS", "visionos": "VISION_OS",
                   "macos": "MAC_OS"}
GOOGLE_PLATFORMS = ("android",)
GOOGLE_KINDS = {"phone": ("phone",), "tablet": ("tablet7", "tablet10"), "tv": ("tv",), "watch": ("wear",)}


def finding(severity, where, message, rule=None):
    """One thing found: ``{"severity", "where", "message", "rule"}``."""
    return {"severity": severity, "where": where, "message": message, "rule": rule}


def check_picture(path, where, width, height):
    """What's wrong with one capture file (a list of findings; empty when it's fine)."""
    try:
        meta = png.info(path)
    except (png.ImageError, OSError) as e:
        return [finding("error", where, "not a picture this can read: %s" % e)]
    out = []
    if meta.format != "png":
        out.append(finding("error", where, "a %s, not a PNG" % meta.format.upper()))
    if (meta.width, meta.height) != (width, height):
        out.append(finding("error", where, "%dx%d, not the %dx%d the plan promises (never resize: recapture on the "
                                           "device that renders it)" % (meta.width, meta.height, width, height)))
    if meta.bit_depth != 8:
        out.append(finding("error", where, "%d-bit, not 8-bit" % meta.bit_depth))
    if meta.has_alpha:
        out.append(finding("error", where, "has an alpha channel or tRNS (the stores refuse alpha: capture.py "
                                           "flattens it)"))
    elif meta.format == "png" and meta.color_type != 2:
        out.append(finding("error", where, "PNG colour type %d, not RGB (2)" % meta.color_type))
    if not meta.srgb:
        out.append(finding("error", where, "colour profile %r, not sRGB" % meta.icc_name))
    if meta.interlaced:
        out.append(finding("error", where, "interlaced"))
    return out


def _fits(size, sizes, orientation):
    w, h = size
    for sw, sh in sizes:
        if (w, h) == (sw, sh):
            return True
        if not orientation and (h, w) == (sw, sh):
            return True
    return False


def apple_slots(ruleset, platform, size):
    """The App Store display types of ``platform`` (``IOS``, …) that take a picture of ``size``, in order."""
    return [name for name, slot in ruleset.slots.items()
            if slot.get("platform") == platform and slot.get("sizes")
            and _fits(size, slot["sizes"], slot.get("orientation"))]


def google_fits(slot, size):
    """Why a Play screenshot slot refuses ``size`` (a message), or ``None`` when it takes it."""
    r = slot.get("range") or {}
    short, long_ = min(size), max(size)
    aspect = float(long_) / float(short) if short else 0
    if r.get("minSide") and short < r["minSide"]:
        return "its short side %d is under %d" % (short, r["minSide"])
    if r.get("maxSide") and long_ > r["maxSide"]:
        return "its long side %d is over %d" % (long_, r["maxSide"])
    if r.get("maxAspect") and aspect > r["maxAspect"] + 1e-6:
        return "it's %.2f:1, longer than %g:1" % (aspect, r["maxAspect"])
    if r.get("minAspect") and aspect < r["minAspect"] - 1e-6:
        return "it's %.2f:1, not the %g:1 or longer it needs" % (aspect, r["minAspect"])
    return None


def check_store_sizes(device, rulesets):
    """Findings for a device's size against each store's accepted sizes."""
    out = []
    size = (device["width"], device["height"])
    where = "device %s (%dx%d)" % (device["id"], size[0], size[1])
    apple = rulesets.get("apple")
    if apple is not None and device["platform"] in APPLE_PLATFORMS:
        platform = APPLE_PLATFORMS[device["platform"]]
        slots = apple_slots(apple, platform, size)
        if not slots:
            out.append(finding("error", where, "no App Store display type for %s takes %dx%d" % (platform, size[0],
                                                                                                size[1]),
                               "apple.screenshots.size"))
        else:
            kinds = set(apple.slots[s].get("kind") for s in slots)
            if device.get("kind") and device["kind"] not in kinds:
                out.append(finding("warning", where, "fills %s (%s), but the device says it's a %s"
                                   % (", ".join(slots), "/".join(sorted(k for k in kinds if k)), device["kind"])))
            else:
                out.append(finding("info", where, "fills %s" % slots[0]))
    google = rulesets.get("google")
    if google is not None and device["platform"] in GOOGLE_PLATFORMS:
        names = GOOGLE_KINDS.get(device.get("kind") or "", None)
        candidates = [n for n, s in google.slots.items() if s.get("group") == "screenshots"
                      and (names is None or n in names)]
        taken = [n for n in candidates if google_fits(google.slots[n], size) is None]
        if not taken:
            why = "; ".join("%s: %s" % (n, google_fits(google.slots[n], size)) for n in candidates)
            out.append(finding("error", where, "no Google Play screenshot slot takes %dx%d (%s)" % (size[0], size[1],
                                                                                                  why),
                               "google.screenshots.size"))
        else:
            out.append(finding("info", where, "fits Play's %s" % ", ".join(taken)))
    return out


def report_entries(out):
    """The capture report's shots by ``(locale, device, screen)``, or ``{}``."""
    path = os.path.join(out, capture.REPORT_NAME)
    if not os.path.isfile(path):
        return {}
    try:
        data = jsonio.load(path)
    except (jsonio.JsonError, OSError):
        return {}
    shots = data.get("shots") if isinstance(data, dict) else None
    return dict(((e.get("locale"), e.get("device"), e.get("screen")), e) for e in shots or [] if isinstance(e, dict))


def check(plan_path, stores=None):
    """Check every capture the plan asks for; return ``(findings, files_checked)``. Raises ``capture.UsageError``
    for an unusable plan and ``rules.RulesError`` for unknown rules."""
    plan = capture.load_plan(plan_path)
    out = capture.out_dir(plan, plan_path)
    rulesets = dict((s, rules_lib.load(s, RULES_DIR)) for s in stores or [])
    entries = report_entries(out)
    findings = []
    checked = 0
    for raw in plan["devices"]:
        device = capture.resolve_device(plan, raw)
        findings.extend(check_store_sizes(device, rulesets))
        for screen in capture.screens_for(plan, device):
            for locale in screen["locales"]:
                rel = "/".join((locale, device["id"], screen["id"] + ".png"))
                path = os.path.join(out, locale, device["id"], screen["id"] + ".png")
                entry = entries.get((locale, device["id"], screen["id"])) or {}
                if not os.path.isfile(path):
                    reason = entry.get("reason")
                    findings.append(finding("error", rel, "missing%s" % ((" (%s: %s)" % (entry.get("status"), reason))
                                                                        if reason else "")))
                    continue
                checked += 1
                findings.extend(check_picture(path, rel, device["width"], device["height"]))
                if entry.get("kept") == "previous" and entry.get("status") != "taken":
                    findings.append(finding("warning", rel, "kept from an earlier run: this run's shot was %s (%s)"
                                            % (entry.get("status"), entry.get("reason") or "no reason given")))
                if entry.get("statusBar") in ("unverified", "overridden") and entry.get("status") == "taken":
                    findings.append(finding("note", rel, "status bar %s: look at it" % entry["statusBar"]))
    return findings, checked


def parser():
    p = argparse.ArgumentParser(prog="check_captures.py", description="Check captures against the plan and the stores.")
    p.add_argument("--plan", default="capture-plan.json", help="the capture plan (default capture-plan.json)")
    p.add_argument("--rules", help="also check sizes against these stores' rules (comma-separated: apple,google)")
    p.add_argument("--json", action="store_true", help="print the findings as JSON")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    stores = [s.strip() for s in (args.rules or "").split(",") if s.strip()]
    try:
        findings, checked = check(args.plan, stores)
    except capture.UsageError as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    except rules_lib.RulesError as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    errors = [f for f in findings if f["severity"] == "error"]
    if args.json:
        print(json.dumps({"findings": findings, "checked": checked, "errors": len(errors)}, indent=2,
                         ensure_ascii=False))
    else:
        for f in findings:
            print("%s: %s: %s" % (f["severity"], f["where"], f["message"]))
        print("%d captures checked, %d errors, %d warnings" % (
            checked, len(errors), sum(1 for f in findings if f["severity"] == "warning")))
    return EXIT_ERRORS if errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
