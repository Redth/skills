#!/usr/bin/env python3
"""capture.py: capture an app's screens at exactly the sizes the stores want, by the plan's drivers.

    capture.py [--plan capture-plan.json] [--devices iphone-6.9,android-phone] [--screens plan,recipe]
               [--locales en-US,de-DE] [--keep-going] [--cleanup] [--dry-run]

For each device in the plan (CONTRACT.md 10.2) its driver prepares it (finds or creates and boots a dedicated
simulator, starts an emulator, opens a browser), then for each locale and each screen runs the screen's steps and
takes a screenshot, and always resets the device after (status bar, demo mode, display size, appearance, locale),
even when something failed. Each picture is checked: exactly the device's ``width`` x ``height`` (any other size is
``failed``, never resized), 8-bit RGB with no alpha, sRGB, not interlaced. One with an alpha channel (or 16 bits, a
colour profile other than sRGB, interlacing) is drawn again through headless Chrome onto the plan's ``flatten``
colour and the change listed in its ``fixes``.

Pictures are written into a temporary folder inside ``<out>`` and moved into place at the end:
``<out>/<locale>/<device id>/<screen id>.png``, with ``<out>/capture-report.json`` saying what was taken, missed
(``kept: previous`` when an older picture stays), failed or skipped, and why. A partial run (``--devices``, …)
keeps the report's entries for what it didn't run.

``--dry-run`` prints each device's preparation and every step as its driver would run it, and runs nothing.
``--cleanup`` deletes the simulators and emulators this skill created (``appstores-<device id>``) when done.
Without ``--keep-going`` the run stops at the first shot that's missed or failed (the rest are reported as not
attempted).

Exit codes: 0 done; 1 a shot failed, or was missed or skipped with no previous picture kept; 2 refused (another
capture is writing to the same folder); 3 usage or environment (no plan, an invalid plan, a missing tool).
"""

from __future__ import annotations

import argparse
import copy
import datetime
import os
import shutil
import sys
import tempfile
import traceback

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import schema  # noqa: E402
import drivers  # noqa: E402
from drivers import base  # noqa: E402

SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
SCHEMA_PATH = os.path.join(SKILL_DIR, "schema", "capture-plan.schema.json")
REPORT_NAME = "capture-report.json"
LOCK_NAME = ".capture.lock"

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_REFUSED = 2
EXIT_USAGE = 3

# Settings a device and a screen may override (CONTRACT.md 10.2), and their defaults.
SETTINGS = ("appearance", "clock", "statusBar", "seed", "flatten")
DEFAULTS = {"locales": ["en-US"], "appearance": "light", "clock": "09:41", "statusBar": "clean", "seed": None,
            "flatten": "#000000", "out": "captures"}
# A platform with no app entry of its own uses its family's.
FAMILY = {"ipados": "ios", "tvos": "ios", "watchos": "ios", "visionos": "ios"}


class UsageError(Exception):
    """The plan can't be used: missing, not JSON, against the schema, or naming things that don't exist."""


class Refused(Exception):
    """The run won't start (another capture holds the output folder)."""


def log(message):
    """Progress, to stderr."""
    print(message, file=sys.stderr)


def _csv(value):
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def now():
    """The current UTC time (a hook for tests)."""
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp(when):
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


# -- the plan -------------------------------------------------------------------------------------------------

def load_schema():
    """The plan's JSON schema."""
    return jsonio.load(SCHEMA_PATH)


def load_plan(path):
    """Read and validate a plan; return it. Raises ``UsageError`` naming every problem."""
    if not os.path.isfile(path):
        raise UsageError("no plan at %s (pass --plan, or write capture-plan.json: see the skill's SKILL.md)" % path)
    try:
        plan = jsonio.load(path)
    except jsonio.JsonError as e:
        raise UsageError(str(e)) from None
    problems = schema.validate(plan, load_schema())
    if not problems and isinstance(plan, dict):
        problems = check_plan(plan)
    if problems:
        raise UsageError("%s isn't a usable capture plan:\n  %s" % (path, "\n  ".join(problems)))
    return plan


def check_plan(plan):
    """What the schema can't say: unique ids, screens naming devices that exist. Returns messages."""
    problems = []
    seen = set()
    for d in plan["devices"]:
        if d["id"] in seen:
            problems.append("/devices: the id %s is used twice" % d["id"])
        seen.add(d["id"])
    screens = set()
    platforms = set(d["platform"] for d in plan["devices"])
    for i, s in enumerate(plan["screens"]):
        if s["id"] in screens:
            problems.append("/screens: the id %s is used twice" % s["id"])
        screens.add(s["id"])
        for name in s.get("devices") or []:
            if name not in seen:
                problems.append("/screens/%d/devices: no device %s" % (i, name))
        for name in s.get("overrides") or {}:
            if name not in seen and name not in platforms:
                problems.append("/screens/%d/overrides: %s is neither a device id nor a device's platform" % (i, name))
    return problems


def app_for(plan, device):
    """The app entry a device uses: the plan's for its platform (or its family's), merged with the device's."""
    apps = plan.get("app") or {}
    platform = device["platform"]
    entry = apps.get(platform)
    if entry is None and platform in FAMILY:
        entry = apps.get(FAMILY[platform])
    merged = dict(entry or {})
    merged.update(device.get("app") or {})
    merged.pop("$comment", None)
    return merged


def resolve_device(plan, device):
    """A device as a driver gets it: its own fields, each setting from the device or else the plan (or the
    default), its ``app`` entry and ``target`` (``{}`` when absent)."""
    out = copy.deepcopy(device)
    out.pop("$comment", None)
    out["locales"] = list(device.get("locales") or plan.get("locales") or DEFAULTS["locales"])
    for key in SETTINGS:
        value = device.get(key)
        out[key] = value if value is not None else plan.get(key, DEFAULTS[key])
    out["app"] = app_for(plan, device)
    out["target"] = dict(device.get("target") or {})
    return out


def screens_for(plan, device):
    """The screens a resolved device captures, each resolved for it: its settings (the device's, then the
    screen's, then its overrides' for the device's platform, then for its id), its ``steps`` (an override's
    replace the screen's) and its ``locales`` (those of the device's it's limited to)."""
    out = []
    for screen in plan["screens"]:
        if screen.get("devices") and device["id"] not in screen["devices"]:
            continue
        if screen.get("platforms") and device["platform"] not in screen["platforms"]:
            continue
        layers = [screen]
        overrides = screen.get("overrides") or {}
        for key in (device["platform"], device["id"]):
            if key in overrides:
                layers.append(overrides[key])
        resolved = {"id": screen["id"], "steps": copy.deepcopy(screen.get("steps") or [])}
        for key in SETTINGS:
            resolved[key] = device.get(key)
        wanted = None
        for layer in layers:
            for key in SETTINGS:
                if layer.get(key) is not None:
                    resolved[key] = layer[key]
            if layer is not screen and "steps" in layer:
                resolved["steps"] = copy.deepcopy(layer["steps"])
            if layer.get("locales"):
                wanted = layer["locales"]
        resolved["locales"] = [l for l in device["locales"] if wanted is None or l in wanted]
        out.append(resolved)
    return out


def out_dir(plan, plan_path):
    """The captures' folder, absolute."""
    rel = plan.get("out") or DEFAULTS["out"]
    return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(plan_path)), rel))


# -- checking a picture ---------------------------------------------------------------------------------------

_BROWSER = [None]


def _browser():
    if _BROWSER[0] is None:
        _BROWSER[0] = chrome.Chrome()
        _BROWSER[0].start()
    return _BROWSER[0]


def close_browser():
    """Stop the Chrome flattening used, if it started one."""
    if _BROWSER[0] is not None:
        _BROWSER[0].close()
        _BROWSER[0] = None


def flatten_with_chrome(src, dest, width, height, colour):
    """Draw ``src`` at 1:1 onto an opaque ``colour`` page of exactly ``width`` x ``height`` CSS px at scale 1 in
    headless Chrome and write ``dest``: 8-bit RGB, sRGB (Chrome converts a tagged profile), not interlaced, every
    opaque pixel unchanged. Raises ``chrome.ChromeNotFound`` / ``chrome.ChromeError``."""
    folder = os.path.dirname(os.path.abspath(dest))
    os.makedirs(folder, exist_ok=True)
    page = os.path.join(folder, ".flatten-%s.html" % os.getpid())
    with open(page, "w", encoding="utf-8") as f:
        f.write('<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;'
                'background:%s}img{display:block;width:%dpx;height:%dpx}</style></head><body>'
                '<img src="%s"></body></html>' % (colour, width, height, chrome.to_url(os.path.abspath(src))))
    try:
        _browser().render(page, width, height, dest, scale=1)
    finally:
        os.unlink(page)


FLATTEN = flatten_with_chrome   # callable(src, dest, width, height, colour): tests replace it


def picture_fixes(meta):
    """What a picture needs before it's a capture (CONTRACT.md 10.4), as fix names; empty when it's fine."""
    fixes = []
    if meta.format != "png":
        fixes.append("converted-to-png")
    if meta.has_alpha:
        fixes.append("alpha-flattened")
    if meta.bit_depth == 16:
        fixes.append("16-bit-to-8-bit")
    if meta.format == "png" and meta.color_type in (0, 3, 4) or meta.format == "jpeg" and meta.color_type != 3:
        fixes.append("converted-to-rgb")
    if not meta.srgb:
        fixes.append("converted-to-srgb")
    if meta.interlaced:
        fixes.append("de-interlaced")
    return fixes


def verify_picture(src, dest, width, height, colour="#000000"):
    """Check the picture a driver wrote and put the capture at ``dest``.

    Returns ``(status, fixes, reason)``: ``("taken", fixes, None)`` with ``dest`` written (copied, or drawn
    again by ``FLATTEN`` when it needed fixes), or ``("failed", [], reason)`` for a picture that isn't one, isn't
    exactly ``width`` x ``height`` (never resized) or couldn't be fixed.
    """
    if not src or not os.path.isfile(src):
        return "failed", [], "the driver said it took a picture, but there's no file"
    try:
        meta = png.info(src)
    except (png.ImageError, OSError) as e:
        return "failed", [], "not a picture: %s" % e
    if (meta.width, meta.height) != (width, height):
        hint = " (the other way round: rotated?)" if (meta.height, meta.width) == (width, height) else \
            " (never resized: pick the device, display size or viewport that renders %dx%d)" % (width, height)
        return "failed", [], "came out %dx%d, not %dx%d%s" % (meta.width, meta.height, width, height, hint)
    fixes = picture_fixes(meta)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    if not fixes:
        shutil.copyfile(src, dest)
        return "taken", [], None
    try:
        FLATTEN(src, dest, width, height, colour)
    except chrome.ChromeNotFound as e:
        return "failed", [], "needs %s, which takes Chrome: %s" % (", ".join(fixes), e)
    except (chrome.ChromeError, OSError) as e:
        return "failed", [], "couldn't fix it (%s): %s" % (", ".join(fixes), e)
    try:
        after = png.info(dest)
    except (png.ImageError, OSError) as e:
        return "failed", [], "fixing it (%s) made no picture: %s" % (", ".join(fixes), e)
    left = picture_fixes(after)
    if (after.width, after.height) != (width, height) or left:
        if os.path.exists(dest):
            os.unlink(dest)
        return "failed", [], "fixing it (%s) left %s" % (", ".join(fixes), ", ".join(left) or "the wrong size")
    return "taken", fixes, None


# -- running --------------------------------------------------------------------------------------------------

def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def take_lock(out):
    """Claim ``<out>`` for this run (``.capture.lock`` with this process's id); raise ``Refused`` when a live
    capture holds it. Returns the lock's path."""
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, LOCK_NAME)
    if os.path.exists(path):
        try:
            with open(path) as f:
                pid = int(f.read().strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if pid and pid != os.getpid() and _pid_alive(pid):
            raise Refused("another capture (process %d) is writing to %s: wait for it, or remove %s if it's gone"
                          % (pid, out, path))
    with open(path, "w") as f:
        f.write(str(os.getpid()))
    return path


def _entry(locale, device, screen_id, driver_name):
    return {"locale": locale, "device": device["id"], "screen": screen_id, "driver": driver_name}


def _rel(locale, device_id, screen_id):
    return "/".join((locale, device_id, screen_id + ".png"))


class Run(object):
    """One capture run: the plan, the filters and options, and what it found. ``execute()`` does it."""

    def __init__(self, plan_path, devices=None, screens=None, locales=None, keep_going=False, cleanup=False,
                 dry_run=False):
        """Load the plan and check the filters name things it has (``UsageError`` otherwise)."""
        self.plan_path = os.path.abspath(plan_path)
        self.plan = load_plan(plan_path)
        self.plan_dir = os.path.dirname(self.plan_path)
        self.out = out_dir(self.plan, plan_path)
        self.keep_going = keep_going
        self.cleanup = cleanup
        self.dry_run = dry_run
        ids = [d["id"] for d in self.plan["devices"]]
        screen_ids = [s["id"] for s in self.plan["screens"]]
        all_locales = set(self.plan.get("locales") or DEFAULTS["locales"])
        for d in self.plan["devices"]:
            all_locales.update(d.get("locales") or [])
        for name, wanted, have in (("device", devices, ids), ("screen", screens, screen_ids),
                                   ("locale", locales, sorted(all_locales))):
            for w in wanted or []:
                if w not in have:
                    raise UsageError("the plan has no %s %s (it has %s)" % (name, w, ", ".join(have)))
        self.only_devices = devices
        self.only_screens = screens
        self.only_locales = locales
        self.entries = []
        self.device_notes = []
        self.environment_problem = False
        self.stopped = None
        self.moves = []

    # Which shots this run makes, for one device.

    def jobs(self, device):
        """``(locale, screen)`` pairs for a resolved device, locale by locale (so a device switches locale least)."""
        screens = [s for s in screens_for(self.plan, device)
                   if not self.only_screens or s["id"] in self.only_screens]
        pairs = []
        for locale in device["locales"]:
            if self.only_locales and locale not in self.only_locales:
                continue
            for s in screens:
                if locale in s["locales"]:
                    pairs.append((locale, s))
        return pairs

    def devices(self):
        """The resolved devices this run captures."""
        return [resolve_device(self.plan, d) for d in self.plan["devices"]
                if not self.only_devices or d["id"] in self.only_devices]

    def kept(self, locale, device_id, screen_id):
        """``previous`` when an older picture of this shot stays in ``<out>``, else ``none``."""
        return "previous" if os.path.isfile(os.path.join(self.out, locale, device_id, screen_id + ".png")) else "none"

    def not_taken(self, locale, device, screen_id, driver_name, status, reason, source=None, warnings=None,
                  status_bar="none"):
        """Record a shot that wasn't taken, keeping any previous picture."""
        e = _entry(locale, device, screen_id, driver_name)
        e.update({"status": status, "reason": reason, "kept": self.kept(locale, device["id"], screen_id),
                  "source": source or {}, "statusBar": status_bar, "fixes": [], "warnings": list(warnings or [])})
        self.entries.append(e)
        log("%-7s %s/%s/%s: %s%s" % (status, locale, device["id"], screen_id, reason,
                                     " (kept: previous)" if e["kept"] == "previous" else ""))
        return e

    def execute(self):
        """Run every device; return the report (``None`` under ``--dry-run``)."""
        started = now()
        tmp = None
        lock = None
        if self.dry_run:
            base.DRY_RUN = True
            base.LOG = lambda line: print(line)
        try:
            if not self.dry_run:
                lock = take_lock(self.out)
                tmp = tempfile.mkdtemp(prefix=".capture-", dir=self.out)
            for device in self.devices():
                self.capture_device(device, tmp)
            if self.dry_run:
                return None
            for src, dest in self.moves:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                os.replace(src, dest)
            report = self.report(started)
            jsonio.dump(report, os.path.join(self.out, REPORT_NAME))
            return report
        finally:
            close_browser()
            if self.dry_run:
                base.DRY_RUN = False
                base.LOG = base._stderr_log
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            if lock and os.path.exists(lock):
                os.unlink(lock)

    def capture_device(self, device, tmp):
        """Prepare one device, take its shots, and always reset it."""
        jobs = self.jobs(device)
        name = device["driver"]
        header = "device %s (%s, %s, %dx%d)" % (device["id"], name, device["platform"], device["width"],
                                                 device["height"])
        (print if self.dry_run else log)(header)
        if not jobs:
            log("  nothing to capture on %s" % device["id"])
            return
        if self.stopped:
            for locale, s in jobs:
                self.not_taken(locale, device, s["id"], name, "missed", self.stopped)
            return
        try:
            cls = drivers.get(name)
        except drivers.UnknownDriver as e:
            for locale, s in jobs:
                self.not_taken(locale, device, s["id"], name, "skipped", str(e))
            return
        work = os.path.join(tmp, "work", device["id"]) if tmp else os.path.join(self.out, ".capture-dry-run")
        if tmp:
            os.makedirs(work, exist_ok=True)
        driver = cls(base.Options(plan_dir=self.plan_dir, workdir=work, cleanup=self.cleanup))
        note = {"id": device["id"], "driver": name, "source": {}, "warnings": []}
        self.device_notes.append(note)
        if driver.PLATFORMS and device["platform"] not in driver.PLATFORMS:
            for locale, s in jobs:
                self.not_taken(locale, device, s["id"], name, "skipped", "the %s driver doesn't capture %s devices"
                               % (name, device["platform"]))
            return
        prepared = False
        try:
            try:
                (print if self.dry_run else log)("  prepare")
                driver.prepare(device, self.plan)
                prepared = True
                note["source"] = driver.source(device)
            except base.ToolMissing as e:
                self.environment_problem = True
                reason = "couldn't prepare %s: %s" % (device["id"], e)
            except base.DriverError as e:
                reason = "couldn't prepare %s: %s" % (device["id"], e)
            except Exception as e:  # a driver's bug: report it and still reset
                traceback.print_exc()
                reason = "the %s driver failed preparing %s: %s" % (name, device["id"], e)
            if not prepared:
                for locale, s in jobs:
                    self.not_taken(locale, device, s["id"], name, "missed", reason)
                if not self.keep_going:
                    self.stopped = "not attempted: the run stopped after %s couldn't be prepared (pass --keep-going " \
                                   "to go on)" % device["id"]
                return
            for locale, s in jobs:
                if self.stopped:
                    self.not_taken(locale, device, s["id"], name, "missed", self.stopped)
                    continue
                (print if self.dry_run else log)("  screen %s (%s)" % (s["id"], locale))
                self.shoot(driver, device, s, locale, tmp)
        finally:
            (print if self.dry_run else log)("  reset")
            try:
                warnings = driver.reset(device) or []
            except Exception as e:
                warnings = ["reset failed: %s (check the device by hand)" % e]
            for w in warnings:
                log("  warning: %s" % w)
            note["warnings"].extend(warnings)
            note["warnings"].extend(getattr(driver, "warnings", []) or [])

    def shoot(self, driver, device, screen, locale, tmp):
        """Take one shot and record it."""
        name = device["driver"]
        try:
            shot = driver.run_screen(device, screen, locale)
        except base.ToolMissing as e:
            self.environment_problem = True
            shot = base.Shot(status="missed", reason=str(e))
        except base.DriverError as e:
            shot = base.Shot(status="missed", reason=str(e))
        except Exception as e:  # a driver's bug: report it, go on to reset
            traceback.print_exc()
            shot = base.Shot(status="missed", reason="the %s driver failed: %s" % (name, e))
        rel = _rel(locale, device["id"], screen["id"])
        if self.dry_run:
            print("  -> %s %s" % ("would save" if shot.status == "taken" else shot.status,
                                  rel if shot.status == "taken" else (shot.reason or "")))
            return
        if shot.status != "taken":
            self.not_taken(locale, device, screen["id"], name, shot.status, shot.reason or "not reached",
                           shot.source, shot.warnings, shot.status_bar)
            if shot.status in ("missed", "failed"):
                self.stop_after(rel)
            return
        dest = os.path.join(tmp, "out", locale, device["id"], screen["id"] + ".png")
        status, fixes, reason = verify_picture(shot.path, dest, device["width"], device["height"],
                                               screen.get("flatten") or device.get("flatten") or "#000000")
        if status != "taken":
            self.not_taken(locale, device, screen["id"], name, "failed", reason, shot.source, shot.warnings,
                           shot.status_bar)
            self.stop_after(rel)
            return
        e = _entry(locale, device, screen["id"], name)
        e.update({"status": "taken", "path": rel, "width": device["width"], "height": device["height"],
                  "sha256": png.sha256(dest), "source": shot.source, "statusBar": shot.status_bar,
                  "fixes": list(shot.fixes) + fixes, "warnings": list(shot.warnings)})
        self.entries.append(e)
        self.moves.append((dest, os.path.join(self.out, locale, device["id"], screen["id"] + ".png")))
        log("taken   %s%s" % (rel, (" (%s)" % ", ".join(e["fixes"])) if e["fixes"] else ""))

    def stop_after(self, rel):
        """Without ``--keep-going``, the rest of the run isn't attempted after a missed or failed shot."""
        if not self.keep_going and not self.stopped:
            self.stopped = "not attempted: the run stopped after %s (pass --keep-going to go on)" % rel

    def report(self, started):
        """The report: this run's shots, plus the previous report's for shots this run didn't make."""
        keys = set((e["locale"], e["device"], e["screen"]) for e in self.entries)
        previous = []
        old_path = os.path.join(self.out, REPORT_NAME)
        if os.path.isfile(old_path):
            try:
                old = jsonio.load(old_path)
                previous = [e for e in (old.get("shots") or [])
                            if isinstance(e, dict) and (e.get("locale"), e.get("device"), e.get("screen")) not in keys]
            except (jsonio.JsonError, OSError, AttributeError):
                previous = []
        return {"version": 1, "startedAt": _stamp(started), "finishedAt": _stamp(now()),
                "plan": os.path.basename(self.plan_path), "devices": self.device_notes,
                "shots": previous + self.entries}

    def exit_code(self):
        """0, 1 (a failure, or a miss/skip with nothing kept) or 3 (a tool was missing)."""
        if self.environment_problem:
            return EXIT_USAGE
        for e in self.entries:
            if e["status"] == "failed":
                return EXIT_ERRORS
            if e["status"] in ("missed", "skipped") and e.get("kept") != "previous":
                return EXIT_ERRORS
        return EXIT_OK


def summary(entries):
    """One line: how many taken, missed, failed, skipped."""
    counts = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    return ", ".join("%d %s" % (counts.get(k, 0), k) for k in ("taken", "missed", "failed", "skipped"))


def parser():
    p = argparse.ArgumentParser(prog="capture.py", description="Capture an app's screens at the stores' exact sizes.")
    p.add_argument("--plan", default="capture-plan.json", help="the capture plan (default capture-plan.json)")
    p.add_argument("--devices", help="only these devices (comma-separated ids)")
    p.add_argument("--screens", help="only these screens (comma-separated ids)")
    p.add_argument("--locales", help="only these locales (comma-separated)")
    p.add_argument("--keep-going", action="store_true", help="go on after a shot is missed or fails")
    p.add_argument("--cleanup", action="store_true",
                   help="delete the simulators and emulators this skill created (appstores-<device id>) when done")
    p.add_argument("--dry-run", action="store_true", help="print what each driver would run; run nothing")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        run = Run(args.plan, _csv(args.devices), _csv(args.screens), _csv(args.locales), args.keep_going,
                  args.cleanup, args.dry_run)
        report = run.execute()
    except UsageError as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    except Refused as e:
        print("refused: %s" % e, file=sys.stderr)
        return EXIT_REFUSED
    if report is None:
        return EXIT_OK
    print("%s: %s" % (os.path.join(run.out, REPORT_NAME), summary(run.entries)))
    return run.exit_code()


if __name__ == "__main__":
    sys.exit(main())
