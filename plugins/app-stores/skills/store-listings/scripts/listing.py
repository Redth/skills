#!/usr/bin/env python3
"""listing.py: check, build, preview and import an app's store listing (``store-listing.json``).

Subcommands (run from the user's project; every one is offline):

    listing.py import --from fastlane|supply|triple-t|expo|live <path> [--out store-listing.json] [--platform P]
    listing.py check  [--config store-listing.json] [--stores apple,google] [--json]
    listing.py build  [--config store-listing.json] [--out out]
    listing.py preview [--config store-listing.json] [--out out] [--png]
    listing.py diff   [--config store-listing.json] [--existing existing] [--stores apple,google] [--json]

``check`` validates the config against ``schema/store-listing.schema.json``, then runs every rule in
``rules/<store>.json`` for each enabled store on the words (after locale fallback) and the picture files.
``build`` runs the check (errors stop it) and writes ``out/``: fastlane ``deliver`` and ``supply`` layouts,
``out/listing.json`` (what ``push.py`` reads) and ``out/checklist.md``. ``preview`` draws each store's page
from ``out/`` as HTML (and, with ``--png``, pictures through headless Chrome). ``import`` starts or extends a
config from fastlane, Triple-T or Expo metadata, or from what ``push.py pull`` read off the stores (``live``);
``diff`` compares the config's words with that (offline: it reads ``existing/``).

Exit codes: 0 done; 1 a check error; 3 usage or environment (no config, no Chrome).
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appstores_lib import jsonio  # noqa: E402
from appstores_lib import locales  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import rules  # noqa: E402
from appstores_lib import schema  # noqa: E402

if __name__ == "__main__":
    # listing_import and listing_preview import this module as ``listing``: make that this same module.
    sys.modules.setdefault("listing", sys.modules[__name__])

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
RULES_DIR = os.path.join(SKILL_DIR, "rules")
SCHEMA_PATH = os.path.join(SKILL_DIR, "schema", "store-listing.schema.json")

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_REFUSED = 2
EXIT_USAGE = 3

STORES = ("apple", "google")
LATER_STORES = ("amazon", "steam", "itch")
STORE_NAMES = {"apple": "App Store", "google": "Google Play", "config": "Config",
               "amazon": "Amazon Appstore", "steam": "Steam", "itch": "itch.io"}
APPLE_PLATFORMS = ("IOS", "MAC_OS", "TV_OS", "VISION_OS")
GOOGLE_SCREEN_SLOTS = ("phone", "tablet7", "tablet10", "tv", "wear")
GOOGLE_GRAPHICS = ("icon", "featureGraphic", "tvBanner")
PICTURE_EXTS = (".png", ".jpg", ".jpeg")
VIDEO_MIME = {".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/x-m4v"}

# The locale fields each store reads (after fallback). ``apple.description`` and ``google.fullDescription``
# fall back to the locale's shared ``description``.
STORE_FIELDS = {
    "apple": ("apple.name", "apple.subtitle", "apple.keywords", "apple.promotionalText", "apple.whatsNew",
              "apple.description"),
    "google": ("google.title", "google.shortDescription", "google.fullDescription", "google.video",
               "google.releaseNotes", "altText.featureGraphic"),
}
LOCALE_PREFIXES = ("apple.", "google.", "altText.")

# App Store Connect keeps these per platform (a version's words): ``locales.<loc>.apple.platforms.<P>.<field>``
# overrides them for one platform. ``name`` and ``subtitle`` are the app's (appInfo), the same on every platform.
APPLE_PLATFORM_FIELDS = ("description", "keywords", "promotionalText", "whatsNew", "marketingUrl", "supportUrl")
APPLE_PLATFORM_PATHS = tuple("apple." + f for f in APPLE_PLATFORM_FIELDS)
APPLE_URL_FIELDS = {"marketingUrl": "marketing", "supportUrl": "support"}

# A config's own findings (not a store's rule) use these ids; they can't be relaxed.
CONFIG_STORE = "config"


class UsageError(Exception):
    """A usage or environment problem: exit 3 with this message."""


def config_finding(rule_id, where, message, severity="error"):
    """A finding about the config itself (schema, references, files), not a store's rule."""
    return rules.Finding(rule_id, severity, where, message, None, "verified")


def _missing(value):
    """True for a value a ``required`` rule counts as absent: null, empty or blank text, an empty list or object."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not [v for k, v in (value.items() if isinstance(value, dict) else enumerate(value))
                    if not (isinstance(k, str) and k.startswith("$"))]
    return False


def _size_text(size):
    return "%dx%d" % (size[0], size[1])


# ---------------------------------------------------------------------------------------------------------
# Pictures

class Picture:
    """One picture file a store would get: which screen and shot it is, for which locale, where it is, which
    locale's file it really is (``from_locale``, the primary's when it fell back), and its header (``info``,
    or ``error`` when it isn't a PNG or JPEG this can read)."""

    def __init__(self, screen, shot, path, rel, locale, from_locale, info, error):
        self.screen = screen
        self.shot = shot
        self.path = path
        self.rel = rel
        self.locale = locale
        self.from_locale = from_locale
        self.info = info
        self.error = error
        self.slot = None

    @property
    def size(self):
        """(width, height), or None when the file couldn't be read."""
        return (self.info.width, self.info.height) if self.info else None

    @property
    def fell_back(self):
        """True when the locale had no file of its own and this is the primary locale's."""
        return self.locale != self.from_locale

    def __repr__(self):
        return "Picture(%r)" % self.rel


def fits(size, sizes, orientation=None):
    """True when ``size`` ([w, h]) is one of ``sizes`` in the orientation a rules file allows (``None``:
    either way round; ``portrait``/``landscape``: only that way; ``asListed``: exactly as written)."""
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


def accepted_sizes(sizes, orientation=None):
    """Every [w, h] a size list accepts, as tuples (both orientations unless one is set)."""
    out = []
    for sw, sh in sizes:
        if orientation == "asListed":
            cands = [(sw, sh)]
        elif orientation == "portrait":
            cands = [(min(sw, sh), max(sw, sh))]
        elif orientation == "landscape":
            cands = [(max(sw, sh), min(sw, sh))]
        else:
            cands = [(sw, sh), (sh, sw)]
        for c in cands:
            if c not in out:
                out.append(c)
    return out


def in_range(size, rng):
    """True when ``size`` is within a rules ``range`` (minSide, maxSide, minAspect, maxAspect)."""
    w, h = size
    short, long_ = min(w, h), max(w, h)
    if rng.get("minSide") is not None and short < rng["minSide"]:
        return False
    if rng.get("maxSide") is not None and long_ > rng["maxSide"]:
        return False
    aspect = long_ / float(short) if short else float("inf")
    if aspect < float(rng.get("minAspect", 1)) - 1e-9:
        return False
    if rng.get("maxAspect") is not None and aspect > float(rng["maxAspect"]) + 1e-9:
        return False
    return True


def describe_range(rng):
    """A range in words: 'each side 320-3840 px, the long side at most 2x the short'."""
    parts = []
    lo, hi = rng.get("minSide"), rng.get("maxSide")
    if lo is not None and hi is not None:
        parts.append("each side %d-%d px" % (lo, hi))
    elif lo is not None:
        parts.append("each side at least %d px" % lo)
    elif hi is not None:
        parts.append("each side at most %d px" % hi)
    mn, mx = rng.get("minAspect"), rng.get("maxAspect")
    if mn is not None and mx is not None and abs(mn - mx) < 1e-9:
        parts.append("square" if abs(mn - 1) < 1e-9 else "long side %g x the short" % mn)
    elif mn is not None and mx is not None and abs(mn - 1.77) < 0.02 and abs(mx - 1.78) < 0.02:
        parts.append("16:9 or 9:16")
    else:
        if mn is not None and mn > 1:
            parts.append("the long side at least %gx the short" % mn)
        if mx is not None:
            parts.append("the long side at most %gx the short" % mx)
    return ", ".join(parts)


# ---------------------------------------------------------------------------------------------------------
# The config

class Listing:
    """A loaded ``store-listing.json``: its data, folder, and the lookups the checks and the build share
    (words after fallback, pictures after fallback, slots)."""

    def __init__(self, path, data):
        self.path = os.path.abspath(path)
        self.dir = os.path.dirname(self.path)
        self.data = data
        self._info = {}

    # -- plain lookups -----------------------------------------------------------------------------------

    @property
    def primary(self):
        """The primary locale (BCP 47)."""
        return self.data.get("primaryLocale")

    @property
    def locale_codes(self):
        """The config's locales, primary first, then in the config's order."""
        codes = [k for k in (self.data.get("locales") or {}) if not k.startswith("$")]
        if self.primary in codes:
            codes.remove(self.primary)
            codes.insert(0, self.primary)
        return codes

    def store(self, name):
        """The config's ``stores.<name>`` object (``{}`` when absent)."""
        return (self.data.get("stores") or {}).get(name) or {}

    def store_primary(self, store):
        """A store's primary locale: ``stores.apple.primaryLocale`` or ``stores.google.defaultLanguage``, else the
        config's ``primaryLocale``."""
        key = {"apple": "primaryLocale", "google": "defaultLanguage"}.get(store)
        return (self.store(store).get(key) if key else None) or self.primary

    def store_locale_codes(self, store):
        """The locales a store gets (``stores.<store>.locales``, else every one of the config's), the store's
        primary first. Names that aren't the config's locales are left out (the check reports them)."""
        listed = self.store(store).get("locales")
        codes = self.locale_codes
        if isinstance(listed, list):
            codes = [c for c in codes if c in listed]
        first = self.store_primary(store)
        if first in codes:
            codes.remove(first)
            codes.insert(0, first)
        return codes

    def fallback_order(self, loc, store=None):
        """The locales a field is looked for in: the locale, the store's primary, then the config's primary."""
        out = []
        for l in (loc, self.store_primary(store) if store else None, self.primary):
            if l and l not in out:
                out.append(l)
        return out

    def enabled(self, name):
        """True when ``stores.<name>.enabled`` is true."""
        return bool(self.store(name).get("enabled"))

    def screens(self):
        """The config's screens: ``{name: {"kind": …}}``."""
        return dict((k, v) for k, v in (self.data.get("screens") or {}).items() if not k.startswith("$"))

    def screen_kind(self, screen):
        """A screen's kind, or None for a screen the config doesn't define."""
        return (self.screens().get(screen) or {}).get("kind")

    def shots(self):
        """The shots, in order."""
        return list((self.data.get("screenshots") or {}).get("shots") or [])

    def shots_for(self, store, screen):
        """The ids of the shots a store shows on a screen, in order (the ``screens``/``stores`` filters)."""
        out = []
        for shot in self.shots():
            if shot.get("stores") is not None and store not in shot["stores"]:
                continue
            if shot.get("screens") is not None and screen not in shot["screens"]:
                continue
            out.append(shot["id"])
        return out

    def apple_platforms(self):
        """The Apple platforms the config ships (non-null), in App Store Connect's order."""
        plats = self.store("apple").get("platforms") or {}
        return [p for p in APPLE_PLATFORMS if plats.get(p)]

    def platform_screens(self, platform):
        """The screens an Apple platform uses."""
        return list(((self.store("apple").get("platforms") or {}).get(platform) or {}).get("screens") or [])

    def google_slots(self):
        """``{slot: screen}`` for the Play screenshot slots the config fills."""
        slots = self.store("google").get("slots") or {}
        return collections.OrderedDict((s, slots[s]) for s in GOOGLE_SCREEN_SLOTS if slots.get(s))

    def google_graphics(self):
        """``{graphic: path}`` for the Play graphics the config sets."""
        g = self.store("google").get("graphics") or {}
        return collections.OrderedDict((k, g[k]) for k in GOOGLE_GRAPHICS if g.get(k))

    def is_game(self, store):
        """True when the app's category is a game (Apple ``GAMES``, Play ``GAME_*``). Play's category is
        optional: without it, Apple's is used, else it's taken as not a game."""
        apple_cat = (self.store("apple").get("categories") or {}).get("primary")
        google_cat = self.store("google").get("category")
        if store == "google" and google_cat:
            return google_cat.startswith("GAME_")
        if apple_cat:
            return apple_cat == "GAMES"
        if google_cat:
            return google_cat.startswith("GAME_")
        return False

    def abspath(self, rel):
        """A config-relative path made absolute."""
        return os.path.normpath(os.path.join(self.dir, rel))

    def relpath(self, path):
        """A path relative to the config's folder, with forward slashes."""
        return os.path.relpath(path, self.dir).replace(os.sep, "/")

    # -- words ---------------------------------------------------------------------------------------------

    def _raw(self, loc, group, field):
        words = (self.data.get("locales") or {}).get(loc) or {}
        if group is None:
            return words.get(field)
        node = words
        for key in (group if isinstance(group, tuple) else (group,)):
            node = node.get(key) if isinstance(node, dict) else None
        return node.get(field) if isinstance(node, dict) else None

    def resolve(self, loc, path, store=None, platform=None):
        """A locale field's value after fallback, and the locale it came from: ``(value, locale)``.

        A field is looked for in the locale, then the store's primary locale, then the config's
        (``fallback_order``; the store is the path's own, ``apple.``/``google.``/``altText.``, unless given).
        ``apple.description`` and ``google.fullDescription`` take the same locale's shared ``description``
        before moving on (so a translated shared description beats the primary's store-specific one). With a
        ``platform``, an Apple version field (``APPLE_PLATFORM_PATHS``) first takes that platform's override
        (``locales.<loc>.apple.platforms.<P>.<field>``) at each step. ``apple.name`` ends at ``app.name``,
        ``apple.marketingUrl``/``supportUrl`` at ``app.urls`` (locale ``None``). ``(None, None)`` when nothing
        sets it.
        """
        if store is None:
            store = "apple" if path.startswith("apple.") else (
                "google" if path.startswith(("google.", "altText.")) else None)
        order = self.fallback_order(loc, store)
        cands = []
        if path == "description":
            cands = [(l, None, "description") for l in order]
        else:
            group, field = path.split(".", 1)
            for l in order:
                if group == "apple" and platform and path in APPLE_PLATFORM_PATHS:
                    cands.append((l, ("apple", "platforms", platform), field))
                if group == "apple" and field in APPLE_URL_FIELDS:
                    continue  # a URL is set per platform, or app-wide in app.urls
                cands.append((l, group, field))
                if path in ("apple.description", "google.fullDescription"):
                    cands.append((l, None, "description"))
        for l, g, f in cands:
            value = self._raw(l, g, f)
            if value is not None:
                return value, l
        if path == "apple.name":
            return (self.data.get("app") or {}).get("name"), None
        if path.startswith("apple.") and path[6:] in APPLE_URL_FIELDS:
            return ((self.data.get("app") or {}).get("urls") or {}).get(APPLE_URL_FIELDS[path[6:]]), None
        return None, None

    def platform_overrides(self, loc):
        """``{platform: {field: value}}`` a locale sets for single Apple platforms (nulls left out)."""
        plats = ((((self.data.get("locales") or {}).get(loc) or {}).get("apple") or {}).get("platforms")) or {}
        out = collections.OrderedDict()
        for p in APPLE_PLATFORMS:
            words = plats.get(p) or {}
            given = collections.OrderedDict((k, v) for k, v in words.items() if not k.startswith("$") and v is not None)
            if given:
                out[p] = given
        return out

    def root_value(self, path):
        """A value read from the config's root (``app.…``, ``stores.…``). Where the config names an
        environment variable instead (``phone`` → ``phoneEnv``), the variable's value (None if unset)."""
        node = self.data
        parts = path.split(".")
        for i, part in enumerate(parts):
            if not isinstance(node, dict):
                return None
            if part in node:
                node = node[part]
                continue
            env = node.get(part + "Env")
            if i == len(parts) - 1 and isinstance(env, str):
                return os.environ.get(env)
            return None
        return node

    def env_name(self, path):
        """The environment variable a root path reads (``…contact.phone`` → the ``phoneEnv`` value), or None."""
        parent, _, last = path.rpartition(".")
        node = self.root_value(parent) if parent else self.data
        if isinstance(node, dict) and last not in node and isinstance(node.get(last + "Env"), str):
            return node[last + "Env"]
        return None

    # -- pictures ------------------------------------------------------------------------------------------

    def picture_info(self, path):
        """``(ImageInfo, None)`` or ``(None, message)`` for a file, read once."""
        if path not in self._info:
            try:
                self._info[path] = (png.info(path), None)
            except (png.ImageError, OSError, ValueError) as e:
                self._info[path] = (None, str(e))
        return self._info[path]

    def _picture_file(self, loc, screen, shot):
        folder = (self.data.get("screenshots") or {}).get("folder") or "screenshots"
        for ext in PICTURE_EXTS:
            p = self.abspath(os.path.join(folder, loc, screen, shot + ext))
            if os.path.isfile(p):
                return p
        return None

    def picture(self, loc, screen, shot, store=None):
        """The ``Picture`` for a locale, screen and shot: the locale's own file, else the store's primary
        locale's, else the config's primary's (a fallback), else None."""
        for from_loc in self.fallback_order(loc, store):
            path = self._picture_file(from_loc, screen, shot)
            if path is not None:
                info, err = self.picture_info(path)
                return Picture(screen, shot, path, self.relpath(path), loc, from_loc, info, err)
        return None

    def graphic(self, name):
        """The ``Picture`` for a Play graphic (``icon``…), or None when the config sets none or it's missing."""
        rel = self.google_graphics().get(name)
        if not rel:
            return None
        path = self.abspath(rel)
        if not os.path.isfile(path):
            return None
        info, err = self.picture_info(path)
        pic = Picture(None, name, path, self.relpath(path), None, None, info, err)
        pic.slot = name
        return pic


def load_listing(path):
    """Read a config (exit 3 when it isn't there; a JSON error is raised as ``jsonio.JsonError``)."""
    if not os.path.isfile(path):
        raise UsageError("no config at %s (pass --config, or start one with listing.py import)" % path)
    return Listing(path, jsonio.load(path))


def load_schema():
    """The config's JSON Schema."""
    return jsonio.load(SCHEMA_PATH)


# ---------------------------------------------------------------------------------------------------------
# The report

class Report:
    """What a check found: findings per store, fallbacks, relaxed rules, checklist items and notes."""

    def __init__(self, config_path):
        self.config_path = config_path
        self.findings = []      # (store, Finding)
        self.fallbacks = []     # dicts
        self.relaxed = []       # dicts
        self.checklist = []     # dicts
        self.not_checked = []   # dicts
        self.notes = []         # strings
        self.stores = []        # stores checked
        self._seen = set()
        self._fallback_seen = set()
        self._checklist_seen = set()

    def add(self, store, finding):
        """Add a finding (each identical finding once)."""
        key = (store,) + tuple(finding)
        if key in self._seen:
            return
        self._seen.add(key)
        self.findings.append((store, finding))

    def fallback(self, store, locale, what, from_locale, file=None):
        """Record that a locale's field or picture came from the primary locale."""
        key = (store, locale, what)
        if key in self._fallback_seen:
            return
        self._fallback_seen.add(key)
        entry = collections.OrderedDict([("store", store), ("locale", locale), ("what", what),
                                         ("from", from_locale)])
        if file is not None:
            entry["file"] = file
        self.fallbacks.append(entry)

    def add_checklist(self, store, rule):
        """Record a checklist rule (once per store and id)."""
        if (store, rule.id) in self._checklist_seen:
            return
        self._checklist_seen.add((store, rule.id))
        self.checklist.append(collections.OrderedDict([
            ("store", store), ("id", rule.id), ("item", rule.get("item")), ("severity", rule.declared_severity),
            ("source", rule.source), ("status", rule.status), ("checked", rule.checked)]))

    def skip(self, store, rule, why):
        """Record a rule that couldn't be decided offline."""
        if any(n["id"] == rule.id and n["store"] == store for n in self.not_checked):
            return
        self.not_checked.append(collections.OrderedDict([("store", store), ("id", rule.id), ("why", why)]))

    @property
    def errors(self):
        """The error findings."""
        return [f for s, f in self.findings if f.severity == "error"]

    @property
    def warnings(self):
        """The warning findings."""
        return [f for s, f in self.findings if f.severity == "warning"]

    def to_json(self):
        """The report as ``--json`` prints it."""
        findings = []
        for store, f in self.findings:
            obj = collections.OrderedDict(f._asdict())
            obj["store"] = store
            findings.append(obj)
        return collections.OrderedDict([
            ("config", self.config_path), ("stores", list(self.stores)),
            ("findings", findings), ("fallbacks", self.fallbacks), ("relaxed", self.relaxed),
            ("checklist", self.checklist), ("notChecked", self.not_checked), ("notes", self.notes),
            ("summary", collections.OrderedDict([("errors", len(self.errors)),
                                                 ("warnings", len(self.warnings))])),
        ])

    def to_text(self):
        """The report as text: findings grouped by store and severity, then fallbacks, relaxed rules,
        what wasn't checked, the checklist's size, and a summary."""
        lines = []
        stores = [CONFIG_STORE] + [s for s in self.stores if s != CONFIG_STORE]
        for store in stores:
            mine = [f for s, f in self.findings if s == store]
            if not mine and store == CONFIG_STORE:
                continue
            n_err = len([f for f in mine if f.severity == "error"])
            n_warn = len(mine) - n_err
            lines.append("%s (%s): %s, %s" % (STORE_NAMES.get(store, store), store, _plural(n_err, "error"),
                                              _plural(n_warn, "warning")))
            for sev, title in (("error", "Errors"), ("warning", "Warnings")):
                group = [f for f in mine if f.severity == sev]
                if not group:
                    continue
                lines.append("  %s:" % title)
                for f in group:
                    lines.append("    %s: %s [%s]" % (f.where, f.message, f.rule_id))
            lines.append("")
        if self.fallbacks:
            lines.append("Fell back to the primary locale (%s): not errors, but check they're meant to be:"
                         % ", ".join(sorted(set(f["from"] for f in self.fallbacks))))
            for fb in self.fallbacks:
                extra = " (%s)" % fb["file"] if fb.get("file") else ""
                lines.append("  %s %s %s%s" % (fb["store"], fb["locale"], fb["what"], extra))
            lines.append("")
        if self.relaxed:
            lines.append("Relaxed by the config (not checked):")
            for r in self.relaxed:
                lines.append("  %s: %s" % (r["id"], r["reason"] or "(no reason given)"))
            lines.append("")
        if self.not_checked:
            lines.append("Not checked offline:")
            for n in self.not_checked:
                lines.append("  %s: %s" % (n["id"], n["why"]))
            lines.append("")
        if self.checklist:
            lines.append("To confirm by hand: %d checklist items (listed in out/checklist.md by build, or with "
                         "--json)." % len(self.checklist))
        for note in self.notes:
            lines.append("Note: %s" % note)
        lines.append("Result: %s, %s." % (_plural(len(self.errors), "error"), _plural(len(self.warnings), "warning")))
        return "\n".join(lines) + "\n"


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


# ---------------------------------------------------------------------------------------------------------
# The check

def validate_config(listing, report):
    """Schema validation, then what a schema can't say (the primary locale is a locale, screens named
    elsewhere exist). Returns False when the config can't be checked further."""
    errors = schema.validate(listing.data, load_schema())
    for msg in errors:
        where, _, text = msg.partition(": ")
        report.add(CONFIG_STORE, config_finding("config.schema", where or "(root)", text or msg))
    if errors:
        return False
    data = listing.data
    ok = True
    locs = listing.locale_codes
    if listing.primary not in locs:
        report.add(CONFIG_STORE, config_finding(
            "config.primary_locale", "primaryLocale",
            "%s isn't one of the config's locales (%s)" % (listing.primary, ", ".join(locs) or "none")))
        ok = False
    screens = listing.screens()
    seen = set()
    for i, shot in enumerate(listing.shots()):
        if shot["id"] in seen:
            report.add(CONFIG_STORE, config_finding("config.shots", "screenshots.shots[%d]" % i,
                                                    "the shot id %r is used twice" % shot["id"]))
        seen.add(shot["id"])
        for s in shot.get("screens") or []:
            if s not in screens:
                report.add(CONFIG_STORE, config_finding(
                    "config.screens", "screenshots.shots[%d].screens" % i, "names %r, which isn't in screens" % s))
    for p in listing.apple_platforms() if listing.enabled("apple") else []:
        pconf = listing.store("apple")["platforms"][p]
        for s in pconf.get("screens") or []:
            if s not in screens:
                report.add(CONFIG_STORE, config_finding(
                    "config.screens", "stores.apple.platforms.%s.screens" % p, "names %r, which isn't in screens" % s))
        for s in (pconf.get("previews") or {}):
            if s not in (pconf.get("screens") or []):
                report.add(CONFIG_STORE, config_finding(
                    "config.screens", "stores.apple.platforms.%s.previews" % p,
                    "has previews for %r, which isn't one of the platform's screens" % s))
    if listing.enabled("google"):
        for slot, s in listing.google_slots().items():
            if s not in screens:
                report.add(CONFIG_STORE, config_finding(
                    "config.screens", "stores.google.slots.%s" % slot, "names %r, which isn't in screens" % s))
    for store, key, rid in (("apple", "primaryLocale", "config.primary_locale"),
                            ("google", "defaultLanguage", "config.default_language")):
        if not listing.enabled(store):
            continue
        listed = listing.store(store).get("locales")
        if isinstance(listed, list):
            for i, loc in enumerate(listed):
                if loc not in locs:
                    report.add(CONFIG_STORE, config_finding(
                        "config.locales", "stores.%s.locales[%d]" % (store, i),
                        "%s isn't one of the config's locales (%s)" % (loc, ", ".join(locs))))
        own = listing.store(store).get(key)
        if own and own not in locs:
            report.add(CONFIG_STORE, config_finding(
                rid, "stores.%s.%s" % (store, key), "%s isn't one of the config's locales (%s)" % (own, ", ".join(locs))))
        elif isinstance(listed, list) and listing.store_primary(store) not in listed:
            where = "stores.%s.%s" % (store, key) if own else "primaryLocale"
            report.add(CONFIG_STORE, config_finding(
                rid, where, "%s, %s's primary locale, isn't one of stores.%s.locales (%s): a store's primary must be "
                "one of its locales (set stores.%s.%s)" % (listing.store_primary(store), STORE_NAMES[store], store,
                                                            ", ".join(listed), store, key)))
    if listing.enabled("apple"):
        shipped = listing.apple_platforms()
        for loc in locs:
            for p in listing.platform_overrides(loc):
                if p not in shipped:
                    report.add(CONFIG_STORE, config_finding(
                        "config.platforms", "locales.%s.apple.platforms.%s" % (loc, p),
                        "sets words for %s, which stores.apple.platforms doesn't ship (they're not sent)" % p,
                        "warning"))
    for store in STORES:
        if not listing.enabled(store):
            continue
        for key, rel in _store_files(listing, store):
            if rel and not os.path.isfile(listing.abspath(rel)):
                report.add(CONFIG_STORE, config_finding("config.files", key, "%s doesn't exist" % rel))
    return ok


def _store_files(listing, store):
    """(config path, file) pairs a store's section names, other than the Play graphics (whose absence is a
    store rule's finding)."""
    out = []
    if store == "apple":
        a = listing.store("apple")
        if a.get("tvPrivacyText"):
            out.append(("stores.apple.tvPrivacyText", a["tvPrivacyText"]))
        for p in listing.apple_platforms():
            for screen, items in (a["platforms"][p].get("previews") or {}).items():
                for i, item in enumerate(items):
                    out.append(("stores.apple.platforms.%s.previews.%s[%d]" % (p, screen, i), item.get("file")))
    else:
        g = listing.store("google")
        if g.get("dataSafetyCsv"):
            out.append(("stores.google.dataSafetyCsv", g["dataSafetyCsv"]))
    return out


def store_locales(listing, store, report):
    """``{bcp47: store code}`` for the locales a store gets (``stores.<store>.locales``, else all), its primary
    first; a locale the store doesn't offer (or two that map to one store locale) is an error, and left out."""
    out = collections.OrderedDict()
    taken = {}
    for loc in listing.store_locale_codes(store):
        try:
            code = locales.for_store(store, loc)
        except locales.LocaleError as e:
            report.add(store, config_finding("config.locales", "locales.%s" % loc, str(e)))
            continue
        if code in taken:
            report.add(store, config_finding(
                "config.locales", "locales.%s" % loc,
                "%s and %s would both be %s's %s" % (taken[code], loc, STORE_NAMES[store], code)))
            continue
        taken[code] = loc
        out[loc] = code
    return out


class StoreCheck:
    """One store's check: the rules (relaxed), the locales, the pictures in each slot, and the findings."""

    def __init__(self, listing, store, report):
        self.listing = listing
        self.store = store
        self.report = report
        relax = ((listing.data.get("rules") or {}).get("relax") or [])
        full = rules.load(store, RULES_DIR)
        self.rules = rules.relaxed(full, relax)
        for rule, reason in self.rules.relaxed_rules:
            report.relaxed.append(collections.OrderedDict([("store", store), ("id", rule.id), ("reason", reason)]))
        for rid in self.rules.unknown_relaxed:
            report.add(store, config_finding(
                "config.relax", "rules.relax", "relaxes %s, which isn't one of %s's rules (a typo, or since renamed?)"
                % (rid, store), "warning"))
        self.slots = self.rules.slots
        self.primary = listing.store_primary(store)
        self.locales = store_locales(listing, store, report)
        extra = list((listing.data.get("rules") or {}).get("extraForbiddenWords") or [])
        self.extra_rule = rules.Rule({
            "id": "config.extra_forbidden_words", "kind": "words", "words": extra, "severity": "error",
            "status": "verified"}) if extra else None
        # pictures[(platform, locale)] = OrderedDict(slot -> [Picture]); platform None for Google
        self.pictures = collections.OrderedDict()
        self.unassigned = collections.OrderedDict()  # (platform, locale) -> [Picture] that fit no slot
        self.unreadable = []
        self.missing_shots = []
        self.previews = collections.OrderedDict()   # platform -> [(screen, item, slot or None, why)]

    # -- pictures --------------------------------------------------------------------------------------

    def platform_slots(self, platform):
        """Apple's slots for a platform, in the rules file's order."""
        return [(k, v) for k, v in self.slots.items() if v.get("platform") == platform]

    def assign_apple(self):
        """Put each Apple picture in the first slot of its platform whose sizes fit it."""
        for platform in self.listing.apple_platforms():
            slots = self.platform_slots(platform)
            for loc in self.locales:
                by_slot = collections.OrderedDict()
                unassigned = []
                for screen in self.listing.platform_screens(platform):
                    for shot in self.listing.shots_for("apple", screen):
                        pic = self.listing.picture(loc, screen, shot, "apple")
                        if pic is None:
                            if loc == self.primary:
                                self.missing_shots.append((platform, screen, shot))
                            continue
                        if pic.fell_back:
                            self.report.fallback("apple", loc, "screenshot %s/%s" % (screen, shot), pic.from_locale,
                                                 pic.rel)
                        if pic.info is None:
                            self.unreadable.append(pic)
                            continue
                        for key, slot in slots:
                            if fits(pic.size, slot.get("sizes") or [], slot.get("orientation")):
                                pic.slot = key
                                by_slot.setdefault(key, []).append(pic)
                                break
                        else:
                            unassigned.append(pic)
                self.pictures[(platform, loc)] = by_slot
                self.unassigned[(platform, loc)] = unassigned
            self.assign_previews(platform)

    def assign_previews(self, platform):
        """Each preview goes in the slot its screen's screenshots fill (in the primary locale)."""
        pconf = self.listing.store("apple")["platforms"][platform]
        out = []
        primary_pics = self.pictures.get((platform, self.primary)) or {}
        for screen, items in (pconf.get("previews") or {}).items():
            slots = []
            for key, pics in primary_pics.items():
                if any(p.screen == screen for p in pics) and key not in slots:
                    slots.append(key)
            for item in items:
                if not slots:
                    out.append((screen, item, None, "its screen %r has no screenshots to say which slot it's for"
                                % screen))
                else:
                    out.append((screen, item, slots[0], None))
        self.previews[platform] = out

    def assign_google(self):
        """Put each Play picture in the slot ``stores.google.slots`` names for its screen."""
        for loc in self.locales:
            by_slot = collections.OrderedDict()
            for slot, screen in self.listing.google_slots().items():
                pics = []
                for shot in self.listing.shots_for("google", screen):
                    pic = self.listing.picture(loc, screen, shot, "google")
                    if pic is None:
                        if loc == self.primary:
                            self.missing_shots.append((None, screen, shot))
                        continue
                    if pic.fell_back:
                        self.report.fallback("google", loc, "screenshot %s/%s" % (screen, shot), pic.from_locale,
                                             pic.rel)
                    if pic.info is None:
                        self.unreadable.append(pic)
                        continue
                    pic.slot = slot
                    pics.append(pic)
                by_slot[slot] = pics
            for name in GOOGLE_GRAPHICS:
                pic = self.listing.graphic(name)
                if pic is not None:
                    if pic.info is None:
                        self.unreadable.append(pic)
                    else:
                        by_slot[name] = [pic]
            self.pictures[(None, loc)] = by_slot

    def slots_in_play(self, platform, loc):
        """The slots that count as used: Apple's with pictures in that locale; Play's screenshot slots the
        config fills and the graphics it sets."""
        if self.store == "apple":
            return set(k for k, v in (self.pictures.get((platform, loc)) or {}).items() if v)
        used = set(self.listing.google_slots())
        used |= set(self.listing.google_graphics())
        return used

    def own_pictures(self, platform, loc):
        """True when a locale has a picture of its own (not fallen back) for a platform (or Play)."""
        if loc == self.primary:
            return True
        for pics in (self.pictures.get((platform, loc)) or {}).values():
            if any(p.locale is not None and not p.fell_back for p in pics):
                return True
        return False

    # -- conditions ----------------------------------------------------------------------------------------

    def when(self, rule, platform=None, slots_used=None):
        """Whether a rule's ``when`` holds: True, False, or None when it can't be known offline."""
        cond = rule.get("when") or {}
        unknown = False
        for key, want in cond.items():
            if key == "platform":
                wants = want if isinstance(want, list) else [want]
                if self.store != "apple":
                    ok = False
                elif platform is not None:
                    ok = platform in wants
                else:
                    ok = any(p in wants for p in self.listing.apple_platforms())
            elif key == "screenKind":
                if self.store == "apple":
                    plats = [platform] if platform else self.listing.apple_platforms()
                    ok = any(self.listing.screen_kind(s) == want for p in plats
                             for s in self.listing.platform_screens(p))
                else:
                    ok = any(self.listing.screen_kind(s) == want for s in self.listing.google_slots().values())
            elif key == "slotUsed":
                used = slots_used if slots_used is not None else self.store_slots_used()
                ok = want in used
            elif key == "slotMissing":
                used = slots_used if slots_used is not None else self.store_slots_used()
                ok = want not in used
            elif key == "game":
                ok = self.listing.is_game(self.store) == bool(want)
            else:
                unknown = True
                continue
            if not ok:
                return False
        return None if unknown else True

    def store_slots_used(self):
        """Slots used in the primary locale on any platform (for rules not tied to a slot)."""
        used = set()
        if self.store == "apple":
            for p in self.listing.apple_platforms():
                used |= self.slots_in_play(p, self.primary)
        else:
            used = self.slots_in_play(None, self.primary)
        return used

    def _unknown_why(self, rule):
        keys = [k for k in (rule.get("when") or {}) if k not in ("platform", "screenKind", "slotUsed",
                                                                  "slotMissing", "game")]
        if "update" in keys:
            return ("applies only when this version isn't the app's first, which the config doesn't say "
                    "(push.py plan reads it from the store)")
        return "its condition (%s) can't be decided offline" % ", ".join(keys)

    # -- running -----------------------------------------------------------------------------------------

    def run(self):
        """Run every rule; findings go to the report."""
        if self.store == "apple":
            if not self.listing.apple_platforms():
                self.report.add("apple", config_finding(
                    "config.platforms", "stores.apple.platforms",
                    "no platform is shipped (IOS, MAC_OS, TV_OS and VISION_OS are all null)", "warning"))
            self.assign_apple()
        else:
            self.assign_google()
        self.field_fallbacks()
        for pic in self.unreadable:
            self.report.add(self.store, config_finding("config.files", pic.rel, pic.error))
        folder = (self.listing.data.get("screenshots") or {}).get("folder") or "screenshots"
        grouped = collections.OrderedDict()
        for platform, screen, shot in self.missing_shots:
            grouped.setdefault((platform, screen), []).append(shot)
        for (platform, screen), shots in grouped.items():
            where = "%s/%s/%s/" % (folder, self.primary, screen)
            if platform:
                where = "%s %s" % (platform, where)
            self.report.add(self.store, config_finding(
                "config.screenshots", where, "has no picture for %s %s (.png or .jpg)" % (
                    "shot" if len(shots) == 1 else "shots", ", ".join(shots)), "warning"))
        for rule in self.rules:
            if rule.kind == "checklist":
                if self.when(rule) is not False:
                    self.report.add_checklist(self.store, rule)
                continue
            if rule.slots:
                self.slot_rule(rule)
            elif rule.fields:
                self.field_rule(rule)
        if self.extra_rule is not None:
            self.extra_words()

    def field_fallbacks(self):
        """Report each non-primary locale's store field that took another locale's value (the store's primary's,
        or the config's)."""
        for loc in self.locales:
            if loc == self.primary:
                continue
            for field in STORE_FIELDS[self.store]:
                for value, src, what, _ in self.locale_values(loc, field):
                    if value is not None and src is not None and src != loc:
                        self.report.fallback(self.store, loc, what, src)

    def locale_values(self, loc, field):
        """A locale's value of a field as each store target gets it: ``[(value, source locale, label,
        platforms)]``. One entry, ``platforms`` None, unless the field is an Apple version field whose value
        differs between the shipped platforms: then one entry per distinct value, labelled with its platforms."""
        plats = self.listing.apple_platforms() if self.store == "apple" and field in APPLE_PLATFORM_PATHS else []
        if not plats:
            value, src = self.listing.resolve(loc, field, self.store)
            return [(value, src, field, None)]
        groups = collections.OrderedDict()
        for p in plats:
            value, src = self.listing.resolve(loc, field, self.store, p)
            groups.setdefault(json.dumps(value, sort_keys=True), [value, src, []])[2].append(p)
        if len(groups) == 1:
            value, src, _ = list(groups.values())[0]
            return [(value, src, field, None)]
        return [(v, src, "%s (%s)" % (field, ", ".join(ps)), ps) for v, src, ps in groups.values()]

    # -- field rules --------------------------------------------------------------------------------------

    def field_rule(self, rule):
        """Evaluate a rule on config fields: per locale for a locale's words, once for the root's."""
        cond = self.when(rule)
        if cond is False:
            return
        if cond is None:
            self.report.skip(self.store, rule, self._unknown_why(rule))
            return
        for field in rule.fields:
            if field == "captions":
                continue
            if field.startswith(LOCALE_PREFIXES) or field == "description":
                for loc in self.locales:
                    for value, src, label, plats in self.locale_values(loc, field):
                        if loc != self.primary and src != loc:
                            continue  # the store's primary locale's value: checked there
                        if plats and not any(self.when(rule, p) is not False for p in plats):
                            continue
                        self.evaluate(rule, field, value, "%s %s" % (loc, label), loc)
            else:
                value = self.listing.root_value(field)
                env = self.listing.env_name(field)
                where = "%s (%s)" % (field, env) if env else field
                self.evaluate(rule, field, value, where, None)

    def evaluate(self, rule, field, value, where, loc):
        """Evaluate one rule on one value."""
        kind = rule.kind
        add = self.report.add
        if kind == "required":
            if _missing(value):
                env = self.listing.env_name(field)
                add(self.store, rules.finding(rule, where, "isn't set" + (
                    " (set the environment variable %s)" % env if env else "")))
            elif field == "stores.apple.tvPrivacyText" and not os.path.isfile(self.listing.abspath(value)):
                add(self.store, rules.finding(rule, where, "points at %s, which doesn't exist" % value))
            return
        if value is None:
            return
        if kind == "enum":
            for f in self.check_enum(rule, field, value, where):
                add(self.store, f)
            return
        if kind == "words" and rule.get("wordsFrom"):
            for f in self.check_words_from(rule, value, where, loc):
                add(self.store, f)
            return
        if kind == "count":
            items = value if isinstance(value, list) else [value]
            if rule.get("unique"):
                seen, dups = set(), []
                for item in items:
                    key = str(item).strip().lower()
                    if key in seen and item not in dups:
                        dups.append(item)
                    seen.add(key)
                if dups:
                    add(self.store, rules.finding(rule, where, "repeats %s" % ", ".join('"%s"' % d for d in dups)))
            if rule.get("min") is not None or rule.get("max") is not None:
                for f in rules.evaluate(rule, items, where):
                    add(self.store, f)
            return
        if kind in ("limit", "words", "pattern"):
            if (rule.get("applies") or {}).get("each") and isinstance(value, list):
                for i, item in enumerate(value):
                    for f in rules.evaluate(rule, item, '%s[%d] "%s"' % (where, i, item)):
                        add(self.store, f)
            else:
                for f in rules.evaluate(rule, value, where):
                    add(self.store, f)
            return
        self.report.skip(self.store, rule, "a %s rule on a field isn't something this script checks" % kind)

    def check_enum(self, rule, field, value, where):
        """An ``enum`` rule: values from the rule or a table in the rules file (categories, subcategories by
        their category, the age rating's attributes and their values)."""
        table = rule.get("values")
        if table is None and rule.get("valuesFrom"):
            table = _table(self.rules, rule.get("valuesFrom"))
            if table is None:
                self.report.skip(self.store, rule, "its table %s isn't in the rules file" % rule.get("valuesFrom"))
                return []
        out = []
        if isinstance(table, dict) and isinstance(value, dict) and _is_attribute_table(table):
            for key, v in value.items():
                if key.startswith("$"):
                    continue
                spec = table.get(key)
                if spec is None:
                    out.append(rules.finding(rule, "%s.%s" % (where, key), "isn't one of App Store Connect's "
                                             "attributes (%s…)" % ", ".join(sorted(table)[:4])))
                    continue
                if v is None:
                    continue
                problem = _attribute_problem(spec, v)
                if problem:
                    out.append(rules.finding(rule, "%s.%s" % (where, key), problem))
            return out
        if isinstance(table, dict):
            # subcategories: by the category beside them (primarySubcategories -> primary)
            parent_key = field.rsplit(".", 1)[-1].replace("Subcategories", "")
            parent = self.listing.root_value(field.rsplit(".", 1)[0] + "." + parent_key)
            allowed = table.get(parent) if parent else None
            items = value if isinstance(value, list) else [value]
            for item in items:
                if allowed is None:
                    out.append(rules.finding(rule, where, "%s takes no subcategories (only %s do)" % (
                        parent or "no category", ", ".join(sorted(table)))))
                    break
                if item not in allowed:
                    out.append(rules.finding(rule, where, "%r isn't a subcategory of %s (%s)" % (
                        item, parent, ", ".join(allowed))))
            return out
        items = value if isinstance(value, list) else [value]
        for item in items:
            if item not in (table or []):
                nearest = [t for t in (table or []) if str(t).split("_")[0] == str(item).split("_")[0]]
                hint = " (did you mean %s?)" % ", ".join(nearest[:3]) if nearest else ""
                out.append(rules.finding(rule, where, "%r isn't one the store knows%s" % (item, hint)))
        return out

    def check_words_from(self, rule, value, where, loc):
        """A ``words`` rule whose words are another field's: a field repeating the name's or subtitle's words."""
        words = []
        for other in rule.get("wordsFrom") or []:
            if other.startswith(LOCALE_PREFIXES) or other == "description":
                v = self.listing.resolve(loc or self.primary, other, self.store)[0]
            else:
                v = self.listing.root_value(other)
            if isinstance(v, list):
                v = " ".join(v)
            for w in re.findall(r"\w[\w'’-]*", v or "", re.UNICODE):
                if len(w) >= 3 and w.lower() not in _STOP_WORDS and w.lower() not in [x.lower() for x in words]:
                    words.append(w.lower())
        if not words:
            return []
        own = rules.Rule(dict(rule.data, words=words))
        found = rules.check_words(own, value, where)
        return [f._replace(message=f.message + " (already in %s)" % " or ".join(rule.get("wordsFrom")))
                for f in found]

    def extra_words(self):
        """The config's ``extraForbiddenWords`` in every word field the store sends."""
        for loc in self.locales:
            for field in STORE_FIELDS[self.store]:
                for value, src, label, _ in self.locale_values(loc, field):
                    if value is None or (loc != self.primary and src != loc):
                        continue
                    for f in rules.check_words(self.extra_rule, value, "%s %s" % (loc, label)):
                        self.report.add(self.store, f._replace(message=f.message + " (rules.extraForbiddenWords)"))

    # -- slot rules ------------------------------------------------------------------------------------

    def contexts(self):
        """(platform, locale) pairs whose pictures are checked: each shipped platform (Apple) or Play, in each
        locale with pictures of its own (a locale that only falls back is the primary's, checked there)."""
        plats = self.listing.apple_platforms() if self.store == "apple" else [None]
        out = []
        for p in plats:
            for loc in self.locales:
                if self.own_pictures(p, loc):
                    out.append((p, loc))
        return out

    def slot_rule(self, rule):
        """Evaluate a rule on slots: counts, required slots, sizes, formats and previews."""
        media = (rule.get("applies") or {}).get("media") or "screenshot"
        if media == "preview":
            self.preview_rule(rule)
            return
        kind = rule.kind
        if kind in ("size", "format"):
            self.file_rule(rule)
            return
        if kind not in ("count", "required"):
            self.report.skip(self.store, rule, "a %s rule on slots isn't something this script checks" % kind)
            return
        for platform, loc in self.contexts():
            used = self.slots_in_play(platform, loc)
            cond = self.when(rule, platform, used)
            if cond is False:
                continue
            if cond is None:
                self.report.skip(self.store, rule, self._unknown_why(rule))
                return
            slots = [s for s in rule.slots if self.store != "apple" or (self.slots.get(s) or {}).get(
                "platform") == platform]
            if not slots:
                continue
            pics = self.pictures.get((platform, loc)) or {}
            here = "%s %s" % (loc, platform) if platform else loc
            if kind == "required":
                if not any(pics.get(s) for s in slots):
                    self.report.add(self.store, rules.finding(rule, "%s %s" % (here, "/".join(slots)),
                                                              self._required_message(slots)))
                continue
            # count
            if rule.get("across"):
                n = sum(len(pics.get(s) or []) for s in slots if s in used)
                filled = ", ".join(s for s in slots if s in used)
                where = "%s (%s)" % (here, filled) if filled else "%s stores.google.slots (none filled)" % here
                for f in rules.check_count(rule, n, where, rule.get("noun") or "screenshots"):
                    self.report.add(self.store, f)
                continue
            for s in slots:
                if s not in used:
                    continue
                items = pics.get(s) or []
                noun = rule.get("noun") or "pictures"
                if rule.get("of"):
                    items = [p for p in items if in_range(p.size, rule.get("of"))]
                    noun = "pictures that qualify (%s)" % describe_range(rule.get("of"))
                for f in rules.check_count(rule, len(items), "%s %s" % (here, s), noun):
                    self.report.add(self.store, f)

    def _required_message(self, slots):
        parts = []
        for s in slots:
            slot = self.slots.get(s) or {}
            sizes = slot.get("sizes")
            desc = slot.get("device") or slot.get("imageType") or s
            if sizes:
                parts.append("%s (%s: %s)" % (s, desc, " or ".join(_size_text(x) for x in sizes)))
            else:
                parts.append(s)
        if self.store == "google" and slots[0] in GOOGLE_GRAPHICS:
            name = slots[0]
            sizes = " or ".join(_size_text(x) for x in (self.slots.get(name) or {}).get("sizes") or []) or "picture"
            rel = self.listing.google_graphics().get(name)
            if rel:
                return "%s (stores.google.graphics.%s) doesn't exist: put the %s %s there" % (rel, name, sizes, name)
            return "has no %s: set stores.google.graphics.%s to a %s file" % (name, name, sizes)
        return "has no picture for %s" % (" or ".join(parts))

    def _all_pictures(self, rule):
        """Each picture in the rule's slots, once per file (a file shared by locales is checked once)."""
        seen = set()
        out = []
        for (platform, loc), by_slot in self.pictures.items():
            for slot in rule.slots:
                for pic in by_slot.get(slot) or []:
                    if (pic.path, slot) in seen:
                        continue
                    seen.add((pic.path, slot))
                    out.append((platform, pic))
        return out

    def file_rule(self, rule):
        """``size`` and ``format`` rules, on each file in the rule's slots."""
        if self.when(rule) is False:
            return
        add = self.report.add
        for platform, pic in self._all_pictures(rule):
            if rule.kind == "size":
                for f in self.check_size(rule, pic):
                    add(self.store, f)
            else:
                for f in self.check_format(rule, pic):
                    add(self.store, f)
        if rule.kind == "size" and rule.get("fromSlots") and self.store == "apple":
            seen = set()
            for (platform, loc), pics in self.unassigned.items():
                for pic in pics:
                    if pic.path in seen:
                        continue
                    seen.add(pic.path)
                    add(self.store, rules.finding(rule, pic.rel, self._no_slot_message(platform, pic)))

    def _no_slot_message(self, platform, pic):
        kind = self.listing.screen_kind(pic.screen)
        slots = self.platform_slots(platform)
        same_kind = [(k, v) for k, v in slots if v.get("kind") == kind] or slots
        cands = []
        for key, slot in same_kind:
            for size in accepted_sizes(slot.get("sizes") or [], slot.get("orientation")):
                d = abs(size[0] - pic.size[0]) + abs(size[1] - pic.size[1])
                same_way = (size[0] < size[1]) == (pic.size[0] < pic.size[1])
                cands.append((0 if same_way else 1, d, key, size))
        cands.sort(key=lambda c: (c[0], c[1]))
        nearest = []
        for _, _, key, size in cands:
            label = "%s (%s)" % (_size_text(size), key)
            if label not in nearest:
                nearest.append(label)
            if len(nearest) == 3:
                break
        return ("is %s, which fits no %s screenshot slot; the nearest accepted sizes: %s. Capture or render it "
                "at one of them (don't resize)" % (_size_text(pic.size), platform, ", ".join(nearest)))

    def check_size(self, rule, pic):
        """A ``size`` rule on a picture: exact sizes, a slot's own sizes, or a range."""
        if rule.get("fromSlots"):
            slot = self.slots.get(pic.slot) or {}
            sizes, orientation = slot.get("sizes") or [], slot.get("orientation")
            if fits(pic.size, sizes, orientation):
                return []
            return [rules.finding(rule, pic.rel, "is %s; %s takes %s" % (
                _size_text(pic.size), pic.slot, ", ".join(_size_text(s) for s in accepted_sizes(sizes, orientation))))]
        out = []
        if rule.get("sizes"):
            if not fits(pic.size, rule.get("sizes"), rule.get("orientation")):
                out.append(rules.finding(rule, pic.rel, "is %s; %s must be %s" % (
                    _size_text(pic.size), pic.slot, " or ".join(
                        _size_text(s) for s in accepted_sizes(rule.get("sizes"), rule.get("orientation"))))))
        if rule.get("range"):
            if not in_range(pic.size, rule.get("range")):
                w, h = pic.size
                aspect = max(w, h) / float(min(w, h) or 1)
                out.append(rules.finding(rule, pic.rel, "is %s (long side %.2fx the short); %s needs %s" % (
                    _size_text(pic.size), aspect, pic.slot, describe_range(rule.get("range")))))
        return out

    def check_format(self, rule, pic):
        """A ``format`` rule on a picture: the file format, an alpha channel, see-through pixels, the file size."""
        out = []
        info = pic.info
        if rule.get("formats") and info.format not in rule.get("formats"):
            out.append(rules.finding(rule, pic.rel, "is a %s; %s takes %s" % (
                info.format.upper(), pic.slot, " or ".join(f.upper() for f in rule.get("formats")))))
        if rule.get("alpha") is False and info.has_alpha:
            out.append(rules.finding(rule, pic.rel, "has an alpha channel or transparency, which %s doesn't take: "
                                     "save it without alpha (24-bit PNG or JPEG)" % pic.slot))
        if rule.get("transparency") is False and info.has_alpha:
            try:
                see_through = png.has_transparency(pic.path)
            except png.ImageError:
                see_through = True
            if see_through:
                out.append(rules.finding(rule, pic.rel, "has see-through pixels, which %s shouldn't: make every "
                                         "pixel opaque (an alpha channel itself is fine)" % pic.slot))
        if rule.get("maxBytes") is not None:
            n = os.path.getsize(pic.path)
            if n > rule.get("maxBytes"):
                out.append(rules.finding(rule, pic.rel, "is %d bytes; %s takes at most %d" % (
                    n, pic.slot, rule.get("maxBytes"))))
        return out

    # -- previews (Apple) ------------------------------------------------------------------------------

    def preview_rule(self, rule):
        """Rules on Apple's app previews: counts per slot, and the video's own properties."""
        for platform in self.listing.apple_platforms():
            if self.when(rule, platform) is False:
                continue
            items = self.previews.get(platform) or []
            if rule.kind == "count":
                per_slot = collections.OrderedDict()
                for screen, item, slot, why in items:
                    if slot:
                        per_slot.setdefault(slot, []).append(item)
                for slot, its in per_slot.items():
                    if slot in rule.slots:
                        for f in rules.check_count(rule, len(its), "%s %s previews" % (platform, slot), "previews"):
                            self.report.add(self.store, f)
            elif rule.kind == "video":
                for screen, item, slot, why in items:
                    for f in self.check_video(rule, platform, screen, item, slot, why):
                        self.report.add(self.store, f)
            else:
                self.report.skip(self.store, rule, "a %s rule on previews isn't something this script checks"
                                 % rule.kind)

    def check_video(self, rule, platform, screen, item, slot, why):
        """A ``video`` rule on one preview file (through ffprobe when it's installed)."""
        rel = item.get("file")
        path = self.listing.abspath(rel)
        where = rel
        if not os.path.isfile(path):
            return []  # config.files reports it
        out = []
        if why and rule.get("codecs"):
            out.append(rules.finding(rule, where, "can't be placed: " + why))
        elif slot and (self.slots.get(slot) or {}).get("preview") is None and rule.get("codecs"):
            out.append(rules.finding(rule, where, "%s takes no app previews" % slot))
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if rule.get("containers") and ext not in rule.get("containers"):
            out.append(rules.finding(rule, where, "is a .%s file; previews are %s" % (
                ext, ", ".join("." + c for c in rule.get("containers")))))
        if rule.get("maxBytes") is not None and os.path.getsize(path) > rule.get("maxBytes"):
            out.append(rules.finding(rule, where, "is %d bytes; at most %d" % (
                os.path.getsize(path), rule.get("maxBytes"))))
        needs_probe = any(rule.get(k) is not None for k in ("codecs", "fps", "minSeconds", "maxSeconds")) or \
            rule.get("fromSlots") or rule.get("sizes") or rule.get("audioRequired")
        if not needs_probe:
            return out
        probe = probe_video(path)
        if probe is None:
            if rule.get("codecs"):  # say it once a file, on the main video rule
                out.append(rules.Finding(rule.id, "warning", where,
                                         "the video's codec, frame rate, length, size and audio weren't checked: "
                                         "ffprobe isn't installed (install ffmpeg, or set FFPROBE)",
                                         rule.source, rule.status))
            return out
        if isinstance(probe, str):
            out.append(rules.finding(rule, where, "ffprobe couldn't read it: %s" % probe))
            return out
        if rule.get("codecs") and probe.get("codec") not in rule.get("codecs"):
            out.append(rules.finding(rule, where, "is %s; previews are %s" % (
                probe.get("codec") or "an unknown codec", " or ".join(rule.get("codecs")))))
        if rule.get("fps") is not None and probe.get("fps") and probe["fps"] > rule.get("fps") + 0.01:
            out.append(rules.finding(rule, where, "runs at %.2f fps; at most %g" % (probe["fps"], rule.get("fps"))))
        secs = probe.get("seconds")
        if secs is not None:
            if rule.get("minSeconds") is not None and secs < rule.get("minSeconds") - 0.05:
                out.append(rules.finding(rule, where, "is %.1f s long; at least %g s" % (secs, rule.get("minSeconds"))))
            if rule.get("maxSeconds") is not None and secs > rule.get("maxSeconds") + 0.05:
                out.append(rules.finding(rule, where, "is %.1f s long; at most %g s" % (secs, rule.get("maxSeconds"))))
        size = probe.get("size")
        if size and slot:
            if rule.get("fromSlots"):
                prev = (self.slots.get(slot) or {}).get("preview") or {}
                sizes, orientation = prev.get("sizes") or [], prev.get("orientation")
            else:
                sizes, orientation = rule.get("sizes") or [], rule.get("orientation")
            if sizes and not fits(size, sizes, orientation):
                out.append(rules.finding(rule, where, "is %s; %s previews are %s" % (
                    _size_text(size), slot, ", ".join(_size_text(s) for s in accepted_sizes(sizes, orientation)))))
        if rule.get("audioRequired") and not probe.get("audio"):
            out.append(rules.finding(rule, where, "has no audio track"))
        return out


_STOP_WORDS = frozenset(["and", "the", "for", "with", "you", "your", "our", "app", "der", "die", "das", "und",
                         "les", "des", "une", "con", "por", "para"])


def _table(ruleset_or_none, dotted):
    """A table from the rules file by a dotted path (``categories.primary``)."""
    path = os.path.join(RULES_DIR, "%s.json" % ruleset_or_none.store)
    node = _rules_json(path)
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


_RULES_JSON = {}


def _rules_json(path):
    if path not in _RULES_JSON:
        _RULES_JSON[path] = jsonio.load(path)
    return _RULES_JSON[path]


def _is_attribute_table(table):
    return all(isinstance(v, dict) and "type" in v for k, v in table.items() if not k.startswith("$"))


def _attribute_problem(spec, value):
    kind = spec.get("type")
    if kind == "boolean":
        return None if isinstance(value, bool) else "is %r; it takes true or false" % (value,)
    if kind == "uri":
        return None if isinstance(value, str) and re.match(r"^https?://\S+$", value) else "isn't a URL"
    if not isinstance(value, str):
        return "is %r; it takes text" % (value,)
    if spec.get("values") and value not in spec["values"]:
        return "is %r; it takes %s" % (value, ", ".join(spec["values"]))
    return None


def find_ffprobe():
    """ffprobe's path (``$FFPROBE``, then ``PATH``), or None."""
    env = os.environ.get("FFPROBE")
    if env:
        return env if os.path.isfile(env) else None
    return shutil.which("ffprobe")


def probe_video(path):
    """A video's properties through ffprobe: ``{codec, fps, seconds, size, audio}``; None when ffprobe isn't
    installed; a message when it can't read the file."""
    exe = find_ffprobe()
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    if proc.returncode != 0:
        return proc.stderr.decode("utf-8", "replace").strip() or "exit %d" % proc.returncode
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except ValueError:
        return "its output wasn't JSON"
    return parse_probe(data)


def parse_probe(data):
    """Turn ffprobe's JSON into ``{codec, fps, seconds, size, audio}``."""
    video = None
    audio = False
    for s in data.get("streams") or []:
        if s.get("codec_type") == "video" and video is None:
            video = s
        elif s.get("codec_type") == "audio":
            audio = True
    out = {"codec": None, "fps": None, "seconds": None, "size": None, "audio": audio}
    if video:
        out["codec"] = video.get("codec_name")
        for key in ("avg_frame_rate", "r_frame_rate"):
            rate = video.get(key)
            if rate and "/" in rate:
                num, den = rate.split("/", 1)
                try:
                    if float(den):
                        out["fps"] = float(num) / float(den)
                        break
                except ValueError:
                    pass
        if video.get("width") and video.get("height"):
            out["size"] = (int(video["width"]), int(video["height"]))
    dur = (data.get("format") or {}).get("duration") or (video or {}).get("duration")
    try:
        out["seconds"] = float(dur) if dur is not None else None
    except ValueError:
        pass
    return out


def run_check(config_path, stores=None):
    """Check a config. Returns ``(report, listing, checks)``: the report, the loaded config (None when it
    doesn't load) and each store's ``StoreCheck`` (for the build). Raises ``UsageError`` for a missing
    config or an unknown store."""
    report = Report(config_path)
    listing = load_listing(config_path)
    report.config_path = os.path.relpath(listing.path)
    if stores:
        unknown = [s for s in stores if s not in STORES + LATER_STORES]
        if unknown:
            raise UsageError("unknown store %s (apple, google)" % ", ".join(unknown))
    if not validate_config(listing, report):
        return report, listing, {}
    wanted = [s for s in (stores or STORES)]
    checks = collections.OrderedDict()
    for store in wanted:
        if store in LATER_STORES:
            if listing.enabled(store) or stores:
                report.notes.append("%s has no rules data or listing API here yet: its checklist is in "
                                    "references/sending.md" % STORE_NAMES[store])
            continue
        if not listing.enabled(store):
            if stores:
                report.notes.append("%s isn't enabled in the config (stores.%s.enabled): not checked"
                                    % (STORE_NAMES[store], store))
            continue
        report.stores.append(store)
        check = StoreCheck(listing, store, report)
        check.run()
        checks[store] = check
    if not report.stores:
        report.notes.append("no store is enabled: set stores.apple.enabled or stores.google.enabled")
    for store in LATER_STORES:
        if not stores and listing.enabled(store):
            report.notes.append("%s is enabled; it has no listing API here: its checklist is in "
                                "references/sending.md" % STORE_NAMES[store])
    return report, listing, checks


def cmd_check(args):
    """``listing.py check``."""
    stores = [s.strip() for s in args.stores.split(",") if s.strip()] if args.stores else None
    try:
        report, _, _ = run_check(args.config, stores)
    except jsonio.JsonError as e:
        report = Report(args.config)
        report.add(CONFIG_STORE, config_finding("config.json", args.config, str(e)))
    if args.json:
        sys.stdout.write(jsonio.dumps(report.to_json()))
    else:
        sys.stdout.write(report.to_text())
    return EXIT_ERRORS if report.errors else EXIT_OK


# ---------------------------------------------------------------------------------------------------------
# The build

OUT_PARTS = ("apple", "google", "listing.json", "checklist.md")


def _prepare_out(out):
    """Make ``out`` ready for a build: remove the last build's files (only where ``out/listing.json`` shows
    it's a build folder), never anything else."""
    if os.path.isdir(out):
        ours = os.path.isfile(os.path.join(out, "listing.json"))
        clash = [p for p in ("apple", "google") if os.path.exists(os.path.join(out, p))]
        if clash and not ours:
            raise UsageError("%s has %s but no listing.json: it doesn't look like a build folder, so nothing in it "
                             "was replaced (pass another --out)" % (out, " and ".join(clash)))
        for part in OUT_PARTS:
            p = os.path.join(out, part)
            if os.path.isdir(p):
                shutil.rmtree(p)
            elif os.path.isfile(p):
                os.unlink(p)
    os.makedirs(out, exist_ok=True)


def _write_text(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(value)


def _file_entry(out, path):
    """``{file, md5, sha256, size}`` for a file in ``out``."""
    return collections.OrderedDict([
        ("file", os.path.relpath(path, out).replace(os.sep, "/")),
        ("md5", png.md5(path)), ("sha256", png.sha256(path)), ("size", os.path.getsize(path))])


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def _picture_ext(pic):
    if pic.info is not None:
        return ".png" if pic.info.format == "png" else ".jpg"
    return os.path.splitext(pic.path)[1].lower()


def _keywords(value):
    if value is None:
        return None
    if isinstance(value, list):
        return ",".join(v.strip() for v in value)
    return value


# The environment variables holding each store's key (their names only; never their values).
APPLE_AUTH = (("keyIdEnv", "ASC_KEY_ID"), ("issuerIdEnv", "ASC_ISSUER_ID"), ("privateKeyEnv", "ASC_PRIVATE_KEY"))
GOOGLE_AUTH = (("serviceAccountEnv", "GOOGLE_PLAY_SERVICE_ACCOUNT"),)


def _auth(section, defaults):
    """A store's ``auth`` for the manifest: the config's variable names, else the defaults."""
    given = section.get("auth") or {}
    return collections.OrderedDict((key, given.get(key) or default) for key, default in defaults)


def build_apple(listing, check, out):
    """Write ``out/apple/…`` (fastlane deliver's layout) and return the manifest's ``apple`` section."""
    a = listing.store("apple")
    ids = (listing.data.get("app") or {}).get("ids") or {}
    app = listing.data.get("app") or {}
    urls = app.get("urls") or {}
    cats = a.get("categories") or {}
    by_code = check.locales
    manifest = collections.OrderedDict()
    manifest["appId"] = (ids.get("apple") or {}).get("appId")
    manifest["bundleId"] = (ids.get("apple") or {}).get("bundleId")
    manifest["primaryLocale"] = by_code.get(check.primary)
    age = collections.OrderedDict((k, v) for k, v in (a.get("ageRating") or {}).items() if not k.startswith("$"))
    app_locs = collections.OrderedDict()
    for loc, code in by_code.items():
        app_locs[code] = collections.OrderedDict([
            ("name", listing.resolve(loc, "apple.name")[0]),
            ("subtitle", listing.resolve(loc, "apple.subtitle")[0]),
            ("privacyPolicyUrl", urls.get("privacy")),
            ("privacyChoicesUrl", urls.get("privacyChoices")),
        ])
    manifest["app"] = collections.OrderedDict([
        ("categories", collections.OrderedDict([
            ("primary", cats.get("primary")), ("primarySubcategories", list(cats.get("primarySubcategories") or [])),
            ("secondary", cats.get("secondary")),
            ("secondarySubcategories", list(cats.get("secondarySubcategories") or []))])),
        ("ageRating", age),
        ("copyright", app.get("copyright")),
        ("localizations", app_locs),
    ])
    platforms = collections.OrderedDict()
    web_only = []
    tv_text = None
    if a.get("tvPrivacyText") and os.path.isfile(listing.abspath(a["tvPrivacyText"])):
        with open(listing.abspath(a["tvPrivacyText"]), encoding="utf-8") as f:
            tv_text = f.read().strip()
        # One file today, so it's the store's primary locale's (Apple TV shows the text, not a link)
        primary_code = by_code.get(check.primary)
        if primary_code in app_locs:
            app_locs[primary_code]["privacyPolicyText"] = tv_text
    for platform in listing.apple_platforms():
        base = os.path.join(out, "apple", platform)
        meta = os.path.join(base, "metadata")
        locs = collections.OrderedDict()
        shots = collections.OrderedDict()
        for loc, code in by_code.items():
            # The version's words are this platform's: its override, else the locale's (decision: per platform)
            words = collections.OrderedDict(
                (f, listing.resolve(loc, "apple." + f, "apple", platform)[0]) for f in APPLE_PLATFORM_FIELDS)
            words["keywords"] = _keywords(words["keywords"])
            locs[code] = words
            files = [("name", app_locs[code]["name"]), ("subtitle", app_locs[code]["subtitle"]),
                     ("description", words["description"]), ("keywords", words["keywords"]),
                     ("promotional_text", words["promotionalText"]), ("release_notes", words["whatsNew"]),
                     ("marketing_url", words["marketingUrl"]), ("support_url", words["supportUrl"]),
                     ("privacy_url", urls.get("privacy"))]
            if platform == "TV_OS" and tv_text is not None:
                files.append(("apple_tv_privacy_policy", tv_text))
            for name, value in files:
                if value is not None:
                    _write_text(os.path.join(meta, code, name + ".txt"), value)
            per_slot = collections.OrderedDict()
            for slot, pics in (check.pictures.get((platform, loc)) or {}).items():
                display = (check.slots.get(slot) or {}).get("displayType")
                if not display:
                    for pic in pics:
                        web_only.append((platform, code, slot, pic.rel))
                    continue
                entries = []
                for i, pic in enumerate(pics, 1):
                    dst = os.path.join(base, "screenshots", code, "%02d_%s_%s%s" % (i, display, pic.shot,
                                                                                     _picture_ext(pic)))
                    _copy(pic.path, dst)
                    entries.append(_file_entry(out, dst))
                if entries:
                    per_slot[display] = entries
            shots[code] = per_slot
        for name, value in (("copyright", app.get("copyright")), ("primary_category", cats.get("primary")),
                            ("secondary_category", cats.get("secondary"))):
            if value is not None:
                _write_text(os.path.join(meta, name + ".txt"), value)
        for which in ("primary", "secondary"):
            for n, sub in zip(("first", "second"), cats.get(which + "Subcategories") or []):
                _write_text(os.path.join(meta, "%s_%s_sub_category.txt" % (which, n)), sub)
        notes = (a.get("review") or {}).get("notes")
        if notes is not None:
            _write_text(os.path.join(meta, "review_information", "notes.txt"), notes)
        previews = collections.OrderedDict()
        copied = {}
        counts = collections.Counter()
        for screen, item, slot, why in check.previews.get(platform) or []:
            ptype = (((check.slots.get(slot) or {}).get("preview")) or {}).get("type") if slot else None
            src = listing.abspath(item["file"])
            if not ptype or not os.path.isfile(src):
                continue
            if src not in copied:
                counts[ptype] += 1
                ext = os.path.splitext(src)[1].lower()
                dst = os.path.join(base, "app_previews", "%02d_%s_%s%s" % (counts[ptype], ptype, screen, ext))
                _copy(src, dst)
                copied[src] = dst
            dst = copied[src]
            entry = _file_entry(out, dst)
            entry["posterFrame"] = item.get("posterFrame")
            entry["mime"] = VIDEO_MIME.get(os.path.splitext(dst)[1].lower(), "application/octet-stream")
            for code in by_code.values():
                previews.setdefault(code, collections.OrderedDict()).setdefault(ptype, []).append(entry)
        platforms[platform] = collections.OrderedDict([
            ("localizations", locs), ("screenshots", shots), ("previews", previews)])
    manifest["platforms"] = platforms
    review = a.get("review") or {}
    manifest["review"] = collections.OrderedDict([
        ("notes", review.get("notes")),
        ("contact", collections.OrderedDict(sorted((review.get("contact") or {}).items()))),
        ("demoAccount", review.get("demoAccount")),  # null: no demo account needed; else env names
    ])
    manifest["auth"] = _auth(a, APPLE_AUTH)
    return manifest, web_only


def _developer(app):
    """Who the app is by, for the preview: the copyright's holder (``2026 Example Studio``), else the app's name."""
    holder = re.sub(r"^\s*(©|\(c\))?\s*\d{4}(\s*[-–]\s*\d{4})?\s*,?\s*", "", app.get("copyright") or "").strip()
    return holder or app.get("name")


def build_google(listing, check, out):
    """Write ``out/google/…`` (fastlane supply's layout) and return the manifest's ``google`` section."""
    g = listing.store("google")
    app = listing.data.get("app") or {}
    ids = app.get("ids") or {}
    contact = app.get("contact") or {}
    by_code = check.locales
    manifest = collections.OrderedDict()
    manifest["package"] = (ids.get("google") or {}).get("package")
    manifest["defaultLanguage"] = by_code.get(check.primary)
    manifest["details"] = collections.OrderedDict([
        ("contactEmail", contact.get("email")), ("contactWebsite", contact.get("website")),
        ("contactPhone", contact.get("phone"))])
    # Shown by the preview only (Play's developer name is the account's, never sent): the copyright's owner.
    manifest["developer"] = _developer(app)
    listings = collections.OrderedDict()
    images = collections.OrderedDict()
    meta = os.path.join(out, "google", "metadata", "android")
    for loc, code in by_code.items():
        video = listing.resolve(loc, "google.video")[0]
        words = collections.OrderedDict([
            ("title", listing.resolve(loc, "google.title")[0]),
            ("shortDescription", listing.resolve(loc, "google.shortDescription")[0]),
            ("fullDescription", listing.resolve(loc, "google.fullDescription")[0]),
            ("video", video),  # null leaves Play's as it is; "" clears it
        ])
        listings[code] = words
        for name, key in (("title", "title"), ("short_description", "shortDescription"),
                          ("full_description", "fullDescription"), ("video", "video")):
            if words[key] is not None:
                _write_text(os.path.join(meta, code, name + ".txt"), words[key])
        per_type = collections.OrderedDict()
        for slot, pics in (check.pictures.get((None, loc)) or {}).items():
            image_type = (check.slots.get(slot) or {}).get("imageType") or slot
            entries = []
            for i, pic in enumerate(pics, 1):
                if slot in GOOGLE_GRAPHICS:
                    dst = os.path.join(meta, code, "images", image_type + _picture_ext(pic))
                else:
                    dst = os.path.join(meta, code, "images", image_type, "%02d_%s%s" % (i, pic.shot, _picture_ext(pic)))
                _copy(pic.path, dst)
                entries.append(_file_entry(out, dst))
            if entries:
                per_type[image_type] = entries
        images[code] = per_type
    manifest["listings"] = listings
    manifest["images"] = images
    csv = g.get("dataSafetyCsv")
    if csv and os.path.isfile(listing.abspath(csv)):
        dst = os.path.join(out, "google", "dataSafety.csv")
        _copy(listing.abspath(csv), dst)
        manifest["dataSafetyCsv"] = os.path.relpath(dst, out).replace(os.sep, "/")
    else:
        manifest["dataSafetyCsv"] = None
    manifest["auth"] = _auth(g, GOOGLE_AUTH)
    return manifest


# Forms with no API, per store (references/apple.md, google.md, forms.md).
NO_API = {
    "apple": [
        "App Privacy (the privacy \"nutrition label\"): App Store Connect > App Privacy",
        "Price and availability",
        "EU trader status (Digital Services Act): without it the app leaves EU storefronts",
        "Content rights",
        "Regulated medical device declaration (Health & Fitness or Medical apps in the EU, UK and US)",
        "Made for Kids (can't be undone once approved)",
        "Submitting the version for review",
    ],
    "google": [
        "Content rating (IARC questionnaire)",
        "Target audience and content",
        "Ads declaration",
        "Sign-in details (formerly App access)",
        "The other App content declarations (health, financial features, government apps, permissions)",
        "Category and up to five tags (Store settings)",
        "Feature graphic alt text (Main store listing)",
    ],
}


def _forms_for(forms, store):
    out = collections.OrderedDict()
    for key, value in (forms or {}).items():
        if key.startswith("$"):
            continue
        k = key.lower()
        if store == "apple" and k.startswith("apple"):
            out[key] = value
        elif store == "google" and (k.startswith("google") or k.startswith("play")):
            out[key] = value
        elif store == "other" and not (k.startswith("apple") or k.startswith("google") or k.startswith("play")):
            out[key] = value
    return out


def _form_lines(forms):
    lines = []
    for key, value in forms.items():
        if isinstance(value, (dict, list)):
            lines.append("- `%s`:" % key)
            lines.append("")
            lines.append("  ```json")
            for row in json.dumps(value, indent=2, ensure_ascii=False).splitlines():
                lines.append("  " + row)
            lines.append("  ```")
            lines.append("")
        else:
            lines.append("- `%s`: %s" % (key, value))
    return lines


def build_checklist(listing, report, web_only, stores):
    """``out/checklist.md``: every checklist rule, the forms with no API with the config's drafted answers,
    and what has to be done by hand."""
    lines = ["# Checklist: what no API sends", "",
             "Built from `%s`. Nothing here was sent or changed by a script: tick each item by hand. A form's "
             "drafted answers (the config's `forms`) are drafts until the user confirms them." %
             os.path.basename(listing.path), ""]
    forms = listing.data.get("forms") or {}
    for store in stores:
        lines.append("## %s" % STORE_NAMES[store])
        lines.append("")
        items = [c for c in report.checklist if c["store"] == store]
        if items:
            lines.append("### Confirm by looking")
            lines.append("")
            for c in items:
                status = "" if c["status"] == "verified" else " (%s)" % c["status"]
                src = " ([source](%s), checked %s)" % (c["source"], c["checked"]) if c.get("source") else ""
                lines.append("- [ ] %s `%s`%s%s" % (c["item"], c["id"], status, src))
            lines.append("")
        lines.append("### Forms with no API: change them in %s" % (
            "App Store Connect" if store == "apple" else "Play Console"))
        lines.append("")
        for item in NO_API[store]:
            lines.append("- [ ] %s" % item)
        lines.append("")
        if store == "google":
            alt = []
            for loc in report_locales(listing, store):
                v = listing.resolve(loc, "altText.featureGraphic")[0]
                if v:
                    alt.append("  - %s: \"%s\"" % (loc, v))
            if alt:
                lines.append("Feature graphic alt text to enter, per language:")
                lines.append("")
                lines.extend(alt)
                lines.append("")
            cat = listing.store("google").get("category")
            if cat:
                lines.append("Category to choose: `%s`." % cat)
                lines.append("")
        if store == "apple" and web_only:
            lines.append("### Upload by hand (no API display type yet)")
            lines.append("")
            for platform, code, slot, rel in web_only:
                lines.append("- [ ] %s %s %s: `%s`" % (platform, code, slot, rel))
            lines.append("")
        mine = _forms_for(forms, store)
        lines.append("### Drafted answers")
        lines.append("")
        if mine:
            lines.extend(_form_lines(mine))
        else:
            lines.append("None in the config's `forms` yet (see references/forms.md).")
        lines.append("")
    other = _forms_for(forms, "other")
    if other:
        lines.append("## Other drafted answers")
        lines.append("")
        lines.extend(_form_lines(other))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def report_locales(listing, store):
    """The locales a store gets (its primary first)."""
    return listing.store_locale_codes(store)


def run_build(config_path, out, now=None):
    """Check, then build ``out``. Returns ``(report, manifest or None)``."""
    report, listing, checks = run_check(config_path)
    if report.errors:
        return report, None
    _prepare_out(out)
    manifest = collections.OrderedDict()
    manifest["version"] = 1
    stamp = now or datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    manifest["builtAt"] = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest["config"] = os.path.relpath(listing.path, os.path.dirname(os.path.abspath(out))).replace(os.sep, "/")
    web_only = []
    if "apple" in checks:
        manifest["apple"], web_only = build_apple(listing, checks["apple"], out)
    if "google" in checks:
        manifest["google"] = build_google(listing, checks["google"], out)
    jsonio.dump(manifest, os.path.join(out, "listing.json"))
    _write_text(os.path.join(out, "checklist.md"), build_checklist(listing, report, web_only, list(checks)))
    return report, manifest


def cmd_build(args):
    """``listing.py build``."""
    try:
        report, manifest = run_build(args.config, args.out)
    except jsonio.JsonError as e:
        sys.stdout.write("Config error: %s\n" % e)
        return EXIT_ERRORS
    sys.stdout.write(report.to_text())
    if manifest is None:
        sys.stdout.write("Not built: fix the errors above (the config, the words or the pictures; not the rules), "
                         "then build again.\n")
        return EXIT_ERRORS
    n = 0
    for part in OUT_PARTS:
        p = os.path.join(args.out, part)
        if os.path.isfile(p):
            n += 1
        for _, _, files in os.walk(p):
            n += len(files)
    sys.stdout.write("Built %s: %s, listing.json and checklist.md (%d files).\n" % (
        args.out, " and ".join(STORE_NAMES[s] for s in ("apple", "google") if s in manifest), n))
    return EXIT_OK


# ---------------------------------------------------------------------------------------------------------
# The command line

def cmd_preview(args):
    """``listing.py preview``."""
    import listing_preview
    return listing_preview.main(args)


def cmd_diff(args):
    """``listing.py diff``."""
    import listing_live
    return listing_live.cmd_diff(args)


def cmd_import(args):
    """``listing.py import``."""
    import listing_import
    return listing_import.main(args)


def parser():
    """The argument parser."""
    p = argparse.ArgumentParser(prog="listing.py", description="Check, build, preview and import a store listing "
                                "(store-listing.json). Offline: nothing here reaches a network.")
    sub = p.add_subparsers(dest="command")
    imp = sub.add_parser("import", help="start or extend a config from fastlane, supply, Triple-T or Expo metadata")
    imp.add_argument("--from", dest="source", required=True, choices=("fastlane", "supply", "triple-t", "expo", "live"))
    imp.add_argument("path", help="the metadata folder (Expo's store.config.json; for live, what push.py pull wrote: "
                                  "existing/)")
    imp.add_argument("--out", default="store-listing.json", help="the config to write or merge into")
    imp.add_argument("--platform", choices=APPLE_PLATFORMS,
                     help="fastlane only: the Apple platform the folder is for (default: what its screenshots fit, "
                          "else IOS)")
    chk = sub.add_parser("check", help="check the config against each enabled store's rules")
    chk.add_argument("--config", default="store-listing.json")
    chk.add_argument("--stores", help="comma-separated: apple,google (default: every enabled store)")
    chk.add_argument("--json", action="store_true", help="print the findings as JSON")
    bld = sub.add_parser("build", help="check, then write out/ (fastlane layouts, listing.json, checklist.md)")
    bld.add_argument("--config", default="store-listing.json")
    bld.add_argument("--out", default="out")
    dif = sub.add_parser("diff", help="the config's words and picture counts against what push.py pull read")
    dif.add_argument("--config", default="store-listing.json")
    dif.add_argument("--existing", default="existing", help="what push.py pull wrote (default: existing)")
    dif.add_argument("--stores", help="comma-separated: apple,google (default: every store pulled)")
    dif.add_argument("--json", action="store_true", help="print the entries as JSON")
    prv = sub.add_parser("preview", help="draw each store's page from out/ as HTML (and PNG with --png)")
    prv.add_argument("--config", default="store-listing.json", help="(unused unless out/ has no build)")
    prv.add_argument("--out", default="out")
    prv.add_argument("--png", action="store_true", help="render the pages to PNG through headless Chrome")
    return p


def main(argv=None):
    """Run a subcommand; return its exit code."""
    p = parser()
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return EXIT_OK if e.code in (0, None) else EXIT_USAGE
    if not args.command:
        p.print_help()
        return EXIT_USAGE
    handler = {"import": cmd_import, "check": cmd_check, "build": cmd_build, "preview": cmd_preview,
               "diff": cmd_diff}[args.command]
    try:
        return handler(args)
    except UsageError as e:
        sys.stderr.write("listing.py %s: %s\n" % (args.command, e))
        return EXIT_USAGE
    except rules.RulesError as e:
        sys.stderr.write("listing.py %s: the rules data is broken: %s\n" % (args.command, e))
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
