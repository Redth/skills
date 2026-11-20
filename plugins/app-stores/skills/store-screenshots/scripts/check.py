#!/usr/bin/env python3
"""check.py: check a rendered screenshot set against each store's rules and the design's own limits.

    check.py [--config store-screenshots.json] [--listing store-listing.json] [--report render-report.json]
             [--baseline [design/baseline] | --no-baseline] [--json]

Reads ``<out>/render-report.json`` (what ``render.py`` wrote: every file with its caption, frame and boxes) and
the PNGs themselves, then decides what a script can:

- every file rendered, at its target's exact size, opaque, an accepted size for its store's slot;
- counts per store and slot (the rules' ``count`` rules), required slots (Apple's display types);
- captions: fit, at the font floor, more than two lines, more than six words, missing glyphs, forbidden words
  (the rules' ``words`` and ``pattern`` rules whose fields include ``captions``), text share (Google's 20%),
  their size in Apple's search row, and contrast (WCAG ratio of the ink against the median pixel behind the
  caption's box, measured in the PNG);
- the store's ``design`` table: frames, backgrounds and captions per slot (none on Wear OS), a user's Apple
  bezel used as is, more than half of an Apple set showing the app in use, Play's UI in the first three;
- seams of a panorama, captures shown larger than they are, and what fell back to the primary locale.

- the set's own consistency: the device in the same place on every non-hero shot of a target (0.2u) and the
  caption's top too (0.5u); shots 1-3's captions big enough for search (9.5u on a tall slot);
- with a style: its copy rules (words, lines, case), its roles; with a locked style, a config theme that
  contradicts it (an error) and layouts outside its roles;
- with an approved baseline (``design/baseline``, used by itself when it's there): the locked style unchanged (an
  error otherwise), and each file's drift from its baseline counterpart (caption size, top, height and lines, the
  device's box and frame, tilt, text share, ink, accent, background, layout) past the style's ``drift``
  tolerances (warnings: the user decides).

What it can't decide is listed for a person to check by eye. ``store-listing.json`` (beside the config, or
``--listing``) is read when present: its ``stores.google.slots`` say which Play slot each target fills, its
category whether the app is a game, and its ``rules.relax`` relaxes rules by id here too.

Exit codes: 0 no errors; 1 an error found; 3 usage or environment (no config, no render report).
"""

from __future__ import annotations

import argparse
import collections
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import rules  # noqa: E402
from appstores_lib import text as textlib  # noqa: E402
import styles  # noqa: E402

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
RULES_DIR = os.path.join(SKILL_DIR, "rules")

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_REFUSED = 2
EXIT_USAGE = 3

STORES = ("apple", "google")
STORE_NAMES = {"apple": "App Store", "google": "Google Play", "design": "The set",
               "amazon": "Amazon Appstore", "steam": "Steam", "itch": "itch.io"}
GOOGLE_SCREEN_SLOTS = ("phone", "tablet7", "tablet10", "tv", "wear")

# The search row on an iPhone (derived, not measured: a 402-pt-wide screen, 16-pt margins and 8-pt gaps, three
# portrait shots, so each is about 118 pt wide; one landscape shot spans the row). iOS's smallest text is 11 pt.
SEARCH_SCREEN_PT = 402.0
SEARCH_MARGIN_PT = 16.0
SEARCH_GAP_PT = 8.0
SEARCH_SHOTS = 3
MIN_TEXT_PT = 11.0

# Shots 1-3's caption in u (1% of the width) by aspect class: at about 118 pt in Apple's search row, 9.5u on a tall
# shot is 11 pt (screenshot-craft research; mid and wide from the iPad and landscape sets). Square: none.
FIRST_SHOTS_MIN_U = {"tall": 9.5, "mid": 6.0, "wide": 4.0}
# Inside one set: the device box (x, y, width) and the caption's top across non-hero shots of a layout (u).
SET_DEVICE_TOLERANCE_U = 0.2
SET_CAPTION_TOLERANCE_U = 0.5
DEVICE_LAYOUTS = ("framed", "framed-bleed", "tilt", "pair", "callout")

MIN_CONTRAST = 4.5
MAX_CAPTION_LINES = 2
MAX_CAPTION_WORDS = 6
UPSCALE_TOLERANCE = 1.01
DEFAULT_SEAM_UNITS = 6.0

# Layouts that show no capture of the app (counted against Apple's "more than half in use") and layouts that add
# a background around the capture (what Wear OS forbids).
MARKETING_LAYOUTS = ("hero",)
BACKGROUND_LAYOUTS = ("band", "framed", "framed-bleed", "tilt", "pair", "callout", "hero")

RTL_LANGUAGES = ("ar", "he", "fa", "ur", "yi", "ps", "sd", "ug", "dv", "ckb")


class UsageError(Exception):
    """A usage or environment problem: exit 3 with this message."""


def search_shot_points(width, height):
    """How wide (in points) one shot of this pixel size is drawn in the App Store's search row on an iPhone:
    three portrait shots share the row; a landscape one fills it."""
    row = SEARCH_SCREEN_PT - 2 * SEARCH_MARGIN_PT
    if width > height:
        return row
    return (row - (SEARCH_SHOTS - 1) * SEARCH_GAP_PT) / SEARCH_SHOTS


def points_at(font_px, width_px, shown_pt):
    """A caption's size in points when a ``width_px``-wide picture is drawn ``shown_pt`` points wide."""
    if not font_px or not width_px:
        return None
    return float(font_px) * shown_pt / float(width_px)


# ---------------------------------------------------------------------------------------------------------
# Colour and contrast

_NAMED = {"white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0), "green": (0, 128, 0),
          "blue": (0, 0, 255), "yellow": (255, 255, 0), "gray": (128, 128, 128), "grey": (128, 128, 128)}


def parse_colour(value):
    """An ``(r, g, b)`` tuple from a CSS colour (``#rgb``, ``#rrggbb``, ``#rrggbbaa``, ``rgb()``/``rgba()``, a
    few names, or a ``[r, g, b]`` list), else ``None``."""
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return tuple(max(0, min(255, int(round(float(v))))) for v in value[:3])
        except (TypeError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    if s in _NAMED:
        return _NAMED[s]
    m = re.match(r"^#([0-9a-f]{3,8})$", s)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            return tuple(int(c * 2, 16) for c in h[:3])
        if len(h) in (6, 8):
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        return None
    m = re.match(r"^rgba?\(([^)]*)\)$", s)
    if m:
        parts = [p for p in re.split(r"[\s,/]+", m.group(1)) if p]
        try:
            out = []
            for p in parts[:3]:
                out.append(float(p[:-1]) * 2.55 if p.endswith("%") else float(p))
            return tuple(max(0, min(255, int(round(v)))) for v in out)
        except ValueError:
            return None
    return None


_LINEAR = [(c / 255.0) / 12.92 if c / 255.0 <= 0.04045 else ((c / 255.0 + 0.055) / 1.055) ** 2.4
           for c in range(256)]


def luminance(rgb):
    """WCAG relative luminance of an ``(r, g, b)`` colour."""
    r, g, b = rgb
    return 0.2126 * _LINEAR[r] + 0.7152 * _LINEAR[g] + 0.0722 * _LINEAR[b]


def contrast_ratio(l1, l2):
    """WCAG contrast ratio of two relative luminances (1 to 21)."""
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def median_luminance(pixels, width, height, box, samples=40000):
    """The median relative luminance of the RGB pixels inside ``box`` ([x, y, w, h] in pixels, clipped to the
    picture), sampled on a grid of about ``samples`` points. ``None`` for an empty box."""
    x, y, w, h = [float(v) for v in box]
    x0, y0 = max(0, int(math.floor(x))), max(0, int(math.floor(y)))
    x1, y1 = min(width, int(math.ceil(x + w))), min(height, int(math.ceil(y + h)))
    if x1 <= x0 or y1 <= y0:
        return None
    step = max(1, int(math.sqrt((x1 - x0) * (y1 - y0) / float(samples))))
    values = []
    for yy in range(y0, y1, step):
        row = yy * width * 3
        for xx in range(x0, x1, step):
            i = row + xx * 3
            values.append(0.2126 * _LINEAR[pixels[i]] + 0.7152 * _LINEAR[pixels[i + 1]]
                          + 0.0722 * _LINEAR[pixels[i + 2]])
    values.sort()
    n = len(values)
    if n % 2:
        return values[n // 2]
    return (values[n // 2 - 1] + values[n // 2]) / 2.0


# ---------------------------------------------------------------------------------------------------------
# Sizes

def _size_text(size):
    return "%dx%d" % (size[0], size[1])


def fits(size, sizes, orientation=None):
    """True if ``size`` is one of ``sizes`` (either orientation unless ``orientation`` says otherwise)."""
    w, h = size
    for sw, sh in sizes:
        if orientation == "asListed":
            ok = (w, h) == (sw, sh)
        elif orientation == "portrait":
            ok = (w, h) == (min(sw, sh), max(sw, sh))
        elif orientation == "landscape":
            ok = (w, h) == (max(sw, sh), min(sw, sh))
        else:
            ok = (w, h) in ((sw, sh), (sh, sw))
        if ok:
            return True
    return False


def in_range(size, rng):
    """True if each side is within ``minSide``..``maxSide`` and long/short within ``minAspect``..``maxAspect``."""
    w, h = size
    lo, hi = min(w, h), max(w, h)
    if rng.get("minSide") is not None and lo < rng["minSide"]:
        return False
    if rng.get("maxSide") is not None and hi > rng["maxSide"]:
        return False
    aspect = hi / float(lo) if lo else float("inf")
    if aspect < float(rng.get("minAspect", 1)) - 1e-3:
        return False
    if rng.get("maxAspect") is not None and aspect > float(rng["maxAspect"]) + 1e-3:
        return False
    return True


def describe_range(rng):
    """A range in words: "each side 320-3840 px, long side at most 2x the short"."""
    parts = []
    if rng.get("minSide") is not None or rng.get("maxSide") is not None:
        parts.append("each side %s-%s px" % (rng.get("minSide", 1), rng.get("maxSide", "any")))
    lo, hi = rng.get("minAspect"), rng.get("maxAspect")
    if lo is not None and hi is not None and abs(lo - hi) < 1e-6:
        parts.append("square" if abs(lo - 1) < 1e-6 else "long side %gx the short" % lo)
    elif lo is not None and hi is not None:
        parts.append("long side %g-%gx the short" % (lo, hi))
    elif hi is not None:
        parts.append("long side at most %gx the short" % hi)
    return ", ".join(parts)


# ---------------------------------------------------------------------------------------------------------
# Inputs

def _get(obj, *path):
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _box(value):
    """A [x, y, w, h] box as floats, or ``None``."""
    if isinstance(value, dict):
        value = [value.get("x"), value.get("y"), value.get("w", value.get("width")),
                 value.get("h", value.get("height"))]
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [float(v) for v in value]
    except (TypeError, ValueError):
        return None


def _overlaps(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


class Inputs:
    """Everything a check or a sheet reads: the design config, the render report, ``store-listing.json`` when
    there is one, and each store's rules and ``design`` table."""

    def __init__(self, config_path, listing_path=None, rules_dir=RULES_DIR, report_path=None, style_path=None):
        if not os.path.isfile(config_path):
            raise UsageError("no design config at %s (pass --config)" % config_path)
        self.config_path = config_path
        self.base = os.path.dirname(os.path.abspath(config_path))
        self.raw_config = jsonio.load(config_path)
        if not isinstance(self.raw_config, dict):
            raise UsageError("%s isn't a JSON object" % config_path)
        self.design_dir = styles.design_dir(config_path, self.raw_config)
        self.style_path = styles.style_path_for(config_path, self.raw_config, style_path)
        self.style = None
        if self.style_path:
            try:
                self.style = styles.load_style(self.style_path)
            except styles.StyleError as e:
                raise UsageError(str(e))
        try:
            self.config = styles.apply(self.raw_config, self.style)
        except styles.StyleError as e:
            raise UsageError(str(e))
        self.out = os.path.join(self.base, self.config.get("out") or "screenshots")
        self.report_path = report_path or os.path.join(self.out, "render-report.json")
        if not os.path.isfile(self.report_path):
            raise UsageError("no render report at %s: run render.py first%s" % (
                self.report_path, "" if report_path else " (or pass --report)"))
        self.report = jsonio.load(self.report_path)
        if not isinstance(self.report, dict) or not isinstance(self.report.get("files"), list):
            raise UsageError("%s has no \"files\" list" % self.report_path)
        self.files = [f for f in self.report["files"] if isinstance(f, dict)]
        if listing_path is None:
            guess = os.path.join(self.base, "store-listing.json")
            listing_path = guess if os.path.isfile(guess) else None
        elif not os.path.isfile(listing_path):
            raise UsageError("no store listing at %s" % listing_path)
        self.listing_path = listing_path
        self.listing = jsonio.load(listing_path) if listing_path else {}
        if not isinstance(self.listing, dict):
            self.listing = {}
        self.rules_dir = rules_dir
        self.rulesets = {}
        self.designs = {}
        for store in self.stores():
            if store in STORES:
                self.rulesets[store] = rules.load(store, rules_dir)
                data = jsonio.load(os.path.join(rules_dir, "%s.json" % store))
                self.designs[store] = data.get("design") or {}

    # -- the config ------------------------------------------------------------------------------------

    @property
    def targets(self):
        """``{target id: target}`` in the config's order."""
        t = self.config.get("targets")
        return t if isinstance(t, dict) else {}

    @property
    def shots(self):
        """The config's shots, in order."""
        return [s for s in (self.config.get("shots") or []) if isinstance(s, dict) and s.get("id")]

    @property
    def primary(self):
        """The design's primary locale."""
        return self.config.get("primaryLocale") or (self.locales[0] if self.locales else None)

    @property
    def locales(self):
        """The config's locales (else the report's), in order."""
        locs = self.config.get("locales")
        if isinstance(locs, list) and locs:
            return list(locs)
        out = []
        for f in self.files:
            if f.get("locale") and f["locale"] not in out:
                out.append(f["locale"])
        return out

    def stores(self):
        """The stores the targets (and the report's files) are for, in order."""
        out = []
        for t in self.targets.values():
            if isinstance(t, dict) and t.get("store") and t["store"] not in out:
                out.append(t["store"])
        for f in self.files:
            if f.get("store") and f["store"] not in out:
                out.append(f["store"])
        return out

    def target_store(self, target_id):
        """The store a target is for."""
        t = self.targets.get(target_id) or {}
        if t.get("store"):
            return t["store"]
        for f in self.files:
            if f.get("target") == target_id and f.get("store"):
                return f["store"]
        return None

    def shot_order(self):
        """``{shot id: index}`` in the config's order."""
        return dict((s["id"], i) for i, s in enumerate(self.shots))

    def shots_for(self, target_id):
        """The shot ids a target gets, in order (a shot's ``targets`` filter; null = every target)."""
        out = []
        for s in self.shots:
            only = s.get("targets")
            if only is None or target_id in only:
                out.append(s["id"])
        return out

    def target_size(self, target_id):
        """A target's ``(width, height)`` from the config, or ``None``."""
        t = self.targets.get(target_id) or {}
        try:
            return int(t["width"]), int(t["height"])
        except (KeyError, TypeError, ValueError):
            return None

    def caption_setting(self, store, target_id, key):
        """A caption setting, most specific first: the target's ``caption``, the store's, the theme's."""
        for section in (_get(self.targets, target_id, "caption"), _get(self.config, "stores", store, "caption"),
                        _get(self.config, "theme", "caption")):
            if isinstance(section, dict) and section.get(key) is not None:
                return section[key]
        return None

    def ink_for(self, store, target_id):
        """The caption's ink colour from the config: a caption ``ink``/``color`` setting, else the palette's ink."""
        for key in ("ink", "color", "colour"):
            v = self.caption_setting(store, target_id, key)
            if v is not None:
                return v
        for section in (_get(self.targets, target_id, "palette"), _get(self.config, "stores", store, "palette"),
                        _get(self.config, "theme", "palette")):
            if isinstance(section, dict) and section.get("ink"):
                return section["ink"]
        return None

    def string(self, locale, key):
        """A string key's text in a locale, falling back to the primary locale's."""
        strings = self.config.get("strings") or {}
        for loc in (locale, self.primary):
            value = _get(strings, loc, key)
            if isinstance(value, str):
                return value
        return None

    def seam_units(self):
        """The panorama's seam margin in units (1% of a slot's width)."""
        try:
            return float(_get(self.config, "panorama", "seam") or DEFAULT_SEAM_UNITS)
        except (TypeError, ValueError):
            return DEFAULT_SEAM_UNITS

    def path(self, rel):
        """A report path made absolute (paths are relative to the output folder)."""
        return rel if os.path.isabs(rel) else os.path.join(self.out, rel)

    # -- slots ------------------------------------------------------------------------------------------

    def apple_slot(self, size):
        """The Apple display type a picture of this size goes in (the first listed that fits), or ``None``."""
        rs = self.rulesets.get("apple")
        if rs is None or size is None:
            return None
        for key, slot in rs.slots.items():
            if fits(size, slot.get("sizes") or [], slot.get("orientation")):
                return key
        return None

    def google_slot(self, target_id):
        """``(slot, how)``: the Play slot a target fills and how that was decided (``store-listing.json``, the
        target's own ``slot``, or a guess from its size and name)."""
        slots = _get(self.listing, "stores", "google", "slots") or {}
        for slot, screen in slots.items():
            if screen == target_id and slot in GOOGLE_SCREEN_SLOTS:
                return slot, "store-listing.json"
        t = self.targets.get(target_id) or {}
        if t.get("slot") in GOOGLE_SCREEN_SLOTS:
            return t["slot"], "the target's slot"
        size = self.target_size(target_id)
        name = (target_id + " " + str(t.get("capture") or "")).lower()
        words = set(re.split(r"[^a-z0-9]+", name))
        if (size and size[0] == size[1]) or words & {"wear", "watch"}:
            return "wear", "guessed"
        if words & {"tv"}:
            return "tv", "guessed"
        if "tablet" in name:
            return ("tablet7" if words & {"7", "tablet7"} else "tablet10"), "guessed"
        return "phone", "guessed"

    def slot_for(self, store, target_id):
        """The store slot a target fills: Apple's by its size, Play's by ``google_slot``."""
        if store == "apple":
            return self.apple_slot(self.target_size(target_id))
        if store == "google":
            return self.google_slot(target_id)[0]
        return None

    def slot_kind(self, store, slot):
        """The slot's kind (phone, tablet, watch…) from the rules' slot table."""
        rs = self.rulesets.get(store)
        return ((rs.slots.get(slot) or {}).get("kind")) if rs and slot else None

    def is_game(self):
        """True or False from ``store-listing.json``'s categories; ``None`` when there's no telling."""
        g = _get(self.listing, "stores", "google", "category")
        a = _get(self.listing, "stores", "apple", "categories", "primary")
        if g is None and a is None:
            return None
        return bool((isinstance(g, str) and g.upper().startswith("GAME")) or a == "GAMES")

    def relax(self):
        """``{rule id: reason}`` from ``store-listing.json``'s ``rules.relax``."""
        out = collections.OrderedDict()
        for entry in _get(self.listing, "rules", "relax") or []:
            if isinstance(entry, str):
                out[entry] = ""
            elif isinstance(entry, dict) and isinstance(entry.get("id"), str):
                out[entry["id"]] = entry.get("reason") or ""
        return out

    def frame_maker(self, frame):
        """``(drawn, maker)`` for a report's frame: from the report (``drawn``, ``maker``), else from the frame's
        JSON (a path relative to the config gives its JSON beside it; a name, the skill's ``frames/<name>.json``).
        A frame with no JSON to read is taken as drawn."""
        if not isinstance(frame, dict):
            return True, None
        drawn, maker = frame.get("drawn"), frame.get("maker")
        if drawn is None:
            meta = self._frame_json(frame.get("path") or frame.get("name"))
            drawn = meta.get("drawn")
            maker = maker or meta.get("maker")
        if drawn is None:
            drawn = not maker
        return bool(drawn), maker

    def _frame_json(self, name):
        if not isinstance(name, str) or not name:
            return {}
        if "/" in name or os.sep in name or os.path.splitext(name)[1].lower() in (".svg", ".png", ".json"):
            path = name if os.path.isabs(name) else os.path.join(self.base, name)
            path = os.path.splitext(path)[0] + ".json"
        else:
            path = os.path.join(SKILL_DIR, "frames", name + ".json")
        try:
            data = jsonio.load(path)
        except (OSError, jsonio.JsonError):
            return {}
        return data if isinstance(data, dict) else {}

    def design_entry(self, store, name, slot=None):
        """A store's design entry (the slot's override when there is one), or ``None``."""
        entry = (self.designs.get(store) or {}).get(name)
        if not isinstance(entry, dict):
            return None
        by_slot = entry.get("bySlot") or {}
        if slot and isinstance(by_slot.get(slot), dict):
            return by_slot[slot]
        return entry


# ---------------------------------------------------------------------------------------------------------
# The report

def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


class Report:
    """What the check found: findings per store, fallbacks, relaxed rules, notes, measurements and the
    checklist for a person."""

    def __init__(self, config_path, relax=None):
        self.config_path = config_path
        self.findings = []      # (store, Finding)
        self.fallbacks = []
        self.relax = relax or {}
        self.relaxed_used = collections.OrderedDict()
        self.checklist = []
        self.not_checked = []
        self.notes = []
        self.measured = collections.OrderedDict()
        self.stores = []
        self._seen = set()

    def add(self, store, finding):
        """Add a finding once; a finding whose rule the listing relaxes is set aside and listed."""
        if finding.rule_id in self.relax:
            self.relaxed_used[finding.rule_id] = self.relax[finding.rule_id]
            return
        key = (store,) + tuple(finding)
        if key in self._seen:
            return
        self._seen.add(key)
        self.findings.append((store, finding))

    def measure(self, path, key, value):
        """Record a measurement of a file (its contrast, its caption's size in search)."""
        self.measured.setdefault(path, collections.OrderedDict([("path", path)]))[key] = value

    def note(self, text):
        """Add a note once."""
        if text not in self.notes:
            self.notes.append(text)

    def skip(self, store, rule_id, why):
        """A rule that couldn't be decided here."""
        for n in self.not_checked:
            if n["store"] == store and n["id"] == rule_id:
                return
        self.not_checked.append(collections.OrderedDict([("store", store), ("id", rule_id), ("why", why)]))

    def look(self, store, item_id, item, source=None, status=None):
        """Something for a person to check by eye."""
        for c in self.checklist:
            if c["store"] == store and c["id"] == item_id:
                return
        entry = collections.OrderedDict([("store", store), ("id", item_id), ("item", item)])
        if source:
            entry["source"] = source
        if status:
            entry["status"] = status
        self.checklist.append(entry)

    @property
    def errors(self):
        """The error findings."""
        return [f for _, f in self.findings if f.severity == "error"]

    @property
    def warnings(self):
        """The warning findings."""
        return [f for _, f in self.findings if f.severity == "warning"]

    def to_json(self):
        """The report as ``--json`` prints it."""
        findings = []
        for store, f in self.findings:
            obj = collections.OrderedDict(f._asdict())
            obj["store"] = store
            findings.append(obj)
        relaxed = [collections.OrderedDict([("id", k), ("reason", v)]) for k, v in self.relaxed_used.items()]
        return collections.OrderedDict([
            ("config", self.config_path), ("stores", list(self.stores)), ("findings", findings),
            ("fallbacks", self.fallbacks), ("relaxed", relaxed), ("checklist", self.checklist),
            ("notChecked", self.not_checked), ("notes", self.notes), ("measured", list(self.measured.values())),
            ("summary", collections.OrderedDict([("errors", len(self.errors)), ("warnings", len(self.warnings))])),
        ])

    def to_text(self):
        """The report as text: findings by store and severity, fallbacks, relaxed rules, what wasn't checked,
        notes, the checklist for a person and a summary."""
        lines = []
        for store in ["design"] + [s for s in self.stores if s != "design"]:
            mine = [f for s, f in self.findings if s == store]
            if not mine and store == "design":
                continue
            n_err = len([f for f in mine if f.severity == "error"])
            lines.append("%s (%s): %s, %s" % (STORE_NAMES.get(store, store), store, _plural(n_err, "error"),
                                              _plural(len(mine) - n_err, "warning")))
            for sev, title in (("error", "Errors"), ("warning", "Warnings")):
                group = [f for f in mine if f.severity == sev]
                if group:
                    lines.append("  %s:" % title)
                    for f in group:
                        lines.append("    %s: %s [%s]" % (f.where, f.message, f.rule_id))
            lines.append("")
        if self.fallbacks:
            lines.append("Fell back to the primary locale: not errors, but check they're meant to be:")
            for fb in self.fallbacks:
                lines.append("  %s %s of %s from %s (%s)" % (fb["locale"], fb["what"], fb["shot"], fb["from"],
                                                            ", ".join(fb["targets"])))
            lines.append("")
        if self.relaxed_used:
            lines.append("Relaxed by store-listing.json (not reported):")
            for rid, reason in self.relaxed_used.items():
                lines.append("  %s: %s" % (rid, reason or "(no reason given)"))
            lines.append("")
        if self.not_checked:
            lines.append("Not checked:")
            for n in self.not_checked:
                lines.append("  %s: %s" % (n["id"], n["why"]))
            lines.append("")
        for note in self.notes:
            lines.append("Note: %s" % note)
        if self.notes:
            lines.append("")
        if self.checklist:
            lines.append("For a person to check, looking at every picture at full size and the sheets (%d):"
                         % len(self.checklist))
            for c in self.checklist:
                lines.append("  [ ] %s [%s]" % (c["item"], c["id"]))
            lines.append("")
        lines.append("Result: %s, %s." % (_plural(len(self.errors), "error"), _plural(len(self.warnings), "warning")))
        return "\n".join(lines) + "\n"


def own_finding(rule_id, severity, where, message):
    """A finding from the design's own checks (not a store's rule)."""
    return rules.Finding(rule_id, severity, where, message, None, "verified")


def design_finding(store, name, entry, where, message):
    """A finding from a store's ``design`` entry: its severity unless it isn't verified (then a warning, saying
    so), its source and status."""
    status = entry.get("status") or "unverified"
    severity = entry.get("severity") or "warning"
    if status != "verified":
        severity = "warning"
        message = "%s (unverified design rule: %s%s)" % (message, status,
                                                         ", checked " + entry["checked"] if entry.get("checked") else "")
    return rules.Finding(rules.design_rule_id(store, name), severity, where, message, entry.get("source"), status)


# ---------------------------------------------------------------------------------------------------------
# The check

def _texts(inputs, f):
    """``[(role, text)]``: the words drawn on a file: its caption, and its ``texts`` from the report (else the
    shot's kicker and proof strings from the config)."""
    out = []
    cap = f.get("caption")
    if isinstance(cap, dict) and cap.get("text"):
        out.append(("caption", cap["text"]))
    if isinstance(cap, dict):
        inner = [(role, cap[role]) for role in ("kicker", "proof") if isinstance(cap.get(role), dict)]
        if inner:
            for role, item in inner:
                if item.get("text"):
                    out.append((role, item["text"]))
            return out
    extra = f.get("texts")
    if isinstance(extra, list):
        for t in extra:
            if isinstance(t, dict) and t.get("text"):
                out.append((t.get("role") or "text", t["text"]))
        return out
    shot = next((s for s in inputs.shots if s["id"] == f.get("shot")), None) or {}
    for role in ("kicker", "proof"):
        key = shot.get(role)
        if isinstance(key, str):
            value = inputs.string(f.get("locale"), key)
            if value:
                out.append((role, value))
    return out


def _has_caption(f):
    cap = f.get("caption")
    return isinstance(cap, dict) and bool(cap.get("text"))


def _has_frame(f):
    fr = f.get("frame")
    return isinstance(fr, dict) and fr.get("name") not in (None, "", "none")


def _word_count(text):
    return len([w for w in re.split(r"\s+", text.strip()) if re.search(r"\w", w)])


def _no_space_script(text):
    return any(0x3040 <= ord(c) <= 0x30FF or 0x3400 <= ord(c) <= 0x9FFF or 0xAC00 <= ord(c) <= 0xD7AF
               or 0x0E00 <= ord(c) <= 0x0E7F for c in text)


class Check:
    """One run of the check over a rendered set."""

    def __init__(self, inputs, report, baseline=None):
        self.inputs = inputs
        self.report = report
        self.baseline = baseline
        self.pixels = {}
        self.not_on_disk = collections.OrderedDict()
        self.search_small = collections.OrderedDict()

    def where(self, f):
        """A file's place in the report: its path."""
        return f.get("path") or "%s/%s/%s" % (f.get("locale"), f.get("target"), f.get("shot"))

    def run(self):
        """Every check, in order."""
        inputs = self.inputs
        self.report.stores = [s for s in inputs.stores()]
        for store in self.report.stores:
            if store not in STORES:
                self.report.note("%s has no rules data here yet: only the design's own checks ran on its files"
                                 % STORE_NAMES.get(store, store))
        if inputs.listing_path:
            self.report.note("read %s for Play slots, the category and relaxed rules"
                             % os.path.relpath(inputs.listing_path))
        self.check_targets()
        self.check_rendered()
        for f in inputs.files:
            self.check_file(f)
        for (store, loc, tid), e in self.search_small.items():
            if e["shown"]:
                sizes = ", ".join("%.1f pt (%s)" % (pt, shot) for shot, _u, pt in e["shots"])
                where_said = "in Apple's search row (each shot about %d pt wide) would be about %s" % (
                    round(e["shown"]), sizes)
                need = max(e["need"], 100.0 * MIN_TEXT_PT / e["shown"])
            else:
                where_said = "are %s" % ", ".join("%.1fu (%s)" % (u, shot) for shot, u, _pt in e["shots"])
                need = e["need"]
            self.report.add(store, own_finding(
                "design.caption.search_size", "warning", "%s/%s" % (loc, tid),
                "captions on the first shots %s: under %.1fu (%.1f%% of the width), the size that reads at search "
                "size%s; about %d px reaches it. A derived estimate: look at the %s sheet"
                % (where_said, need, need, " (iOS's 11 pt minimum)" if e["shown"] else "",
                   math.ceil(need * e["width"] / 100.0), "search-row" if e["shown"] else "listing's")))
        for (store, loc, tid), shots in self.not_on_disk.items():
            self.report.add(store, own_finding(
                "design.missing", "error", "%s/%s" % (loc, tid),
                "in the render report but not on disk: %s (render again; size, format and contrast weren't "
                "checked)" % ", ".join(str(x) for x in shots)))
        self.check_words()
        self.check_counts()
        self.check_sets()
        self.check_consistency()
        self.check_style()
        if self.baseline is not None:
            self.check_baseline()
        self.check_fallbacks()
        self.checklist()

    # -- targets and files ----------------------------------------------------------------------------

    def check_targets(self):
        """Each target's slot: an Apple size that fits a display type, a Play slot (noted when guessed), and
        targets that share an Apple display type."""
        by_slot = collections.defaultdict(list)
        for tid in self.inputs.targets:
            store = self.inputs.target_store(tid)
            size = self.inputs.target_size(tid)
            if store == "apple" and size:
                slot = self.inputs.apple_slot(size)
                if slot:
                    by_slot[slot].append(tid)
            elif store == "google":
                slot, how = self.inputs.google_slot(tid)
                if how == "guessed":
                    self.report.note("target %s is taken as Play's %s slot (a guess from its size and name: set "
                                     "stores.google.slots in store-listing.json to say)" % (tid, slot))
        for slot, tids in by_slot.items():
            if len(tids) > 1:
                self.report.note("targets %s all fit Apple's %s: store-listings puts their pictures in one "
                                 "display type, so they count together" % (", ".join(tids), slot))

    def check_rendered(self):
        """Every locale x target x shot the config asks for is in the report."""
        have = set((f.get("locale"), f.get("target"), f.get("shot")) for f in self.inputs.files)
        missing = collections.defaultdict(list)
        for loc in self.inputs.locales:
            for tid in self.inputs.targets:
                for shot in self.inputs.shots_for(tid):
                    if (loc, tid, shot) not in have:
                        missing[(loc, tid)].append(shot)
        for (loc, tid), shots in missing.items():
            store = self.inputs.target_store(tid) or "design"
            self.report.add(store, own_finding(
                "design.missing", "error", "%s/%s" % (loc, tid),
                "not rendered: %s (run render.py)" % ", ".join(shots)))

    def check_file(self, f):
        """The checks on one file: it exists and matches the report, its size and format, its words' fit,
        glyphs and contrast, its frame and layout against the store's design table, seams, upscaling."""
        inputs = self.inputs
        store = f.get("store") or inputs.target_store(f.get("target")) or "design"
        where = self.where(f)
        path = inputs.path(f.get("path") or "")
        slot = inputs.slot_for(store, f.get("target")) if store in STORES else None
        f["_slot"] = slot
        meta = None
        if not f.get("path") or not os.path.isfile(path):
            self.not_on_disk.setdefault((store, f.get("locale"), f.get("target")), []).append(f.get("shot"))
        else:
            try:
                meta = png.info(path)
            except (png.ImageError, OSError) as e:
                self.report.add(store, own_finding("design.missing", "error", where, "can't be read: %s" % e))
        if meta is not None:
            digest = f.get("sha256")
            if isinstance(digest, str) and re.match(r"^[0-9a-f]{64}$", digest) and digest != png.sha256(path):
                self.report.add(store, own_finding("design.report.stale", "warning", where,
                                                   "changed since render.py wrote the report (render again)"))
            size = (meta.width, meta.height)
            want = inputs.target_size(f.get("target"))
            if want is None and f.get("width") and f.get("height"):
                want = (int(f["width"]), int(f["height"]))
            if want and size != want:
                self.report.add(store, own_finding(
                    "design.size", "error", where, "is %s; target %s is %s" % (_size_text(size), f.get("target"),
                                                                              _size_text(want))))
            if store in STORES:
                self.check_store_files(store, slot, f, meta, path, where)
            self.check_contrast(store, f, path, meta, where)
        for err in f.get("errors") or []:
            self.report.add(store, own_finding("design.render.errors", "error", where, "the page said: %s" % err))
        self.check_caption(store, slot, f, where)
        self.check_design(store, slot, f, where)
        self.check_seams(store, f, where)
        scale = f.get("captureScale")
        if isinstance(scale, (int, float)) and scale > UPSCALE_TOLERANCE:
            self.report.add(store, own_finding(
                "design.capture.upscaled", "warning", where,
                "shows its capture at %.2fx its pixels: it'll look soft; capture at a larger size" % scale))

    def check_store_files(self, store, slot, f, meta, path, where):
        """The store's ``size`` and ``format`` rules for the file's slot."""
        rs = self.inputs.rulesets[store]
        size = (meta.width, meta.height)
        if store == "apple" and slot is None:
            rule = rs.get("apple.screenshots.size")
            if rule is not None:
                self.report.add(store, rules.finding(
                    rule, where, "%s isn't an App Store screenshot size (no display type takes it)"
                    % _size_text(size)))
        for rule in rs.by_kind("size"):
            if slot is None or slot not in rule.slots or (rule.get("applies") or {}).get("media") == "preview":
                continue
            if rule.get("fromSlots"):
                s = rs.slots.get(slot) or {}
                ok = fits(size, s.get("sizes") or [], s.get("orientation"))
                want = " or ".join(_size_text(x) for x in s.get("sizes") or [])
            elif rule.get("sizes"):
                ok = fits(size, rule.get("sizes"), rule.get("orientation"))
                want = " or ".join(_size_text(x) for x in rule.get("sizes"))
            elif rule.get("range"):
                ok = in_range(size, rule.get("range"))
                want = describe_range(rule.get("range"))
            else:
                continue
            if not ok:
                self.report.add(store, rules.finding(rule, where, "is %s; %s takes %s" % (
                    _size_text(size), slot, want)))
        for rule in rs.by_kind("format"):
            applies = rule.get("applies") or {}
            if applies.get("media") == "preview":
                continue
            if slot is not None and slot not in rule.slots:
                continue
            if slot is None and not any((rs.slots.get(s) or {}).get("group", "screenshots") == "screenshots"
                                        for s in rule.slots):
                continue
            formats = rule.get("formats")
            if formats and meta.format not in formats:
                self.report.add(store, rules.finding(rule, where, "is a %s; %s takes %s" % (
                    meta.format.upper(), slot or "a screenshot", " or ".join(x.upper() for x in formats))))
            if rule.get("alpha") is False and meta.has_alpha:
                self.report.add(store, rules.finding(
                    rule, where, "has an alpha channel; screenshots must be opaque (render with an opaque "
                    "background, RGB)"))
            elif rule.get("transparency") is False and png.has_transparency(path):
                self.report.add(store, rules.finding(rule, where, "has see-through pixels"))
            if rule.get("maxBytes") and os.path.getsize(path) > rule.get("maxBytes"):
                self.report.add(store, rules.finding(rule, where, "is %d bytes; the limit is %d" % (
                    os.path.getsize(path), rule.get("maxBytes"))))

    def check_caption(self, store, slot, f, where):
        """Fit, floor, lines, words and glyphs of the caption (and glyphs of the other texts)."""
        cap = f.get("caption")
        texts = f.get("texts") if isinstance(f.get("texts"), list) else []
        for t in texts:
            if isinstance(t, dict) and t.get("missingGlyphs"):
                self.report.add(store, own_finding("design.glyphs", "error", "%s %s" % (where, t.get("role") or "text"),
                                                   self._glyph_message(t["missingGlyphs"])))
        if not _has_caption(f):
            return
        text = cap["text"]
        if cap.get("fits") is False:
            if cap.get("hyphenationAvailable") is False:
                lang = (f.get("lang") or f.get("locale") or "").split("-")[0]
                fix = ("; this Chrome can't hyphenate %s: add soft hyphens (\"\\u00ad\" in the JSON, or \"&shy;\") "
                       "at the break points, or shorten it" % lang)
            else:
                fix = ": shorten it"
            self.report.add(store, own_finding(
                "design.caption.fit", "error", where,
                "caption \"%s\" doesn't fit even at the font floor (%s px)%s" % (
                    text, _num(cap.get("floorPx")), fix)))
        elif cap.get("atFloor"):
            self.report.add(store, own_finding(
                "design.caption.floor", "warning", where,
                "caption \"%s\" shrank to the font floor (%s px) to fit: shorten it" % (text, _num(cap.get("floorPx")))))
        lines = cap.get("lines")
        if isinstance(lines, int) and lines > MAX_CAPTION_LINES:
            allowed = cap.get("maxLines") or self.inputs.caption_setting(store, f.get("target"), "maxLines")
            severity = "warning" if isinstance(allowed, int) and allowed >= lines else "error"
            self.report.add(store, own_finding(
                "design.caption.lines", severity, where,
                "caption runs to %d lines; two at most read at a glance" % lines))
        if not _no_space_script(text):
            n = _word_count(text)
            if n > MAX_CAPTION_WORDS:
                self.report.add(store, own_finding(
                    "design.caption.words", "warning", where,
                    "caption has %d words; two to five read at search size" % n))
        if cap.get("missingGlyphs"):
            self.report.add(store, own_finding("design.glyphs", "error", "%s caption" % where,
                                               self._glyph_message(cap["missingGlyphs"])))
        w, h = f.get("width"), f.get("height")
        size = self.inputs.target_size(f.get("target")) or ((w, h) if w and h else None)
        if size and cap.get("fontPx"):
            u = 100.0 * float(cap["fontPx"]) / size[0]
            self.report.measure(f.get("path"), "captionU", round(u, 2))
            apple_phone = store == "apple" and self.inputs.slot_kind("apple", slot) == "phone"
            pt = None
            if apple_phone:
                pt = points_at(cap.get("fontPx"), size[0], search_shot_points(size[0], size[1]))
                self.report.measure(f.get("path"), "searchPt", round(pt, 1))
            order = self.inputs.shots_for(f.get("target"))
            first = f.get("shot") in order[:(1 if apple_phone and size[0] > size[1] else SEARCH_SHOTS)]
            need = FIRST_SHOTS_MIN_U.get(aspect_class(size[0], size[1]))
            if first and need is not None and (u < need - 1e-6 or (pt is not None and pt < MIN_TEXT_PT)):
                key = (store, f.get("locale"), f.get("target"))
                entry = self.search_small.setdefault(key, {"shots": [], "need": need, "width": size[0],
                                                           "shown": search_shot_points(size[0], size[1])
                                                           if apple_phone else None})
                entry["shots"].append((f.get("shot"), u, pt))

    @staticmethod
    def _glyph_message(missing):
        chars = missing if isinstance(missing, list) else [missing]
        shown = " ".join("%s (U+%04X)" % (c, ord(c[0])) if isinstance(c, str) and c else str(c) for c in chars[:12])
        return "the font has no glyph for %s: they'd show in a fallback font or as boxes (add a font that covers " \
               "them)" % shown

    def _decode(self, path):
        if path not in self.pixels:
            self.pixels.clear()
            self.pixels[path] = png.decode_rgb(path)
        return self.pixels[path]

    def check_contrast(self, store, f, path, meta, where):
        """WCAG contrast of the caption's ink against the median pixel behind its box (at least 4.5:1)."""
        if not _has_caption(f):
            return
        cap = f["caption"]
        box = _box(cap.get("box"))
        if box is None:
            self.report.skip(store, "design.contrast", "the render report gives no caption box")
            return
        ink_value = cap.get("ink") or cap.get("color")
        ink = parse_colour(ink_value) if ink_value is not None else None
        if ink is None:
            ink = parse_colour(self.inputs.ink_for(store, f.get("target")))
        if ink is None:
            self.report.skip(store, "design.contrast", "no caption ink colour in the report or the theme's palette")
            return
        if meta.format != "png":
            self.report.skip(store, "design.contrast", "contrast is measured on PNGs only")
            return
        try:
            w, h, pixels = self._decode(path)
        except png.ImageError as e:
            self.report.skip(store, "design.contrast", "couldn't decode %s: %s" % (where, e))
            return
        lum = median_luminance(pixels, w, h, box)
        if lum is None:
            self.report.add(store, own_finding("design.contrast", "warning", where,
                                               "the caption's box is outside the picture"))
            return
        ratio = contrast_ratio(luminance(ink), lum)
        self.report.measure(f.get("path"), "contrast", round(ratio, 2))
        if ratio < MIN_CONTRAST:
            self.report.add(store, own_finding(
                "design.contrast", "error", where,
                "caption contrast is %.1f:1 against what's behind it (at least 4.5:1): give it a plate, a darker or "
                "lighter background, or another ink" % ratio))

    def check_design(self, store, slot, f, where):
        """The store's design table on one file: text share, frames, the user's device art, captions and
        backgrounds per slot."""
        inputs = self.inputs
        if store not in STORES:
            return
        entry = inputs.design_entry(store, "maxTextShare", slot)
        cap = f.get("caption") if isinstance(f.get("caption"), dict) else {}
        share = cap.get("textShare", f.get("textShare"))
        if entry and isinstance(share, (int, float)) and share > float(entry["value"]) + 1e-9:
            self.report.add(store, design_finding(
                store, "maxTextShare", entry, where,
                "words cover %d%% of the picture; at most %d%%" % (round(share * 100), round(entry["value"] * 100))))
        frames = [x for x in (f.get("frames") or [f.get("frame")]) if isinstance(x, dict)
                  and x.get("name") not in (None, "", "none")]
        for frame in frames:
            self.check_device_art(store, slot, f, frame, where)
        if _has_frame(f):
            frame = f["frame"]
            entry = inputs.design_entry(store, "frames", slot)
            value = entry.get("value") if entry else None
            if value in ("forbidden", "discouraged"):
                label = "%s %s" % (STORE_NAMES[store], slot) if slot else STORE_NAMES[store]
                msg = ("has a device frame (%s); %s screenshots %s" % (
                    frame.get("name"), label, "may have none" if value == "forbidden" else
                    "are best without (set stores.%s.frame to \"none\")" % store))
                self.report.add(store, design_finding(store, "frames", entry, where, msg))
        if _has_caption(f) or any(r != "caption" for r, _ in _texts(inputs, f)):
            entry = inputs.design_entry(store, "captions", slot)
            value = entry.get("value") if entry else None
            if value in ("forbidden", "discouraged"):
                msg = "has words over it; %s %s screenshots %s" % (
                    STORE_NAMES[store], slot, "may have none" if value == "forbidden" else
                    "are best without (they can get cut off)")
                self.report.add(store, design_finding(store, "captions", entry, where, msg))
        if f.get("layout") in BACKGROUND_LAYOUTS:
            entry = inputs.design_entry(store, "backgrounds", slot)
            value = entry.get("value") if entry else None
            if value in ("forbidden", "discouraged"):
                self.report.add(store, design_finding(
                    store, "backgrounds", entry, where,
                    "the %s layout adds a background around the app; %s %s screenshots %s (use fullbleed or "
                    "gameplay)" % (f.get("layout"), STORE_NAMES[store], slot,
                                   "may have none" if value == "forbidden" else "are best without")))

    def check_device_art(self, store, slot, f, frame, where):
        """A maker's device art (a frame the user supplied, its JSON saying ``"drawn": false`` and its ``maker``)
        used as the design table allows: on Apple, Apple's only as it is (no tilt, 3D, crop or callout over it);
        on Play, none."""
        drawn, maker = self.inputs.frame_maker(frame)
        if drawn:
            return
        entry = self.inputs.design_entry(store, "deviceArt", slot)
        if not entry:
            return
        value = entry.get("value")
        label = "%s's device art" % maker if maker else "a maker's device art"
        if value == "none":
            self.report.add(store, design_finding(store, "deviceArt", entry, where, "uses %s (%s); %s advises against "
                                                  "any (use a drawn frame or none)" % (label, frame.get("name"),
                                                                                      STORE_NAMES[store])))
            return
        if value != "ownAsIs" or (maker or "").lower() != "apple":
            return
        problems = []
        if f.get("layout") == "tilt" or frame.get("tilted") or frame.get("tilt") not in (None, 0, False, "none"):
            problems.append("tilted")
        if frame.get("threeD") or frame.get("3d") or frame.get("rotate3d"):
            problems.append("turned in 3D")
        box = _box(frame.get("box"))
        w, h = f.get("width"), f.get("height")
        if f.get("layout") in ("framed-bleed", "callout") or frame.get("cropped") or (
                box and w and h and (box[0] < -0.5 or box[1] < -0.5 or box[0] + box[2] > w + 0.5
                                     or box[1] + box[3] > h + 0.5)):
            problems.append("cropped by the edge")
        callout = _box(_get(f, "callout", "box"))
        if (f.get("layout") == "callout" and isinstance(f.get("callout"), dict) and box is None) or (
                callout and box and _overlaps(callout, box)):
            problems.append("with a callout over it")
        if problems:
            self.report.add(store, design_finding(
                store, "deviceArt", entry, where,
                "uses Apple's own bezel (%s) %s; Apple's bezels may be used only as they are (a drawn frame may be "
                "tilted and cropped)" % (frame.get("name"), ", ".join(problems))))

    def check_seams(self, store, f, where):
        """Nothing load-bearing within the panorama's seam margin: a caption is an error, a frame or callout a
        warning."""
        seams = f.get("seams")
        if not isinstance(seams, list) or not seams:
            return
        width = f.get("width") or (self.inputs.target_size(f.get("target")) or (0, 0))[0]
        if not width:
            return
        units_margin = self.inputs.seam_units() * width / 100.0
        severity_of = {"caption": "error", "kicker": "error", "proof": "error"}
        for seam in seams:
            x = seam.get("x") if isinstance(seam, dict) else seam
            if isinstance(seam, dict) and x is None:
                x = {"left": 0, "right": width}.get(seam.get("edge"))
            try:
                x = float(x)
            except (TypeError, ValueError):
                continue
            margin = units_margin
            if isinstance(seam, dict) and isinstance(seam.get("marginPx"), (int, float)):
                margin = float(seam["marginPx"])
            if isinstance(seam, dict) and isinstance(seam.get("intruders"), list):
                names = [str(n) for n in seam["intruders"]]
            else:
                band = [x - margin, -1e9, 2 * margin, 2e9]
                names = [name for name, box in (
                    ("caption", _box(_get(f, "caption", "box")) if _has_caption(f) else None),
                    ("frame", _box(_get(f, "frame", "box")) if _has_frame(f) else None),
                    ("callout", _box(_get(f, "callout", "box")))) if box and _overlaps(box, band)]
            for name in names:
                self.report.add(store, own_finding(
                    "design.seams", severity_of.get(name, "warning"), where,
                    "the %s comes within %d px of the seam at x=%d (keep %d px clear: words split across two "
                    "shots don't read)" % (name, round(margin), round(x), round(margin))))

    # -- words ----------------------------------------------------------------------------------------

    def check_words(self):
        """The rules' ``words`` and ``pattern`` rules for ``captions``, on every caption and text drawn, once per
        locale, shot and wording (naming the targets it's on)."""
        groups = collections.OrderedDict()
        for f in self.inputs.files:
            store = f.get("store") or self.inputs.target_store(f.get("target"))
            if store not in self.inputs.rulesets:
                continue
            for role, text in _texts(self.inputs, f):
                key = (store, f.get("locale"), f.get("shot"), role, text)
                groups.setdefault(key, []).append(f.get("target"))
        extra = _get(self.inputs.listing, "rules", "extraForbiddenWords") or []
        for (store, loc, shot, role, text), targets in groups.items():
            rs = self.inputs.rulesets[store]
            where = "%s %s %s (%s)" % (loc, shot, role, ", ".join(sorted(set(t for t in targets if t))))
            for rule in rs.for_field("captions"):
                if rule.kind in ("words", "pattern"):
                    for finding in rules.evaluate(rule, text, where):
                        self.report.add(store, finding._replace(message="\"%s\" %s" % (text, finding.message)))
            if extra:
                found = textlib.find_words(text, extra)
                if found:
                    self.report.add(store, own_finding(
                        "design.words.extra", "error", where, "\"%s\" contains %s (rules.extraForbiddenWords)" % (
                            text, ", ".join('"%s"' % w for w in found))))

    # -- counts and required slots ------------------------------------------------------------------

    def _pictures(self, store):
        """``{locale: {slot: [file]}}`` for a store's files."""
        out = collections.OrderedDict()
        for loc in self.inputs.locales:
            out[loc] = collections.OrderedDict()
        for f in self.inputs.files:
            fstore = f.get("store") or self.inputs.target_store(f.get("target"))
            if fstore != store:
                continue
            slot = f.get("_slot") or self.inputs.slot_for(store, f.get("target"))
            if slot is None:
                continue
            out.setdefault(f.get("locale"), collections.OrderedDict()).setdefault(slot, []).append(f)
        return out

    def _when(self, store, rule, used, platforms, kinds):
        """A rule's ``when`` on this set: True, False, or None (can't tell here)."""
        cond = rule.get("when") or {}
        for key, value in cond.items():
            if key == "slotUsed":
                if value not in used:
                    return False
            elif key == "slotMissing":
                if value in used:
                    return False
            elif key == "platform":
                wanted = value if isinstance(value, list) else [value]
                if not set(wanted) & platforms:
                    return False
            elif key == "screenKind":
                if value not in kinds:
                    return False
            elif key == "game":
                game = self.inputs.is_game()
                if game is None:
                    return None
                if bool(value) != game:
                    return False
            else:
                return None
        return True

    def check_counts(self):
        """The rules' ``count`` and ``required`` rules on the store's screenshot slots, per locale."""
        for store in self.report.stores:
            if store not in self.inputs.rulesets:
                continue
            rs = self.inputs.rulesets[store]
            pictures = self._pictures(store)
            used = set()
            for by_slot in pictures.values():
                used |= set(by_slot)
            platforms = set((rs.slots.get(s) or {}).get("platform") for s in used) - {None}
            kinds = set((rs.slots.get(s) or {}).get("kind") for s in used) - {None}
            for rule in rs:
                if rule.kind not in ("count", "required") or not rule.slots:
                    continue
                if (rule.get("applies") or {}).get("media") == "preview":
                    continue
                slots = [s for s in rule.slots if (rs.slots.get(s) or {}).get("group", "screenshots") == "screenshots"]
                if not slots:
                    continue
                cond = self._when(store, rule, used, platforms, kinds)
                if cond is False:
                    continue
                if cond is None:
                    self.report.skip(store, rule.id, "depends on what store-listing.json says (%s)" % ", ".join(
                        sorted((rule.get("when") or {}).keys())))
                    continue
                for loc, by_slot in pictures.items():
                    if rule.kind == "required":
                        if store == "apple":
                            plat = set((rs.slots.get(s) or {}).get("platform") for s in slots)
                            if not plat & platforms:
                                continue
                        if not any(by_slot.get(s) for s in slots):
                            self.report.add(store, rules.finding(rule, "%s %s" % (loc, "/".join(slots)), (
                                "has no screenshots: add a target of %s" % " or ".join(
                                    "%s (%s)" % (s, " or ".join(_size_text(x) for x in (rs.slots.get(s) or {}).get(
                                        "sizes") or [])) for s in slots))))
                        continue
                    if rule.get("across"):
                        n = sum(len(by_slot.get(s) or []) for s in slots)
                        filled = ", ".join(s for s in slots if by_slot.get(s)) or "none"
                        for finding in rules.check_count(rule, n, "%s (%s)" % (loc, filled), "screenshots"):
                            self.report.add(store, finding)
                        continue
                    for s in slots:
                        if s not in used:
                            continue
                        items = by_slot.get(s) or []
                        noun = "screenshots"
                        if rule.get("of"):
                            items = [f for f in items if in_range((f.get("width") or 0, f.get("height") or 0),
                                                                  rule.get("of"))]
                            noun = "screenshots that qualify (%s)" % describe_range(rule.get("of"))
                        for finding in rules.check_count(rule, len(items), "%s %s" % (loc, s), noun):
                            self.report.add(store, finding)

    # -- sets -----------------------------------------------------------------------------------------

    def _sets(self, store):
        """``{(locale, target): [file in shot order]}`` for a store."""
        order = self.inputs.shot_order()
        out = collections.OrderedDict()
        for f in self.inputs.files:
            fstore = f.get("store") or self.inputs.target_store(f.get("target"))
            if fstore == store:
                out.setdefault((f.get("locale"), f.get("target")), []).append(f)
        for key in out:
            out[key].sort(key=lambda f: order.get(f.get("shot"), 1 << 20))
        return out

    def check_sets(self):
        """Per set (a locale's shots for a target): Apple's in-use majority, Play's UI first, Play TV's one
        unaltered shot."""
        for store in self.report.stores:
            if store not in STORES:
                continue
            tv_sets = collections.defaultdict(list)
            for (loc, tid), files in self._sets(store).items():
                slot = self.inputs.slot_for(store, tid)
                where = "%s/%s" % (loc, tid)
                entry = self.inputs.design_entry(store, "inUseMajority", slot)
                if entry and files:
                    in_use = [f for f in files if (f.get("inUse") if isinstance(f.get("inUse"), bool)
                                                   else f.get("layout") not in MARKETING_LAYOUTS)]
                    if len(in_use) <= float(entry["value"]) * len(files):
                        art = [f.get("shot") for f in files if f not in in_use]
                        self.report.add(store, design_finding(
                            store, "inUseMajority", entry, where,
                            "only %d of %d shots show the app in use (%s %s marketing art); more than half must" % (
                                len(in_use), len(files), ", ".join(art), "is" if len(art) == 1 else "are")))
                entry = self.inputs.design_entry(store, "uiFirst", slot)
                if entry:
                    first = files[:int(entry["value"])]
                    art = [f.get("shot") for f in first if f.get("layout") in MARKETING_LAYOUTS
                           or f.get("inUse") is False]
                    if art:
                        self.report.add(store, design_finding(
                            store, "uiFirst", entry, where,
                            "%s among the first %d is marketing art; %s puts the app's UI first" % (
                                ", ".join(art), int(entry["value"]), STORE_NAMES[store])))
                entry = self.inputs.design_entry(store, "captions", slot)
                if entry and entry.get("value") == "oneUnaltered":
                    tv_sets[(loc, slot)].extend(files)
            for (loc, slot), files in tv_sets.items():
                entry = self.inputs.design_entry(store, "captions", slot)
                plain = [f for f in files if not _has_caption(f) and not _has_frame(f)
                         and f.get("layout") not in BACKGROUND_LAYOUTS]
                if files and not plain:
                    self.report.add(store, design_finding(
                        store, "captions", entry, "%s %s" % (loc, slot),
                        "every %s screenshot has words or art over it; leave at least one unaltered (a gameplay "
                        "or fullbleed shot with no caption)" % slot))

    # -- the set's consistency, the style and the baseline ------------------------------------------

    def check_consistency(self):
        """Inside each set (a locale's shots for a target), shots of one layout keep one device box (x, y, width
        within 0.2u) and one caption top (0.5u). The hero may break the grid; nothing else should."""
        groups = collections.OrderedDict()
        for f in self.inputs.files:
            if f.get("layout") == "hero" or f.get("role") == "hero" or not f.get("width"):
                continue
            groups.setdefault((f.get("store") or "design", f.get("locale"), f.get("target"), f.get("layout")),
                              []).append(f)
        order = self.inputs.shot_order()
        for (store, loc, tid, layout), files in groups.items():
            if len(files) < 2:
                continue
            files.sort(key=lambda f: order.get(f.get("shot"), 1 << 20))
            u = files[0]["width"] / 100.0
            if layout in DEVICE_LAYOUTS:
                ref = _box(_get(files[0], "frame", "box"))
                odd = []
                for f in files[1:]:
                    b = _box(_get(f, "frame", "box"))
                    if ref and b and max(abs(b[i] - ref[i]) for i in (0, 1, 2)) / u > SET_DEVICE_TOLERANCE_U:
                        odd.append("%s (%.1fu)" % (f.get("shot"), max(abs(b[i] - ref[i]) for i in (0, 1, 2)) / u))
                if odd:
                    self.report.add(store, own_finding(
                        "design.set.device", "warning", "%s/%s %s" % (loc, tid, layout),
                        "the device moves between shots of one layout: %s from %s's (keep it within %.1fu: "
                        "well-made sets lock it)" % (", ".join(odd), files[0].get("shot"), SET_DEVICE_TOLERANCE_U)))
            tops = [(f, _box(_get(f, "caption", "box"))) for f in files if _has_caption(f)]
            tops = [(f, b) for f, b in tops if b]
            if len(tops) > 1:
                ref = tops[0][1][1]
                odd = ["%s (%.1fu)" % (f.get("shot"), abs(b[1] - ref) / u) for f, b in tops[1:]
                       if abs(b[1] - ref) / u > SET_CAPTION_TOLERANCE_U]
                if odd:
                    self.report.add(store, own_finding(
                        "design.set.caption", "warning", "%s/%s %s" % (loc, tid, layout),
                        "the caption's top moves between shots: %s from %s's (keep it within %.1fu)"
                        % (", ".join(odd), tops[0][0].get("shot"), SET_CAPTION_TOLERANCE_U)))

    def check_style(self):
        """A style's rules: its copy (words, lines, case) as warnings; its roles' maxPerSet; with a locked style,
        a config theme key that contradicts it (an error) and a shot's own layout outside its roles."""
        style = self.inputs.style
        if not style:
            return
        rel = os.path.relpath(self.inputs.style_path, self.inputs.base)
        if style.get("locked"):
            for path, mine, theirs in styles.theme_conflicts(self.inputs.raw_config.get("theme"), style.get("theme")):
                self.report.add("design", own_finding(
                    "design.style.theme_override", "error", path,
                    "the config sets %s to %s but the locked style (%s) says %s: the style wins, so remove it from "
                    "the config (changing the look is a new approval with the user)" % (
                        path, jsonio.canonical(mine), rel, jsonio.canonical(theirs))))
            allowed = styles.role_layouts(style)
            for shot in self.inputs.raw_config.get("shots") or []:
                layout = shot.get("layout") if isinstance(shot, dict) else None
                if layout and layout not in allowed:
                    self.report.add("design", own_finding(
                        "design.style.layout_outside_roles", "warning", "shot %s" % shot.get("id"),
                        "uses the %s layout, which none of the locked style's roles use (%s): give it a role, or "
                        "agree a new look with the user" % (layout, ", ".join(allowed) or "none")))
        roles = style.get("roles") or {}
        for tid in self.inputs.targets:
            counts = collections.Counter(s.get("role") for s in self.inputs.shots
                                         if s.get("role") and (s.get("targets") is None or tid in s["targets"]))
            for role, n in counts.items():
                most = (roles.get(role) or {}).get("maxPerSet")
                if isinstance(most, int) and n > most:
                    self.report.add("design", own_finding(
                        "design.style.role_count", "warning", tid,
                        "%d shots have the %s role; the style allows %d a set" % (n, role, most)))
        rules_ = style.get("copy") or {}
        if not rules_:
            return
        seen = set()
        for f in self.inputs.files:
            if not _has_caption(f):
                continue
            cap = f["caption"]
            text = cap["text"]
            where = self.where(f)
            limit = rules_.get("maxLines")
            if isinstance(limit, int) and isinstance(cap.get("lines"), int) and cap["lines"] > limit:
                self.report.add("design", own_finding(
                    "design.style.copy.lines", "warning", where,
                    "caption runs to %d lines; the style's copy rules say %d at most" % (cap["lines"], limit)))
            key = (f.get("locale"), f.get("shot"), text)
            if key in seen:
                continue
            seen.add(key)
            where = "%s %s" % (f.get("locale"), f.get("shot"))
            limit = rules_.get("maxWords")
            if isinstance(limit, int) and not _no_space_script(text) and _word_count(text) > limit:
                self.report.add("design", own_finding(
                    "design.style.copy.words", "warning", where,
                    "\"%s\" has %d words; the style's copy rules say %d at most" % (text, _word_count(text), limit)))
            want = rules_.get("case")
            if want and want != "any" and not _no_space_script(text):
                drawn = cap.get("case")
                if not case_ok(text, want, drawn):
                    self.report.add("design", own_finding(
                        "design.style.copy.case", "warning", where,
                        "\"%s\" isn't in %s case, as the style's copy rules ask" % (text, want)))

    def check_baseline(self):
        """The locked style unchanged since the approved baseline (an error), and each file's drift from its
        baseline counterpart past the style's tolerances (warnings)."""
        b = self.baseline
        inputs = self.inputs
        self.report.note("compared with the baseline approved %s (%s)%s" % (
            b.meta.get("approvedAt") or "?", os.path.relpath(b.folder),
            ": %s" % b.meta["note"] if b.meta.get("note") else ""))
        style = inputs.style
        if b.meta.get("styleSha256"):
            if style is None:
                self.report.add("design", own_finding(
                    "design.baseline.style_changed", "error", "style",
                    "the baseline locked a style (%s) but the config names none: put it back, or approve a new "
                    "baseline with the user" % b.meta.get("style")))
            elif style.get("locked") and styles.style_sha256(style) != b.meta["styleSha256"]:
                self.report.add("design", own_finding(
                    "design.baseline.style_changed", "error", os.path.relpath(inputs.style_path, inputs.base),
                    "the locked style changed since the baseline was approved: approve a new baseline with the "
                    "user, or put it back (design/baseline/%s is the approved one)" % styles.STYLE_NAME))
            elif not style.get("locked"):
                self.report.note("the style is unlocked (decisions.md says why): drift is measured against the "
                                 "last baseline; approve a new one once the user agrees the new look")
        tol = styles.drift_tolerances(style or b.style)
        pairs, new, gone = match_baseline(inputs.files, b.files, inputs.primary)
        for cur, base in pairs:
            for message in drift_messages(cur, base, tol):
                self.report.add("design", own_finding("design.baseline.drift", "warning", self.where(cur),
                                                      message))
        if new:
            self.report.note("no baseline counterpart (new since the baseline, compared by role or layout where "
                             "one matched): %s" % ", ".join(new))
        if gone:
            self.report.note("in the baseline but not in this set: %s" % ", ".join(gone))

    # -- fallbacks and the checklist -----------------------------------------------------------------

    def check_fallbacks(self):
        """List what fell back to the primary locale (captures and strings), grouped by locale and shot."""
        groups = collections.OrderedDict()
        for f in self.inputs.files:
            for flag, what in (("captureFallback", "capture"), ("stringFallback", "words")):
                if f.get(flag):
                    key = (f.get("locale"), what, f.get("shot"))
                    groups.setdefault(key, []).append(f.get("target"))
        for (loc, what, shot), targets in groups.items():
            self.report.fallbacks.append(collections.OrderedDict([
                ("locale", loc), ("what", what), ("shot", shot), ("from", self.inputs.primary),
                ("targets", sorted(set(t for t in targets if t)))]))

    def checklist(self):
        """What a person checks by eye: the pre-ship list less what this script decided, the store rules'
        checklist items for the slots in use, and the design table's awards."""
        r = self.report
        stores = [s for s in r.stores if s in STORES]
        r.look("all", "look.first_three",
               "Shots 1-3 each say what the app is at search size (sheets/search-row-*.png, play-listing-*.png), "
               "and shot 1 reads without shot 2.")
        r.look("all", "look.words",
               "No word broken across lines but by proper hyphenation, nothing cut off, every locale's words "
               "read right (CJK line breaks, a German compound).")
        r.look("all", "look.content",
               "Real UI from the current version on the latest OS; invented data only; a clean status bar (full "
               "bars and battery, no carrier, no notifications); no debug overlays, toasts, banners, prompts or "
               "spinners.")
        r.look("all", "look.ages", "Fit for all ages in every shot: no gore, no weapon aimed at a person.")
        awards = []
        for s in stores:
            e = self.inputs.design_entry(s, "awards")
            if e:
                awards.append("%s: %s" % (STORE_NAMES[s], {
                    "verifiableOnly": "real third-party awards only, none of the store's own",
                    "forbidden": "none", "allowed": "allowed"}.get(e.get("value"), e.get("value"))))
        r.look("all", "look.marks",
               "No other platforms' devices, logos, button glyphs or store badges; award laurels and badges in the "
               "art only as each store allows (%s); others' names, logos and characters flagged to the user, never "
               "decided." % ("; ".join(awards) or "check each store's rules"))
        r.look("all", "look.frames",
               "Frames are generic drawn ones that copy no maker's details, or the user's own Apple bezels used as "
               "they are; none on Wear OS; Play frameless unless the user chose otherwise.")
        r.look("all", "look.rights", "The rights to every photo, font, artwork and character shown; credits "
               "recorded.")
        r.look("all", "look.disclaimers", "Required disclaimers present and legible (subscriptions, finance, "
               "regional availability).")
        r.look("all", "look.system", "One visual system across the set (caption style and place, frame, palette); "
               "a dark-mode variant if the app has dark mode.")
        if any(loc.split("-")[0].lower() in RTL_LANGUAGES for loc in self.inputs.locales):
            r.look("all", "look.rtl", "Right-to-left locales: captured in the app's RTL mode; logos, media controls "
                   "and clocks not mirrored; a panorama's order checked in that storefront.")
        r.look("all", "look.dated", "Nothing dated or seasonal in the screenshots (seasonal art goes in assets "
               "that change without a new version).")
        r.look("all", "look.required", "Sizes the check can't know are needed: Play tablet shots if the app runs "
               "on tablets; iPhone Duo once Apple requires it (re-verify the date).")
        if "google" in stores:
            r.look("google", "look.alt_text", "Play alt text for each screenshot in each locale (140 characters at "
                   "most, not starting \"photo of\" or \"image of\"), set in Play Console.")
        r.look("all", "look.experiment", "Propose a product page optimisation (Apple) or store listing experiment "
               "(Play) for the first shot, naming the after-install measure to watch.")
        for store in stores:
            rs = self.inputs.rulesets[store]
            used = set()
            for by_slot in self._pictures(store).values():
                used |= set(by_slot)
            for rule in rs.by_kind("checklist"):
                if (rule.get("applies") or {}).get("media") == "preview" or not set(rule.slots) & used:
                    continue
                cond = rule.get("when") or {}
                if cond.get("slotUsed") and cond["slotUsed"] not in used:
                    continue
                r.look(store, rule.id, rule.get("item"), rule.source, rule.status)


def aspect_class(width, height):
    """The aspect class of a slot: tall (w/h under 0.6), mid (0.6-0.85), square (0.85-1.2) or wide."""
    a = width / float(height)
    if a < 0.6:
        return "tall"
    if a < 0.85:
        return "mid"
    if a <= 1.2:
        return "square"
    return "wide"


def _plain(text):
    return text.replace("*", "").replace("\\n", " ").replace("\n", " ").strip()


def case_ok(text, want, drawn=None):
    """True if ``text`` is in ``want`` case (sentence, title, upper, lower), as drawn (``drawn``: the caption's
    ``case`` setting, ``upper`` or ``lower``, changes what's seen)."""
    t = _plain(text)
    if drawn == "upper":
        t = t.upper()
    elif drawn == "lower":
        t = t.lower()
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return True
    if want == "upper":
        return t == t.upper()
    if want == "lower":
        return t == t.lower()
    words = [w for w in re.findall(r"[^\W\d_][\w'’-]*", t)]
    long_words = [w for w in words[1:] if len(w) >= 4]
    if want == "title":
        return all(w[0].isupper() for w in [words[0]] + long_words) if words else True
    if want == "sentence":
        if len(letters) > 3 and t == t.upper():
            return False
        if letters[0].upper() != letters[0].lower() and not letters[0].isupper():
            return False
        if len(long_words) >= 2 and all(w[0].isupper() for w in long_words):
            return False
        return True
    return True


def _lab(rgb):
    """CIE L*a*b* (D65) of an sRGB colour."""
    lin = [_LINEAR[c] for c in rgb]
    x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    y = (0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]) / 1.0
    z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883

    def f(t):
        return t ** (1.0 / 3) if t > 0.008856 else 7.787 * t + 16.0 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a, b):
    """CIE76 delta E between two CSS colours, or ``None`` when one can't be read."""
    ca, cb = parse_colour(a), parse_colour(b)
    if ca is None or cb is None:
        return None
    la, lb = _lab(ca), _lab(cb)
    return math.sqrt(sum((la[i] - lb[i]) ** 2 for i in range(3)))


class Baseline:
    """An approved baseline (``design/baseline``): its ``baseline.json``, its render report's files and its
    copy of the style."""

    def __init__(self, folder):
        self.folder = folder
        meta_path = os.path.join(folder, "baseline.json")
        if not os.path.isfile(meta_path):
            raise UsageError("no baseline at %s (baseline.py approve makes one, with the user's say)" % folder)
        try:
            self.meta = jsonio.load(meta_path)
            report = jsonio.load(os.path.join(folder, self.meta.get("report") or "render-report.json"))
        except (OSError, jsonio.JsonError) as e:
            raise UsageError("the baseline at %s can't be read: %s" % (folder, e))
        self.report = report
        self.files = [f for f in (report.get("files") or []) if isinstance(f, dict)]
        self.style = None
        style_copy = os.path.join(folder, styles.STYLE_NAME)
        if os.path.isfile(style_copy):
            try:
                self.style = jsonio.load(style_copy)
            except jsonio.JsonError:
                self.style = None

    def path(self, f):
        """A baseline file's PNG."""
        return os.path.join(self.folder, f.get("path") or "")


def match_baseline(files, base_files, primary):
    """Pair each current file with its baseline counterpart: the same locale, target and shot; else the primary
    locale's; else, for a shot new since the baseline, one of the same target with the same role, else the same
    layout. Returns ``(pairs, new, gone)``: ``[(current, baseline)]``, the current files that had no counterpart
    of their own shot (``locale/target/shot``), and the baseline's target/shot pairs no longer in the set."""
    index = {}
    for b in base_files:
        index.setdefault((b.get("locale"), b.get("target"), b.get("shot")), b)
    pairs, new = [], []
    for f in files:
        loc, tid, shot = f.get("locale"), f.get("target"), f.get("shot")
        b = index.get((loc, tid, shot)) or index.get((primary, tid, shot))
        if b is None:
            new.append("%s/%s/%s" % (loc, tid, shot))
            same = [x for x in base_files if x.get("target") == tid and x.get("locale") in (loc, primary)]
            if f.get("role"):
                b = next((x for x in same if x.get("role") == f.get("role")), None)
            if b is None:
                b = next((x for x in same if x.get("layout") == f.get("layout")), None)
        if b is not None:
            pairs.append((f, b))
    have = set((f.get("target"), f.get("shot")) for f in files)
    gone = sorted(set("%s/%s" % (b.get("target"), b.get("shot")) for b in base_files
                      if (b.get("target"), b.get("shot")) not in have))
    return pairs, new, gone


def drift_messages(cur, base, tol):
    """What moved between a file and its baseline counterpart past the tolerances (``styles.DEFAULT_DRIFT``'s
    keys), one message each."""
    out = []
    w = float(cur.get("width") or 0) or 1.0
    bw = float(base.get("width") or 0) or w

    def u(v, width):
        return 100.0 * float(v) / width

    if cur.get("layout") != base.get("layout"):
        out.append("layout is %s; the baseline's was %s" % (cur.get("layout"), base.get("layout")))
    c, b = cur.get("caption"), base.get("caption")
    c = c if isinstance(c, dict) and c.get("text") is not None else None
    b = b if isinstance(b, dict) and b.get("text") is not None else None
    if bool(c) != bool(b):
        out.append("has a caption; the baseline's had none" if c else "has no caption; the baseline's had one")
    if c and b:
        if c.get("fontPx") and b.get("fontPx"):
            cu, bu = u(c["fontPx"], w), u(b["fontPx"], bw)
            change = (cu - bu) / bu if bu else 0
            if abs(change) > tol["captionSize"] + 1e-9:
                out.append("caption size %.1fu, the baseline's %.1fu (%+.0f%%; tolerance %.0f%%)" % (
                    cu, bu, 100 * change, 100 * tol["captionSize"]))
        cb, bb = _box(c.get("box")), _box(b.get("box"))
        if cb and bb:
            top = abs(u(cb[1], w) - u(bb[1], bw))
            if top > 100 * tol["captionPosition"] + 1e-9:
                out.append("caption top %.1fu, the baseline's %.1fu (tolerance %.1fu)" % (
                    u(cb[1], w), u(bb[1], bw), 100 * tol["captionPosition"]))
            size_drift = any(m.startswith("caption size") for m in out)
            if c.get("lines") == b.get("lines") and not size_drift:
                height = abs(u(cb[3], w) - u(bb[3], bw))
                if height > 100 * tol["captionPosition"] + 1e-9:
                    out.append("caption height %.1fu, the baseline's %.1fu (tolerance %.1fu)" % (
                        u(cb[3], w), u(bb[3], bw), 100 * tol["captionPosition"]))
        if c.get("lines") != b.get("lines"):
            out.append("caption runs to %s lines; the baseline's %s" % (c.get("lines"), b.get("lines")))
        for key, label in (("ink", "caption ink"), ("accent", "accent")):
            if c.get(key) and b.get(key):
                d = delta_e(c[key], b[key])
                if d is not None and d > tol["colour"]:
                    out.append("%s %s, the baseline's %s (delta E %.1f)" % (label, c[key], b[key], d))
            elif bool(c.get(key)) != bool(b.get(key)) and key == "accent":
                out.append("%s an accent word" % ("has" if c.get(key) else "no longer has"))
        cs, bs = c.get("textShare"), b.get("textShare")
        if isinstance(cs, (int, float)) and isinstance(bs, (int, float)) and abs(cs - bs) > tol["textShare"] + 1e-9:
            out.append("words cover %.0f%% of the picture, the baseline's %.0f%%" % (100 * cs, 100 * bs))
    fc, fb = cur.get("frame"), base.get("frame")
    nc = fc.get("name") if isinstance(fc, dict) else None
    nb = fb.get("name") if isinstance(fb, dict) else None
    if (nc or "none") != (nb or "none"):
        out.append("frame %s, the baseline's %s" % (nc or "none", nb or "none"))
    elif isinstance(fc, dict) and isinstance(fb, dict):
        xc, xb = _box(fc.get("box")), _box(fb.get("box"))
        if xc and xb:
            moved = []
            for i, name in enumerate(("x", "y", "width", "height")):
                d = abs(u(xc[i], w) - u(xb[i], bw))
                if d > 100 * tol["deviceBox"] + 1e-9:
                    moved.append("%s %.1fu, was %.1fu" % (name, u(xc[i], w), u(xb[i], bw)))
            if moved:
                out.append("the device moved: %s (tolerance %.1fu)" % ("; ".join(moved), 100 * tol["deviceBox"]))
        if bool(fc.get("tilted")) != bool(fb.get("tilted")):
            out.append("the device is %s; the baseline's wasn't" % "tilted" if fc.get("tilted") else
                       "the device isn't tilted; the baseline's was")
    if (cur.get("tilt") or None) != (base.get("tilt") or None) and cur.get("tilt") and base.get("tilt"):
        out.append("tilts %s; the baseline's tilted %s" % (cur.get("tilt"), base.get("tilt")))
    gc, gb = cur.get("background"), base.get("background")
    if isinstance(gc, dict) and isinstance(gb, dict):
        if gc.get("kind") != gb.get("kind"):
            out.append("background %s, the baseline's %s" % (gc.get("kind"), gb.get("kind")))
        else:
            cc, cbg = gc.get("colours") or [], gb.get("colours") or []
            far = [d for d in (delta_e(x, y) for x, y in zip(cc, cbg)) if d is not None and d > tol["colour"]]
            if far or len(cc) != len(cbg):
                out.append("background colours %s, the baseline's %s" % (" ".join(cc), " ".join(cbg)))
            if gc.get("image") != gb.get("image"):
                out.append("background image %s, the baseline's %s" % (gc.get("image"), gb.get("image")))
    return out


def _num(v):
    if isinstance(v, (int, float)):
        return ("%.1f" % v).rstrip("0").rstrip(".")
    return "?"


AUTO = "auto"


def find_baseline(inputs, baseline=AUTO):
    """The ``Baseline`` to compare with: ``None`` (none asked for, or none approved yet with ``AUTO``), the design
    folder's ``baseline/`` (``AUTO`` or ``""``), or a folder given."""
    if baseline is None:
        return None
    if baseline in (AUTO, ""):
        folder = os.path.join(inputs.design_dir, "baseline")
        if baseline == AUTO and not os.path.isfile(os.path.join(folder, "baseline.json")):
            return None
    else:
        folder = baseline
    return Baseline(folder)


def run_check(config_path, listing_path=None, rules_dir=RULES_DIR, report_path=None, baseline=AUTO,
              style_path=None):
    """Check a rendered set; return the ``Report``. ``baseline``: ``AUTO`` (the approved one when there is one),
    ``None`` (no drift check), ``""`` (the design folder's, required) or a folder. Raises ``UsageError`` for a
    missing config, report or asked-for baseline."""
    try:
        inputs = Inputs(config_path, listing_path, rules_dir, report_path, style_path)
        base = find_baseline(inputs, baseline)
    except jsonio.JsonError as e:
        raise UsageError(str(e))
    report = Report(os.path.relpath(config_path), inputs.relax())
    Check(inputs, report, base).run()
    return report


def parser():
    """The argument parser."""
    p = argparse.ArgumentParser(prog="check.py", description="Check rendered store screenshots against each "
                                "store's rules and the design's limits. Offline.")
    p.add_argument("--config", default="store-screenshots.json", help="the design config (default: %(default)s)")
    p.add_argument("--listing", help="store-listing.json (default: beside the config, if there)")
    p.add_argument("--report", help="the render report (default: <out>/render-report.json); its files' paths "
                   "stay relative to <out>")
    p.add_argument("--baseline", nargs="?", const="", default=AUTO, metavar="DIR",
                   help="compare with an approved baseline (default: <design>/baseline, used by itself when it's "
                   "there)")
    p.add_argument("--no-baseline", action="store_true", help="don't compare with the baseline")
    p.add_argument("--json", action="store_true", help="print the findings as JSON")
    return p


def main(argv=None):
    """Run the check; return the exit code."""
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return EXIT_OK if e.code in (0, None) else EXIT_USAGE
    try:
        report = run_check(args.config, args.listing, report_path=args.report,
                           baseline=None if args.no_baseline else args.baseline)
    except UsageError as e:
        sys.stderr.write("check.py: %s\n" % e)
        return EXIT_USAGE
    except rules.RulesError as e:
        sys.stderr.write("check.py: the rules data is broken: %s\n" % e)
        return EXIT_USAGE
    if args.json:
        sys.stdout.write(jsonio.dumps(report.to_json()))
    else:
        sys.stdout.write(report.to_text())
    return EXIT_ERRORS if report.errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
