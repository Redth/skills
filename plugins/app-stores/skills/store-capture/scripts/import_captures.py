#!/usr/bin/env python3
"""import_captures.py: bring another tool's screenshots into the captures layout, checked like capture.py's.

    import_captures.py --from fastlane-snapshot|fastlane-screengrab|xcresult|maestro|flutter|detox|playwright|folder
                       <path> [--map mapping.json] [--plan capture-plan.json] [--out captures]
                       [--locale en-US] [--device iphone-6.9] [--dry-run]

Each source's own layout is read (``references/importing.md``):

- ``fastlane-snapshot``: ``<path>/<language>/<device name>-<name>.png`` (snapshot's ``output_directory``).
- ``fastlane-screengrab``: ``<path>/<locale>/images/<type>Screenshots/<name>_<timestamp>.png`` (the newest of
  each name wins); the device is the folder (``phoneScreenshots``, ``tenInchScreenshots``…).
- ``xcresult``: a ``.xcresult`` bundle (exported with ``xcrun xcresulttool export attachments``) or a folder
  already exported (its ``manifest.json``): the screen is the attachment's name, the device the test's device,
  the locale its test plan configuration.
- ``maestro``: ``maestro test --test-output-dir``'s folder: every ``takeScreenshot`` (the path under the flow's
  ``takeScreenshot`` folder is the screen).
- ``flutter``: the folder an ``integrationDriver(onScreenshot: …)`` writes to.
- ``detox``: the artifacts folder (``<configuration>.<time>/<test>/<name>.png``); the configuration is the device.
  Detox's own ``testStart``/``testDone``/``testFailure`` pictures are left out.
- ``playwright``: a folder of ``page.screenshot`` files (visual-comparison ``-actual``/``-diff``/``-expected``
  files left out); a project folder can name the device.
- ``folder``: ``<locale>/<device>/<screen>.png``, or any folder: a path part that names a locale or device says so.

The mapping file says which of the source's names is which of ours (anything it doesn't name keeps its own name,
made an id: lower case, ``[a-z0-9.-]``)::

    {"locales": {"de": "de-DE"}, "devices": {"iPhone 17 Pro Max": "iphone-6.9"},
     "screens": {"01Plan": "plan"}, "locale": "en-US", "device": "iphone-6.9", "onlyMapped": false}

With ``screens`` given and ``onlyMapped`` true, pictures it doesn't name are left out (listed). ``locale`` and
``device`` (or ``--locale``/``--device``) are used when the source doesn't say.

With ``--plan``, each device's promised ``width`` x ``height`` is checked (any other size is ``failed``, never
resized), the plan's ``out`` is the default ``--out``, and a device or locale the plan doesn't have is a warning.
Every picture is checked as capture.py checks its own (8-bit RGB, sRGB, no alpha, not interlaced; fixed through
headless Chrome when it isn't, the fix listed). Pictures go into a temporary folder in ``<out>`` and are moved
into place at the end; ``<out>/capture-report.json`` gets an entry for each, driver ``import``, merged with the
report already there.

Exit codes: 0 done; 1 a picture failed (or nothing was found); 2 refused (a capture is writing to ``<out>``);
3 usage or environment.
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import shutil
import sys
import tempfile

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
import capture  # noqa: E402
from drivers import base  # noqa: E402
from drivers import xcuitest  # noqa: E402

SOURCES = ("fastlane-snapshot", "fastlane-screengrab", "xcresult", "maestro", "flutter", "detox", "playwright",
           "folder")
PICTURES = (".png", ".jpg", ".jpeg")
# fastlane screengrab's device folders.
SCREENGRAB_TYPES = ("phoneScreenshots", "sevenInchScreenshots", "tenInchScreenshots", "tvScreenshots",
                    "wearScreenshots")
DETOX_OWN = ("testStart", "testDone", "testFailure")
PLAYWRIGHT_COMPARE = re.compile(r"-(actual|diff|expected|previous)$")
LOCALE_LIKE = re.compile(r"^[a-z]{2,3}([-_][A-Za-z]{2,4})?([-_][A-Za-z0-9]{2,8})?$")
SCREENGRAB_STAMP = re.compile(r"_(\d{10,})$")

# One picture found in a source: its file, the source's own locale/device/screen names (None: not said), and
# a sort key (the newest wins when two map to the same shot).
Found = collections.namedtuple("Found", ["file", "locale", "device", "screen", "order"])


class UsageError(Exception):
    """Bad arguments, a source that isn't there, an unreadable mapping."""


# -- names -------------------------------------------------------------------------------------------------

def slug(name):
    """A name as an id: lower case, ``[a-z0-9.-]``, runs of anything else one ``-``."""
    out = re.sub(r"[^a-z0-9.]+", "-", str(name).strip().lower()).strip("-.")
    return out or "shot"


def normal_locale(code):
    """``de_DE`` → ``de-DE``, ``en-us`` → ``en-US``, ``zh-hans`` → ``zh-Hans`` (BCP 47's usual case)."""
    parts = re.split(r"[-_]", str(code))
    out = [parts[0].lower()]
    for p in parts[1:]:
        if len(p) == 2:
            out.append(p.upper())
        elif len(p) == 4:
            out.append(p.title())
        else:
            out.append(p)
    return "-".join(out)


def split_snapshot_name(stem, devices=()):
    """Split fastlane snapshot's ``<device name>-<screenshot name>`` file stem.

    A device name from ``devices`` (the mapping's) that the stem starts with wins (longest first); otherwise the
    first ``-`` whose right side has no space (device names have spaces, snapshot names rarely do:
    ``iPad Pro 13-inch (M4)-01Plan``). Returns ``(device, name)``; ``(None, stem)`` when it can't tell."""
    for d in sorted(devices, key=len, reverse=True):
        if stem.startswith(d + "-") and len(stem) > len(d) + 1:
            return d, stem[len(d) + 1:]
    for i, ch in enumerate(stem):
        if ch == "-" and i > 0 and " " not in stem[i + 1:] and stem[i + 1:]:
            return stem[:i], stem[i + 1:]
    return None, stem


# -- reading each source ------------------------------------------------------------------------------------

def _pictures(root):
    """Every picture file under ``root``, sorted, as absolute paths."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() in PICTURES and not name.startswith("."):
                out.append(os.path.join(dirpath, name))
    return out


def read_snapshot(root, mapping):
    """fastlane snapshot: ``<language>/<device name>-<name>.png``."""
    found = []
    devices = list((mapping.get("devices") or {}).keys())
    for path in _pictures(root):
        rel = os.path.relpath(path, root).split(os.sep)
        stem = os.path.splitext(rel[-1])[0]
        device, name = split_snapshot_name(stem, devices)
        locale = rel[-2] if len(rel) >= 2 else None
        found.append(Found(path, locale, device, name, os.path.getmtime(path)))
    return found


def read_screengrab(root, mapping):
    """fastlane screengrab: ``<locale>/images/<type>Screenshots/<name>_<timestamp>.png``."""
    found = []
    for path in _pictures(root):
        rel = os.path.relpath(path, root).split(os.sep)
        device = next((p for p in rel[:-1] if p in SCREENGRAB_TYPES), None)
        if device is None:
            continue
        locale = None
        if "images" in rel:
            i = rel.index("images")
            locale = rel[i - 1] if i >= 1 else None
        stem = os.path.splitext(rel[-1])[0]
        m = SCREENGRAB_STAMP.search(stem)
        order = int(m.group(1)) if m else os.path.getmtime(path)
        name = stem[:m.start()] if m else stem
        found.append(Found(path, locale, device, name, order))
    return found


def export_xcresult(bundle, dest):
    """Export a result bundle's attachments into ``dest`` with ``xcresulttool`` (writes ``manifest.json``)."""
    base.run(["xcrun", "xcresulttool", "export", "attachments", "--path", bundle, "--output-path", dest],
             timeout=600)
    return dest


def read_xcresult(root, mapping, workdir):
    """A ``.xcresult`` bundle (exported first) or an exported folder with ``manifest.json``."""
    folder = root
    if root.rstrip("/").endswith(".xcresult") or not os.path.isfile(os.path.join(root, "manifest.json")):
        if not root.rstrip("/").endswith(".xcresult"):
            raise UsageError("%s isn't a .xcresult bundle or a folder xcresulttool exported (no manifest.json)" % root)
        folder = export_xcresult(root, os.path.join(workdir, "xcresult"))
    if not os.path.isfile(os.path.join(folder, "manifest.json")):
        raise UsageError("xcresulttool wrote no manifest.json in %s" % folder)
    found = []
    for name, path, _test, att in xcuitest.read_manifest(folder):
        if not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in PICTURES:
            continue
        found.append(Found(path, att.get("configurationName") or None, att.get("deviceName") or None, name,
                           att.get("timestamp") or 0))
    return found


def _tagged(rel_parts, mapping, plan_locales, plan_devices):
    """The locale and device a path's folders name (a mapping key, a plan id, or a locale-looking name)."""
    locales = set((mapping.get("locales") or {}).keys()) | set(plan_locales)
    devices = set((mapping.get("devices") or {}).keys()) | set(plan_devices)
    locale = device = None
    for part in rel_parts:
        if device is None and part in devices:
            device = part
        elif locale is None and (part in locales or LOCALE_LIKE.match(part) and part not in devices):
            locale = part
    return locale, device


def read_generic(root, mapping, kind, plan_locales=(), plan_devices=()):
    """Maestro, Flutter, Detox, Playwright and plain folders: every picture, its screen from its name (Maestro:
    its path under ``takeScreenshot``), its locale and device from folders that name one."""
    found = []
    for path in _pictures(root):
        rel = os.path.relpath(path, root).split(os.sep)
        stem = os.path.splitext(rel[-1])[0]
        folders = rel[:-1]
        name = stem
        if kind == "maestro" and "takeScreenshot" in folders:
            i = len(folders) - 1 - folders[::-1].index("takeScreenshot")
            name = "/".join(folders[i + 1:] + [stem])
            folders = folders[:i]
        if kind == "detox" and stem in DETOX_OWN:
            continue
        if kind == "playwright" and PLAYWRIGHT_COMPARE.search(stem):
            continue
        locale, device = _tagged(folders, mapping, plan_locales, plan_devices)
        if kind == "detox" and device is None and folders:
            # <configuration>.<ISO time>/…: the configuration names the device.
            device = re.sub(r"\.\d{4}-\d{2}-\d{2}.*$", "", folders[0]) or None
        if kind == "folder" and len(rel) == 3:
            # <locale>/<device>/<screen>.png: the folders say what nothing else did.
            locale = locale or rel[0]
            device = device or rel[1]
        found.append(Found(path, locale, device, name, os.path.getmtime(path)))
    return found


def read_source(kind, root, mapping, workdir, plan_locales=(), plan_devices=()):
    """The pictures a source has, as ``Found`` tuples."""
    if kind == "fastlane-snapshot":
        return read_snapshot(root, mapping)
    if kind == "fastlane-screengrab":
        return read_screengrab(root, mapping)
    if kind == "xcresult":
        return read_xcresult(root, mapping, workdir)
    return read_generic(root, mapping, kind, plan_locales, plan_devices)


# -- mapping onto our names ---------------------------------------------------------------------------------

def resolve(found, mapping, default_locale=None, default_device=None):
    """Our ``(locale, device, screen)`` for one picture, or ``(None, None, None, why)`` when it's left out.
    Returns ``(locale, device, screen, why)``."""
    locales = mapping.get("locales") or {}
    devices = mapping.get("devices") or {}
    screens = mapping.get("screens") or {}
    if found.screen in screens:
        screen = screens[found.screen]
    elif screens and mapping.get("onlyMapped"):
        return None, None, None, "not in the mapping's screens"
    else:
        screen = slug(found.screen)
    if found.locale is not None and found.locale in locales:
        locale = locales[found.locale]
    elif found.locale is not None:
        locale = normal_locale(found.locale)
    else:
        locale = default_locale or mapping.get("locale")
    if found.device is not None and found.device in devices:
        device = devices[found.device]
    elif found.device is not None:
        device = slug(found.device)
    else:
        device = default_device or mapping.get("device")
    if not locale:
        return None, None, None, "the source doesn't say its locale: give --locale or the mapping's \"locale\""
    if not device:
        return None, None, None, "the source doesn't say its device: give --device or the mapping's \"device\""
    return locale, device, screen, None


# -- importing ---------------------------------------------------------------------------------------------

def load_mapping(path):
    """The mapping file (``{}`` without one)."""
    if not path:
        return {}
    try:
        data = jsonio.load(path)
    except (jsonio.JsonError, OSError) as e:
        raise UsageError("the mapping %s: %s" % (path, e)) from None
    if not isinstance(data, dict):
        raise UsageError("the mapping %s isn't an object" % path)
    return data


def plan_devices(plan):
    """The plan's devices by id, resolved (``{}`` without a plan)."""
    if not plan:
        return {}
    return dict((d["id"], capture.resolve_device(plan, d)) for d in plan.get("devices") or [])


def import_captures(kind, source, out, mapping=None, plan=None, plan_name=None, default_locale=None,
                    default_device=None, dry_run=False):
    """Import ``source`` (a ``kind`` from ``SOURCES``) into ``out``; return ``(report_or_None, entries, left_out)``.
    ``left_out`` lists ``(file, why)``; under ``dry_run`` nothing is written and the report is ``None``."""
    mapping = mapping or {}
    devices = plan_devices(plan)
    p_locales = set(plan.get("locales") or []) if plan else set()
    for d in devices.values():
        p_locales.update(d.get("locales") or [])
    started = capture.now()
    work = tempfile.mkdtemp(prefix="appstores-import-")
    try:
        found = read_source(kind, source, mapping, work, sorted(p_locales), sorted(devices))
        chosen = collections.OrderedDict()
        left_out = []
        for f in found:
            locale, device, screen, why = resolve(f, mapping, default_locale, default_device)
            if why:
                left_out.append((f.file, why))
                continue
            key = (locale, device, screen)
            if key in chosen:
                older, newer = sorted([chosen[key], f], key=lambda x: x.order)
                left_out.append((older.file, "an older picture of %s/%s/%s" % key))
                chosen[key] = newer
            else:
                chosen[key] = f
        entries = []
        moves = []
        lock = None
        tmp = None
        if not dry_run:
            lock = capture.take_lock(out)
            tmp = tempfile.mkdtemp(prefix=".import-", dir=out)
        try:
            for (locale, device_id, screen), f in chosen.items():
                entries.append(_import_one(f, locale, device_id, screen, kind, source, devices, p_locales, tmp,
                                           moves, dry_run))
            if dry_run:
                return None, entries, left_out
            for src, rel in moves:
                dest = os.path.join(out, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                os.replace(src, dest)
            report = _report(out, entries, started, plan_name)
            jsonio.dump(report, os.path.join(out, capture.REPORT_NAME))
            return report, entries, left_out
        finally:
            capture.close_browser()
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            if lock and os.path.exists(lock):
                os.unlink(lock)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _import_one(f, locale, device_id, screen, kind, source, devices, p_locales, tmp, moves, dry_run):
    """Check one picture and stage it; return its report entry."""
    rel = "/".join((locale, device_id, screen + ".png"))
    entry = {"locale": locale, "device": device_id, "screen": screen, "driver": "import",
             "source": {"from": kind, "file": os.path.relpath(f.file, source)}, "statusBar": "unverified",
             "fixes": [], "warnings": []}
    if devices and device_id not in devices:
        entry["warnings"].append("the plan has no device %s" % device_id)
    if p_locales and locale not in p_locales:
        entry["warnings"].append("the plan has no locale %s" % locale)
    try:
        meta = png.info(f.file)
    except (png.ImageError, OSError) as e:
        entry.update({"status": "failed", "reason": "not a picture: %s" % e, "kept": "none"})
        return entry
    device = devices.get(device_id)
    width, height = (device["width"], device["height"]) if device else (meta.width, meta.height)
    if not device:
        entry["warnings"].append("no promised size to check (no --plan, or the plan has no %s): kept at %dx%d"
                                 % (device_id, meta.width, meta.height))
    if dry_run:
        ok = (meta.width, meta.height) == (width, height)
        entry.update({"status": "taken" if ok else "failed", "path": rel, "width": meta.width, "height": meta.height})
        if not ok:
            entry["reason"] = "came out %dx%d, not %dx%d" % (meta.width, meta.height, width, height)
        return entry
    dest = os.path.join(tmp, rel)
    colour = (device or {}).get("flatten") or "#000000"
    status, fixes, reason = capture.verify_picture(f.file, dest, width, height, colour)
    if status != "taken":
        entry.update({"status": "failed", "reason": reason, "kept": "previous" if os.path.isfile(
            os.path.join(os.path.dirname(tmp), rel)) else "none"})
        return entry
    entry.update({"status": "taken", "path": rel, "width": width, "height": height, "sha256": png.sha256(dest),
                  "fixes": fixes})
    moves.append((dest, rel))
    return entry


def _report(out, entries, started, plan_name):
    """This import's entries, plus the existing report's for shots it didn't bring."""
    keys = set((e["locale"], e["device"], e["screen"]) for e in entries)
    previous = []
    devices = []
    old_path = os.path.join(out, capture.REPORT_NAME)
    old = {}
    if os.path.isfile(old_path):
        try:
            old = jsonio.load(old_path) or {}
            previous = [e for e in (old.get("shots") or []) if isinstance(e, dict)
                        and (e.get("locale"), e.get("device"), e.get("screen")) not in keys]
            devices = list(old.get("devices") or [])
        except (jsonio.JsonError, OSError, AttributeError):
            previous = []
    return {"version": 1, "startedAt": capture._stamp(started), "finishedAt": capture._stamp(capture.now()),
            "plan": plan_name or old.get("plan"), "devices": devices, "shots": previous + entries}


def parser():
    p = argparse.ArgumentParser(prog="import_captures.py",
                                description="Bring another tool's screenshots into the captures layout.")
    p.add_argument("--from", dest="kind", required=True, choices=SOURCES, help="the tool that made them")
    p.add_argument("path", help="its output folder (or a .xcresult bundle)")
    p.add_argument("--map", help="the mapping file: its names to our locales, devices and screens")
    p.add_argument("--plan", help="the capture plan, to check each device's size (and for the default --out)")
    p.add_argument("--out", help="the captures folder (default: the plan's out, else captures)")
    p.add_argument("--locale", help="the locale, when the source doesn't say")
    p.add_argument("--device", help="the device id, when the source doesn't say")
    p.add_argument("--dry-run", action="store_true", help="say what would be imported; write nothing")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if not os.path.exists(args.path):
            raise UsageError("%s doesn't exist" % args.path)
        mapping = load_mapping(args.map)
        plan = None
        out = args.out
        if args.plan:
            try:
                plan = capture.load_plan(args.plan)
            except capture.UsageError as e:
                raise UsageError(str(e)) from None
            if not out:
                out = capture.out_dir(plan, args.plan)
        out = os.path.abspath(out or "captures")
        report, entries, left_out = import_captures(
            args.kind, os.path.abspath(args.path), out, mapping, plan,
            os.path.basename(args.plan) if args.plan else None, args.locale, args.device, args.dry_run)
    except UsageError as e:
        print("error: %s" % e, file=sys.stderr)
        return capture.EXIT_USAGE
    except capture.Refused as e:
        print("refused: %s" % e, file=sys.stderr)
        return capture.EXIT_REFUSED
    except base.ToolMissing as e:
        print("error: %s" % e, file=sys.stderr)
        return capture.EXIT_USAGE
    except base.DriverError as e:
        print("error: %s" % e, file=sys.stderr)
        return capture.EXIT_ERRORS
    for e in entries:
        line = "%-7s %s/%s/%s" % (("would " if args.dry_run and e["status"] == "taken" else "") + e["status"],
                                  e["locale"], e["device"], e["screen"])
        detail = e.get("reason") or (", ".join(e["fixes"]) if e.get("fixes") else "")
        print(line + ("  (%s)" % detail if detail else "") + "  <- " + e["source"]["file"])
        for w in e.get("warnings") or []:
            print("        warning: %s" % w)
    for path, why in left_out:
        print("left out %s: %s" % (os.path.relpath(path, os.path.abspath(args.path)) if path.startswith(
            os.path.abspath(args.path)) else path, why))
    if report is not None:
        print("%s: %s" % (os.path.join(out, capture.REPORT_NAME), capture.summary(entries)))
    if not entries:
        print("nothing to import from %s" % args.path, file=sys.stderr)
        return capture.EXIT_ERRORS
    return capture.EXIT_ERRORS if any(e["status"] == "failed" for e in entries) else capture.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
