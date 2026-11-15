"""``listing.py import``: start or extend ``store-listing.json`` from metadata a project already keeps.

Sources (``references/importing.md``):

- ``fastlane``: fastlane ``deliver``'s ``metadata/`` (and ``screenshots/``) for the App Store.
- ``supply``: fastlane ``supply``'s ``metadata/android/`` for Google Play.
- ``triple-t``: Gradle Play Publisher's ``play/`` folder for Google Play.
- ``expo``: Expo's ``store.config.json`` (EAS Metadata) for the App Store.
- ``live``: what ``push.py pull`` read from the stores into ``existing/<store>/`` (``references/existing.md``).

Running it again into the same config merges: a value the config already has (not null) is never
overwritten, and the import says what it took and what it kept. App Review's contact details and demo
account (fastlane's ``review_information``, Expo's ``apple.review``) are never copied: the config names
environment variables instead, and the import says which to set.
"""

from __future__ import annotations

import collections
import filecmp
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appstores_lib import jsonio  # noqa: E402
from appstores_lib import locales  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import rules  # noqa: E402

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_DIR = os.path.join(os.path.dirname(SCRIPTS_DIR), "rules")
PICTURE_EXTS = (".png", ".jpg", ".jpeg")

REVIEW_ENV = collections.OrderedDict([
    ("firstNameEnv", "APPLE_REVIEW_FIRST_NAME"), ("lastNameEnv", "APPLE_REVIEW_LAST_NAME"),
    ("phoneEnv", "APPLE_REVIEW_PHONE"), ("emailEnv", "APPLE_REVIEW_EMAIL")])
DEMO_ENV = collections.OrderedDict([("usernameEnv", "APPLE_REVIEW_DEMO_USER"),
                                    ("passwordEnv", "APPLE_REVIEW_DEMO_PASSWORD")])

# fastlane supply's image folders and Triple-T's graphics folders -> (Play slot, our screen name, screen kind)
SUPPLY_SCREENSHOTS = collections.OrderedDict([
    ("phoneScreenshots", ("phone", "android-phone", "phone")),
    ("sevenInchScreenshots", ("tablet7", "android-tablet7", "tablet")),
    ("tenInchScreenshots", ("tablet10", "android-tablet10", "tablet")),
    ("tvScreenshots", ("tv", "android-tv", "tv")),
    ("wearScreenshots", ("wear", "android-wear", "watch")),
])
TRIPLE_T_SCREENSHOTS = collections.OrderedDict([
    ("phone-screenshots", "phoneScreenshots"), ("tablet-screenshots", "sevenInchScreenshots"),
    ("large-tablet-screenshots", "tenInchScreenshots"), ("tv-screenshots", "tvScreenshots"),
    ("wear-screenshots", "wearScreenshots"),
])
SUPPLY_GRAPHICS = ("icon", "featureGraphic", "tvBanner")
TRIPLE_T_GRAPHICS = collections.OrderedDict([("icon", "icon"), ("feature-graphic", "featureGraphic"),
                                             ("tv-banner", "tvBanner")])

FASTLANE_FIELDS = collections.OrderedDict([
    ("name", ("apple", "name")), ("subtitle", ("apple", "subtitle")), ("description", ("apple", "description")),
    ("keywords", ("apple", "keywords")), ("promotional_text", ("apple", "promotionalText")),
    ("release_notes", ("apple", "whatsNew")),
])
FASTLANE_URLS = collections.OrderedDict([("marketing_url", "marketing"), ("support_url", "support"),
                                         ("privacy_url", "privacy")])
FASTLANE_PERSONAL = ("review_information", "trade_representative_contact_information")


# Words in a picture's file name that say which device or size it's for, not which moment it shows
DEVICE_WORDS = frozenset([
    "iphone", "ipad", "ipadpro", "mac", "macos", "macbook", "desktop", "appletv", "tvos", "tv", "vision",
    "visionpro", "visionos", "watch", "watchos", "android", "phone", "tablet", "tablet7", "tablet10", "wear",
    "chromebook", "apple", "landscape", "portrait"])
GENERIC_WORDS = frozenset(["screenshot", "screenshots", "screen", "shot", "image", "img", "picture", "pic", "frame",
                           "capture", "untitled", "copy", "at"])
DEVICE_MODIFIERS = frozenset([
    "pro", "max", "plus", "mini", "ultra", "air", "se", "xl", "xs", "xr", "inch", "in", "gen", "generation",
    "series", "seven", "ten", "large", "small"])


def shot_id_from_name(filename, locale=None, display_types=()):
    """The moment a picture's file name says it shows, as a shot id: the order number, the device or size and
    the locale taken off (``01-check-close-iphone.jpg`` -> ``check-close``, ``03_APP_IPHONE_67_plan.png`` ->
    ``plan``, ``iPhone 15 Pro Max-01_home.png`` -> ``home``). None when nothing's left that names a moment."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    for code in sorted(display_types, key=len, reverse=True):
        stem = re.sub(r"(?i)(^|[^A-Za-z0-9])%s(?=$|[^A-Za-z0-9])" % re.escape(code), r"\1-", stem)
    tokens = [t for t in re.split(r"[^a-z0-9]+", stem.lower()) if t]

    def device_run(seq):
        """How many tokens at the start of ``seq`` are a device and its model words (0 if it doesn't start with
        a device word)."""
        if not seq or seq[0] not in DEVICE_WORDS:
            return 0
        n = 1
        while n < len(seq) and (seq[n] in DEVICE_WORDS or seq[n] in DEVICE_MODIFIERS
                                or re.match(r"^\d+(st|nd|rd|th|mm|k)?$", seq[n])):
            n += 1
        return n

    numbered = False
    while tokens:  # the front: fastlane snapshot's device and model ("iPhone 15 Pro Max-"), order numbers
        n = 0 if numbered else device_run(tokens)
        if n and n < len(tokens):
            tokens = tokens[n:]
        elif tokens[0].isdigit():
            numbered = True
            tokens = tokens[1:]
        else:
            break
    loc = [t for t in re.split(r"[^a-z0-9]+", (locale or "").lower()) if t]
    while tokens:  # the end: a size, the locale, a device and its model, a number after the device
        if re.match(r"^\d+x\d+$", tokens[-1]):
            tokens = tokens[:-1]
        elif loc and tokens[-len(loc):] == loc:
            tokens = tokens[:-len(loc)]
        else:
            for i in range(len(tokens) - 1, 0, -1):
                if tokens[i] in DEVICE_WORDS and device_run(tokens[i:]) == len(tokens) - i:
                    while i > 1 and tokens[i - 1] in DEVICE_WORDS:
                        i -= 1
                    tokens = tokens[:i]
                    break
            else:
                break
    if not tokens or all(t.isdigit() or t in GENERIC_WORDS for t in tokens) or device_run(tokens) == len(tokens):
        return None
    return "-".join(tokens)


def shot_ids(files, locale=None, display_types=()):
    """Shot ids for a folder's pictures, in order: from their names when every one names a different moment,
    else ``shot-01``, ``shot-02``… for all of them (so one id never means two moments)."""
    ids = [shot_id_from_name(f, locale, display_types) for f in files]
    if all(ids) and len(set(ids)) == len(ids) and all(re.match(r"^[a-z0-9][a-z0-9_-]*$", i) for i in ids):
        return ids, True
    return ["shot-%02d" % i for i in range(1, len(files) + 1)], False


def merge_order(order, sequence):
    """Put a folder's shot ids into the config's order, each new one after the one before it in the folder."""
    for i, sid in enumerate(sequence):
        if sid in order:
            continue
        before = [s for s in sequence[:i] if s in order]
        after = [s for s in sequence[i + 1:] if s in order]
        if before:
            order.insert(order.index(before[-1]) + 1, sid)
        elif after:
            order.insert(order.index(after[0]), sid)
        else:
            order.append(sid)
    return order


class ImportError_(Exception):
    """Nothing to import at the path given (exit 3)."""


def _natural(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _read(path):
    """A text file's contents, stripped; None when it's missing or empty."""
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8-sig") as f:
        value = f.read().strip()
    return value or None


def _pictures_in(folder):
    """The picture files directly in a folder, in natural order."""
    if not os.path.isdir(folder):
        return []
    names = [n for n in os.listdir(folder) if os.path.splitext(n)[1].lower() in PICTURE_EXTS and not n.startswith(".")]
    return [os.path.join(folder, n) for n in sorted(names, key=_natural)]


def _keywords(text):
    if text is None:
        return None
    if isinstance(text, list):
        items = [str(k).strip() for k in text]
    else:
        items = [k.strip() for k in text.split(",")]
    items = [k for k in items if k]
    return items or None


def _copyright(text):
    """fastlane's copyright without a leading (c) sign (Apple adds it)."""
    if text is None:
        return None, False
    stripped = re.sub(r"(?i)^\s*(©|\(c\)|copyright\b)\s*", "", text).strip()
    return stripped, stripped != text.strip()


def _category(text):
    """An App Store category id from fastlane's spelling (``FOOD_AND_DRINK`` or ``MZGenre.FoodAndDrink``)."""
    if not text:
        return None
    text = text.strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    if not re.match(r"^[A-Z0-9_]+$", text):
        text = re.sub(r"(?<!^)(?=[A-Z])", "_", text.replace("&", "And").replace(" ", "")).upper()
    return text


def _bcp47(code, store):
    """A store's locale code as BCP 47 (``from_apple``/``from_google``), else its canonical spelling."""
    try:
        return locales.from_apple(code) if store == "apple" else locales.from_google(code)
    except locales.LocaleError:
        return locales.canonical(code)


def _is_locale(name, store):
    if name in ("default", "android", "review_information", "trade_representative_contact_information"):
        return False
    table = locales.APPLE if store == "apple" else locales.GOOGLE
    if name in table:
        return True
    try:
        locales.canonical(name)
    except locales.LocaleError:
        return False
    return bool(re.match(r"^[a-z]{2,3}([-_][A-Za-z0-9]{2,8})*$", name))


class Merge:
    """The config being written: loaded if it exists, else a skeleton; values set only where it has none."""

    def __init__(self, out_path):
        self.path = os.path.abspath(out_path)
        self.dir = os.path.dirname(self.path)
        self.existed = os.path.isfile(self.path)
        self.data = jsonio.load(self.path) if self.existed else skeleton()
        self.took = []
        self.kept = []
        self.notes = []
        self.not_copied = []
        self.copied = 0
        self.new_stores = set()
        self.old_screens = [k for k in (self.data.get("screens") or {}) if not k.startswith("$")]
        self.old_shots = set(s.get("id") for s in ((self.data.get("screenshots") or {}).get("shots") or []))
        self.old_platforms = set(p for p, v in (((self.data.get("stores") or {}).get("apple") or {})
                                               .get("platforms") or {}).items() if isinstance(v, dict))
        self.shot_screens = collections.OrderedDict()  # shot id -> screens it got a picture for in this import
        self.generic_ids = False

    # -- values --------------------------------------------------------------------------------------------

    def node(self, keys):
        """The object at ``keys``, made (as an object) where missing or null."""
        node = self.data
        for k in keys:
            if not isinstance(node.get(k), dict):
                node[k] = collections.OrderedDict()
            node = node[k]
        return node

    def get(self, keys):
        """The value at ``keys``, or None."""
        node = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return None
            node = node[k]
        return node

    def set(self, keys, value, what=None):
        """Set ``keys`` to ``value`` unless the config already has a non-null value there."""
        if value is None:
            return False
        parent = self.node(keys[:-1])
        last = keys[-1]
        label = what or ".".join(keys)
        current = parent.get(last)
        if current is None:
            parent[last] = value
            self.took.append(label)
            return True
        if current != value:
            self.kept.append(label)
        return False

    @property
    def primary(self):
        """The config's primary locale."""
        return self.data.get("primaryLocale")

    def choose_primary(self, candidates, preferred=None):
        """Set ``primaryLocale`` for a new config: ``preferred`` if given, else en-US if present, else the first."""
        if self.primary:
            return
        if preferred and preferred in candidates:
            choice = preferred
        elif "en-US" in candidates:
            choice = "en-US"
        else:
            choice = candidates[0] if candidates else "en-US"
        self.data["primaryLocale"] = choice
        self.took.append("primaryLocale")
        self.notes.append("primaryLocale is %s: check it's the primary language each store actually uses "
                          "(App Store Connect and Play Console set it per app)" % choice)

    def primary_value(self, group, field):
        """The primary locale's value of a field (``group`` None for the shared description)."""
        words = (self.data.get("locales") or {}).get(self.primary) or {}
        return words.get(field) if group is None else (words.get(group) or {}).get(field)

    def set_word(self, loc, group, field, value):
        """Set a locale's field, leaving it to fall back when it's the same as the primary locale's."""
        if value is None:
            return
        if loc != self.primary and self.primary_value(group, field) == value:
            return
        keys = ["locales", loc] + ([group] if group else []) + [field]
        self.node(["locales", loc])
        self.set(keys, value)

    def set_description(self, loc, group, field, value):
        """A store's description: into the locale's shared ``description`` if it has none (or the same),
        else into the store's own field."""
        if value is None:
            return
        words = self.node(["locales", loc])
        shared = words.get("description")
        if loc != self.primary and shared is None and self.primary_value(None, "description") == value:
            return
        if shared is None:
            self.set(["locales", loc, "description"], value)
        elif shared != value:
            if group in self.new_stores:
                # the other store's words are the shared description: this store's own go in its field
                self.set_word(loc, group, field, value)
            elif (words.get(group) or {}).get(field) is None:
                self.kept.append("locales.%s.description (the import's %s.%s differs)" % (loc, group, field))
            else:
                self.set_word(loc, group, field, value)

    # -- files -----------------------------------------------------------------------------------------

    def copy(self, src, rel):
        """Copy a file into the config's folder at ``rel`` (unless an identical one is there; a different one
        is kept). Returns the relative path used."""
        dst = os.path.join(self.dir, rel)
        if os.path.exists(dst):
            if not filecmp.cmp(src, dst, shallow=False):
                self.kept.append(rel)
            return rel
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        self.copied += 1
        return rel

    def add_screenshots(self, files, loc, screen, kind, ids=None):
        """Copy a folder's screenshots (in order) into ``<folder>/<locale>/<screen>/<shot>.<ext>``, list the
        screen, and merge their shot ids into ``screenshots.shots``' order. ``ids``: taken from the file names
        (``shot_ids``) unless given."""
        if not files:
            return
        if ids is None:
            ids, named = shot_ids(files, loc, _display_types())
            self.generic_ids = self.generic_ids or not named
        folder = self.node(["screenshots"]).setdefault("folder", "screenshots")
        self.node(["screenshots"]).setdefault("shots", [])
        for src, shot in zip(files, ids):
            ext = os.path.splitext(src)[1].lower()
            ext = ".jpg" if ext == ".jpeg" else ext
            self.copy(src, os.path.join(folder, loc, screen, shot + ext))
            self.shot_screens.setdefault(shot, [])
            if screen not in self.shot_screens[shot]:
                self.shot_screens[shot].append(screen)
        screens = self.node(["screens"])
        if screen not in screens:
            screens[screen] = collections.OrderedDict([("kind", kind)])
            self.took.append("screens.%s" % screen)
        shots = self.data["screenshots"]["shots"]
        order = merge_order([s.get("id") for s in shots], list(ids))
        by_id = dict((s.get("id"), s) for s in shots)
        shots[:] = [by_id.get(i) or collections.OrderedDict([("id", i), ("screens", None), ("stores", None)])
                    for i in order]

    def settle_shots(self):
        """Each shot's ``screens`` after the import: a shot new here lists the screens it has pictures for; one
        the config had gains the screens this import gave it; a shot for every screen (null) that has no picture
        for a screen this import added keeps to the screens it had. A list naming every screen becomes null."""
        shots = (self.data.get("screenshots") or {}).get("shots") or []
        all_screens = [k for k in (self.data.get("screens") or {}) if not k.startswith("$")]
        added = [k for k in all_screens if k not in self.old_screens]
        for shot in shots:
            sid = shot.get("id")
            got = self.shot_screens.get(sid, [])
            screens = shot.get("screens")
            if sid not in self.old_shots:
                screens = [k for k in all_screens if k in got]
            elif screens is None:
                if added and not all(k in got for k in added):
                    screens = self.old_screens + [k for k in added if k in got]
            else:
                screens = list(screens) + [k for k in got if k not in screens]
            if isinstance(screens, list) and screens and set(all_screens) <= set(screens):
                screens = None
            shot["screens"] = screens or None

    def set_store_locales(self, store, locs, primary_key, primary):
        """``stores.<store>.locales``: what this source had (a store made here), or the list grown by it (one
        the config lists already); a store the config gives every locale (no list) is left so. The store's
        primary (``primary_key``) is set where the config hasn't one."""
        section = self.node(["stores", store])
        if store in self.new_stores:
            section["locales"] = list(locs)
            self.took.append("stores.%s.locales (%s)" % (store, ", ".join(locs)))
        elif isinstance(section.get("locales"), list):
            more = [l for l in locs if l not in section["locales"]]
            if more:
                section["locales"].extend(more)
                self.took.append("stores.%s.locales (+%s)" % (store, ", ".join(more)))
        if primary and store in self.new_stores:
            self.set(["stores", store, primary_key], primary)

    # -- stores ------------------------------------------------------------------------------------------

    def apple(self):
        """``stores.apple``, made (enabled) if missing."""
        stores = self.node(["stores"])
        if not isinstance(stores.get("apple"), dict):
            stores["apple"] = collections.OrderedDict([
                ("enabled", True),
                ("primaryLocale", None),
                ("locales", None),
                ("categories", collections.OrderedDict([
                    ("primary", None), ("primarySubcategories", []), ("secondary", None),
                    ("secondarySubcategories", [])])),
                ("platforms", collections.OrderedDict((p, None) for p in ("IOS", "MAC_OS", "TV_OS", "VISION_OS"))),
                ("ageRating", collections.OrderedDict()),
                ("review", collections.OrderedDict([("notes", None), ("contact", collections.OrderedDict(REVIEW_ENV)),
                                                    ("demoAccount", None)])),
                ("tvPrivacyText", None),
            ])
            self.took.append("stores.apple")
            self.new_stores.add("apple")
        a = stores["apple"]
        review = a.setdefault("review", collections.OrderedDict())
        contact = review.setdefault("contact", collections.OrderedDict())
        for k, v in REVIEW_ENV.items():
            contact.setdefault(k, v)
        return a

    def google(self):
        """``stores.google``, made (enabled) if missing."""
        stores = self.node(["stores"])
        if not isinstance(stores.get("google"), dict):
            stores["google"] = collections.OrderedDict([
                ("enabled", True),
                ("defaultLanguage", None),
                ("locales", None),
                ("category", None),
                ("slots", collections.OrderedDict((s, None) for s in ("phone", "tablet7", "tablet10", "tv", "wear"))),
                ("graphics", collections.OrderedDict((g, None) for g in SUPPLY_GRAPHICS)),
                ("dataSafetyCsv", None),
            ])
            self.took.append("stores.google")
            self.new_stores.add("google")
        return stores["google"]

    def add_platform_screen(self, platform, screen):
        """List a screen under an Apple platform (making the platform if it was null)."""
        plats = self.apple().setdefault("platforms", collections.OrderedDict())
        if not isinstance(plats.get(platform), dict):
            plats[platform] = collections.OrderedDict([("screens", []), ("previews", collections.OrderedDict())])
            self.took.append("stores.apple.platforms.%s" % platform)
        screens = plats[platform].setdefault("screens", [])
        if screen not in screens:
            screens.append(screen)

    def save(self):
        """Write the config (``app.name`` left out until something set it, so the check asks for it)."""
        self.settle_shots()
        if self.generic_ids:
            self.notes.append("some screenshots' file names don't say which moment they show, so they were named "
                              "shot-01, shot-02… per screen, in file order: rename them to meaningful ids (in "
                              "screenshots.shots and the files) so one id is the same moment on every screen")
        app = self.data.get("app") or {}
        if app.get("name") is None:
            app.pop("name", None)
            self.notes.append("app.name wasn't in the metadata: set it before checking")
        if not self.data.get("primaryLocale"):
            self.data["primaryLocale"] = "en-US"
        locs = self.data.get("locales") or {}
        for loc, words in list(locs.items()):
            if isinstance(words, dict):
                order = ["$comment", "description", "apple", "google", "altText"]
                locs[loc] = collections.OrderedDict(
                    sorted(words.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order)))
        jsonio.dump(self.data, self.path)


def skeleton():
    """A new config's shape, every value unset."""
    return collections.OrderedDict([
        ("version", 1),
        ("app", collections.OrderedDict([
            ("name", None),
            ("ids", collections.OrderedDict()),
            ("copyright", None),
            ("contact", collections.OrderedDict([("email", None), ("phone", None), ("website", None)])),
            ("urls", collections.OrderedDict([("marketing", None), ("support", None), ("privacy", None),
                                              ("privacyChoices", None)])),
        ])),
        ("primaryLocale", None),
        ("locales", collections.OrderedDict()),
        ("screenshots", collections.OrderedDict([("folder", "screenshots"), ("shots", [])])),
        ("screens", collections.OrderedDict()),
        ("stores", collections.OrderedDict()),
        ("forms", collections.OrderedDict()),
        ("rules", collections.OrderedDict([("extraForbiddenWords", []), ("relax", [])])),
    ])


# ---------------------------------------------------------------------------------------------------------
# Apple: fastlane deliver

def _apple_slots():
    return rules.load("apple", RULES_DIR).slots


def _display_types():
    """Apple's display type codes (``APP_IPHONE_67``…), which fastlane file names may carry."""
    return [v.get("displayType") or k for k, v in _apple_slots().items() if isinstance(v, dict)]


def _screen_for_slot(key):
    """Our screen name for an Apple display type: APP_IPHONE_67 -> iphone-67, APP_DESKTOP -> mac."""
    name = key.lower()
    if name.startswith("app_"):
        name = name[4:]
    return "mac" if name == "desktop" else name.replace("_", "-")


# A device class's screen name, by the slot's platform and kind
DEVICE_CLASS = {("IOS", "phone"): "iphone", ("IOS", "tablet"): "ipad", ("IOS", "watch"): "apple-watch",
                ("MAC_OS", "desktop"): "mac", ("TV_OS", "tv"): "apple-tv", ("VISION_OS", "xr"): "vision-pro"}


def _apple_slot_for(size, slots, platform=None):
    """The first Apple slot a picture's size fits (the given platform's slots first)."""
    import listing  # the slot rules live with the check
    items = list(slots.items())
    if platform:
        items = [kv for kv in items if kv[1].get("platform") == platform] + \
            [kv for kv in items if kv[1].get("platform") != platform]
    for key, slot in items:
        if listing.fits(size, slot.get("sizes") or [], slot.get("orientation")):
            return key, slot
    return None, None


# The fields App Store Connect keeps per platform, as fastlane names them -> the config's
FASTLANE_PLATFORM_FIELDS = collections.OrderedDict([
    ("description", "description"), ("keywords", "keywords"), ("promotional_text", "promotionalText"),
    ("release_notes", "whatsNew"), ("marketing_url", "marketingUrl"), ("support_url", "supportUrl")])


def import_fastlane(m, path, platform=None):
    """fastlane deliver's metadata (and screenshots) into the config: one Apple platform's (``platform``, else
    the one its screenshots are for, else IOS). A platform imported after another whose words differ gets
    them as overrides (``locales.<loc>.apple.platforms.<P>``)."""
    meta = path
    if os.path.isdir(os.path.join(path, "metadata")):
        meta = os.path.join(path, "metadata")
    if not os.path.isdir(meta):
        raise ImportError_("%s isn't a folder" % path)
    shots_dir = os.path.join(os.path.dirname(meta), "screenshots")
    locs = [n for n in sorted(os.listdir(meta)) if os.path.isdir(os.path.join(meta, n)) and _is_locale(n, "apple")]
    if not locs and not os.path.isfile(os.path.join(meta, "copyright.txt")):
        raise ImportError_("no fastlane deliver metadata in %s (expected metadata/<locale>/*.txt)" % path)
    pictures = _apple_screenshots(m, shots_dir, platform)
    found = []
    for _, _, _, slot in pictures:
        if slot.get("platform") not in found:
            found.append(slot.get("platform"))
    if platform is None:
        platform = found[0] if len(found) == 1 else "IOS"
        if len(found) > 1:
            m.notes.append("the screenshots are for %s: the words were imported as %s's (pass --platform to say "
                           "which platform this folder is)" % (", ".join(found), platform))
    m.apple()
    bcp = collections.OrderedDict((n, _bcp47(n, "apple")) for n in locs)
    m.choose_primary(list(bcp.values()))
    apple_locs = list(bcp.values())
    apple_primary = None
    for cand in (m.get(["stores", "apple", "primaryLocale"]), m.primary, "en-US") + tuple(apple_locs[:1]):
        if cand in apple_locs:
            apple_primary = cand
            break
    m.set_store_locales("apple", apple_locs, "primaryLocale", apple_primary)
    # Words of a platform the config already had words for (another fastlane folder) are this platform's own
    # where they differ.
    overriding = "apple" not in m.new_stores and platform not in m.old_platforms and bool(m.old_platforms)
    default = os.path.join(meta, "default")
    values = collections.OrderedDict()
    for code, loc in bcp.items():
        values[loc] = collections.OrderedDict()
        for fname in list(FASTLANE_FIELDS) + list(FASTLANE_URLS) + ["apple_tv_privacy_policy"]:
            values[loc][fname] = _read(os.path.join(meta, code, fname + ".txt"))
    if os.path.isdir(default):
        target = apple_primary if apple_primary in values else (list(values)[0] if values else None)
        if target:
            for fname in values[target]:
                if values[target][fname] is None:
                    values[target][fname] = _read(os.path.join(default, fname + ".txt"))
            m.notes.append("metadata/default/ was used where %s had no file of its own" % target)
    order = sorted(values, key=lambda l: (l != apple_primary, l != m.primary, list(values).index(l)))
    overridden = []
    for loc in order:
        v = values[loc]
        name = v.get("name")
        if loc == m.primary and name is not None and m.set(["app", "name"], name):
            name = None  # app.name now; apple.name falls back to it
        app_name = (m.data.get("app") or {}).get("name")
        if name is not None and name == app_name and m.primary_value("apple", "name") is None:
            name = None
        m.set_word(loc, "apple", "name", name)
        m.set_word(loc, "apple", "subtitle", v.get("subtitle"))
        for fname, field in FASTLANE_PLATFORM_FIELDS.items():
            value = v.get(fname)
            if field == "keywords":
                value = _keywords(value)
            if value is None:
                continue
            if overriding:
                import listing
                now = listing.Listing(m.path, m.data).resolve(loc, "apple." + field, "apple", platform)[0]
                if now is not None:
                    if now != value:
                        m.set(["locales", loc, "apple", "platforms", platform, field], value)
                        overridden.append("%s %s" % (loc, field))
                    continue
            if field == "description":
                m.set_description(loc, "apple", "description", value)
            elif field in ("marketingUrl", "supportUrl"):
                key = FASTLANE_URLS[fname]
                if loc == m.primary or m.get(["app", "urls", key]) is None:
                    m.set(["app", "urls", key], value)
                elif m.get(["app", "urls", key]) != value:
                    m.notes.append("%s's %s differs from the primary locale's: the config has one for every locale "
                                   "(or set locales.%s.apple.platforms.%s.%s)" % (loc, fname, loc, platform, field))
            else:
                m.set_word(loc, "apple", field, value)
        if v.get("privacy_url") is not None:
            if loc == m.primary or m.get(["app", "urls", "privacy"]) is None:
                m.set(["app", "urls", "privacy"], v["privacy_url"])
            elif m.get(["app", "urls", "privacy"]) != v["privacy_url"]:
                m.notes.append("%s's privacy_url differs from the primary locale's: the config has one for every "
                               "locale" % loc)
        if v.get("release_notes"):
            m.notes.append("%s What's New came across as \"%s\": rewrite it for the next version's changes"
                           % (loc, v["release_notes"][:60] + ("…" if len(v["release_notes"]) > 60 else "")))
        if v.get("apple_tv_privacy_policy") and loc == apple_primary:
            rel = "apple-tv-privacy.txt"
            dst = os.path.join(m.dir, rel)
            if not os.path.exists(dst):
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(v["apple_tv_privacy_policy"] + "\n")
            m.set(["stores", "apple", "tvPrivacyText"], rel)
    if overridden:
        m.notes.append("%s's words differ from the platforms imported before: they're %s's own "
                       "(locales.<loc>.apple.platforms.%s): %s" % (platform, platform, platform, ", ".join(overridden)))
    text, changed = _copyright(_read(os.path.join(meta, "copyright.txt")))
    if m.set(["app", "copyright"], text) and changed:
        m.notes.append("the copyright's leading sign was dropped: Apple adds it")
    for which in ("primary", "secondary"):
        m.set(["stores", "apple", "categories", which], _category(_read(os.path.join(meta, which + "_category.txt"))))
        subs = [_category(_read(os.path.join(meta, "%s_%s_sub_category.txt" % (which, n))))
                for n in ("first", "second")]
        subs = [s for s in subs if s]
        cats = m.node(["stores", "apple", "categories"])
        if subs and not cats.get(which + "Subcategories"):
            cats[which + "Subcategories"] = subs
            m.took.append("stores.apple.categories.%sSubcategories" % which)
    review = os.path.join(meta, "review_information")
    if os.path.isdir(review):
        m.set(["stores", "apple", "review", "notes"], _read(os.path.join(review, "notes.txt")))
        personal = sorted(n for n in os.listdir(review) if n.endswith(".txt") and n != "notes.txt")
        if personal:
            m.not_copied.append("review_information/%s (App Review's contact and sign-in: personal). Set %s instead, "
                                "and stop committing those files" % (
                                    ", ".join(personal), ", ".join(REVIEW_ENV.values())))
        if any(n.startswith("demo_") for n in personal):
            a = m.apple()
            if a["review"].get("demoAccount") is None:
                a["review"]["demoAccount"] = collections.OrderedDict(DEMO_ENV)
                m.took.append("stores.apple.review.demoAccount (environment variable names)")
                m.not_copied.append("the demo account: set %s" % ", ".join(DEMO_ENV.values()))
    for name in FASTLANE_PERSONAL[1:]:
        if os.path.isdir(os.path.join(meta, name)):
            m.not_copied.append("%s/ (personal; the EU trader details are entered in App Store Connect)" % name)
    if os.path.isdir(os.path.join(meta, "android")):
        m.notes.append("%s is Google Play's: import it with --from supply" % os.path.join(meta, "android"))
    if m.get(["app", "ids", "apple", "bundleId"]) is None:
        m.notes.append("set app.ids.apple.bundleId (the metadata doesn't say it)")
    n = _import_apple_screenshots(m, pictures)
    if n == 0 and not isinstance((m.apple().get("platforms") or {}).get(platform), dict):
        screen = DEVICE_CLASS.get((platform, {"IOS": "phone", "MAC_OS": "desktop", "TV_OS": "tv",
                                              "VISION_OS": "xr"}[platform]))
        kind = {"IOS": "phone", "MAC_OS": "desktop", "TV_OS": "tv", "VISION_OS": "xr"}[platform]
        m.add_platform_screen(platform, screen)
        m.node(["screens"]).setdefault(screen, collections.OrderedDict([("kind", kind)]))
        m.notes.append("no screenshots were found: stores.apple.platforms.%s lists a '%s' screen; add the "
                       "platforms and screens you ship" % (platform, screen))
    if os.path.isdir(os.path.join(os.path.dirname(meta), "app_previews")):
        m.notes.append("app_previews/ weren't imported: list them under stores.apple.platforms.<platform>.previews")


def _apple_screenshots(m, shots_dir, platform=None):
    """fastlane's ``screenshots/<locale>/*.png``, each with its slot by its pixel size: ``[(src, locale, slot
    key, slot)]`` (pictures that fit no slot are noted and left out)."""
    if not os.path.isdir(shots_dir):
        return []
    slots = _apple_slots()
    out = []
    for code in sorted(os.listdir(shots_dir)):
        folder = os.path.join(shots_dir, code)
        if not os.path.isdir(folder) or not _is_locale(code, "apple"):
            continue
        loc = _bcp47(code, "apple")
        for src in _pictures_in(folder):
            try:
                info = png.info(src)
            except (png.ImageError, OSError) as e:
                m.notes.append("%s wasn't imported: %s" % (os.path.basename(src), e))
                continue
            key, slot = _apple_slot_for((info.width, info.height), slots, platform)
            if key is None:
                m.notes.append("%s (%dx%d) fits no App Store slot and wasn't imported" % (
                    os.path.join(code, os.path.basename(src)), info.width, info.height))
                continue
            out.append((src, loc, key, slot))
    return out


def _import_apple_screenshots(m, pictures, names=None, primary=None):
    """Copy fastlane's (or a pull's) screenshots into the config's layout: a screen per device class (``iphone``,
    ``ipad``, ``mac``, ``apple-tv``…), or per display type (``iphone-67``) where a class has pictures in two; shot
    ids from the file names. ``names``: each source file's own name to take the id from (a pull's files are
    ``01.png``…; the store kept the uploaded name), and then another locale's pictures on a screen take the
    ``primary`` locale's ids by position (the same set, translated)."""
    keys_by_class = collections.OrderedDict()
    for _, _, key, slot in pictures:
        cls = DEVICE_CLASS.get((slot.get("platform"), slot.get("kind")))
        keys_by_class.setdefault(cls, [])
        if key not in keys_by_class[cls]:
            keys_by_class[cls].append(key)
    groups = collections.OrderedDict()  # (loc, screen) -> (kind, platform, [src])
    for src, loc, key, slot in pictures:
        cls = DEVICE_CLASS.get((slot.get("platform"), slot.get("kind")))
        screen = cls if cls and len(keys_by_class[cls]) == 1 else _screen_for_slot(key)
        groups.setdefault((loc, screen), (slot.get("kind") or "phone", slot.get("platform") or "IOS", []))[2].append(src)
    classes = list(DEVICE_CLASS.values())

    def rank(item):
        """Per locale, the device classes in DEVICE_CLASS's order (iPhone before iPad), display types by class."""
        (loc, screen), _ = item
        cls = screen if screen in classes else next(
            (c for c in classes if screen.startswith(c.split("-")[0] + "-")), None)
        return (loc, classes.index(cls) if cls in classes else len(classes), screen)

    first_ids = {}
    if names:
        for (loc, screen), (_, _, files) in groups.items():
            if loc == primary:
                first_ids[screen], named = shot_ids([names.get(f, f) for f in files], loc, _display_types())
                m.generic_ids = m.generic_ids or not named
    for (loc, screen), (kind, platform, files) in sorted(groups.items(), key=rank):
        ids = None
        if names:
            ids = first_ids.get(screen) if loc == primary else None
            if ids is None and screen in first_ids and len(files) <= len(first_ids[screen]):
                ids = first_ids[screen][:len(files)]
            if ids is None:
                ids, named = shot_ids([names.get(f, f) for f in files], loc, _display_types())
                m.generic_ids = m.generic_ids or not named
        m.add_screenshots(files, loc, screen, kind, ids)
        m.add_platform_screen(platform, screen)
    return len(pictures)


# ---------------------------------------------------------------------------------------------------------
# Expo: store.config.json

def import_expo(m, path):
    """Expo's ``store.config.json`` (EAS Metadata; App Store only) into the config."""
    if os.path.isdir(path):
        path = os.path.join(path, "store.config.json")
    if not os.path.isfile(path):
        raise ImportError_("no store.config.json at %s (a store.config.js has to be turned into JSON first)" % path)
    data = jsonio.load(path)
    apple = data.get("apple") if isinstance(data, dict) else None
    if not isinstance(apple, dict):
        raise ImportError_("%s has no \"apple\" section" % path)
    m.apple()
    info = apple.get("info") or {}
    bcp = collections.OrderedDict((code, _bcp47(code, "apple")) for code in info)
    m.choose_primary(list(bcp.values()))
    apple_locs = list(bcp.values())
    first = [l for l in (m.primary, "en-US") + tuple(apple_locs[:1]) if l in apple_locs]
    m.set_store_locales("apple", apple_locs, "primaryLocale", first[0] if first else None)
    order = sorted(bcp, key=lambda c: (bcp[c] != m.primary, list(bcp).index(c)))
    for code in order:
        loc = bcp[code]
        v = info.get(code) or {}
        name = v.get("title")
        if loc == m.primary and name and m.set(["app", "name"], name):
            name = None
        app_name = (m.data.get("app") or {}).get("name")
        if name is not None and name == app_name and m.primary_value("apple", "name") is None:
            name = None
        m.set_word(loc, "apple", "name", name)
        m.set_word(loc, "apple", "subtitle", v.get("subtitle") or None)
        m.set_description(loc, "apple", "description", v.get("description") or None)
        m.set_word(loc, "apple", "keywords", _keywords(v.get("keywords")))
        m.set_word(loc, "apple", "promotionalText", v.get("promoText") or None)
        m.set_word(loc, "apple", "whatsNew", v.get("releaseNotes") or None)
        for key, target in (("marketingUrl", "marketing"), ("supportUrl", "support"),
                            ("privacyPolicyUrl", "privacy"), ("privacyChoicesUrl", "privacyChoices")):
            if v.get(key) and (loc == m.primary or m.get(["app", "urls", target]) is None):
                m.set(["app", "urls", target], v[key])
        if v.get("privacyPolicyText"):
            m.notes.append("%s privacyPolicyText (Apple TV's privacy text) wasn't imported: save it as a text file "
                           "and point stores.apple.tvPrivacyText at it" % loc)
    text, changed = _copyright(apple.get("copyright"))
    m.set(["app", "copyright"], text)
    cats = apple.get("categories") or []
    flat = []
    for item in cats:
        if isinstance(item, list) and item:
            flat.append((item[0], list(item[1:])))
        elif isinstance(item, str):
            if flat and item.startswith(flat[-1][0] + "_"):
                flat[-1][1].append(item)
            else:
                flat.append((item, []))
    for which, (cat, subs) in zip(("primary", "secondary"), flat):
        m.set(["stores", "apple", "categories", which], cat)
        node = m.node(["stores", "apple", "categories"])
        if subs and not node.get(which + "Subcategories"):
            node[which + "Subcategories"] = subs[:2]
            m.took.append("stores.apple.categories.%sSubcategories" % which)
    advisory = apple.get("advisory") or {}
    if advisory:
        try:
            attrs = jsonio.load(os.path.join(RULES_DIR, "apple.json")).get("ageRating", {}).get("attributes", {})
        except (jsonio.JsonError, OSError):
            attrs = {}
        skipped = []
        for key, value in advisory.items():
            if key in attrs:
                m.set(["stores", "apple", "ageRating", key], value)
            else:
                skipped.append(key)
        if skipped:
            m.notes.append("age rating answers not in App Store Connect's current attributes weren't imported: %s"
                           % ", ".join(sorted(skipped)))
    if m.get(["app", "ids", "apple", "bundleId"]) is None:
        m.notes.append("set app.ids.apple.bundleId (store.config.json doesn't say it; it's in app.json)")
    review = apple.get("review") or {}
    if review:
        m.set(["stores", "apple", "review", "notes"], review.get("notes") or None)
        personal = sorted(k for k in review if k not in ("notes", "demoRequired"))
        if personal:
            m.not_copied.append("apple.review's %s (App Review's contact and sign-in: personal). Set %s instead"
                                % (", ".join(personal), ", ".join(REVIEW_ENV.values())))
        if review.get("demoRequired") or review.get("demoUsername") or review.get("demoPassword"):
            a = m.apple()
            if a["review"].get("demoAccount") is None:
                a["review"]["demoAccount"] = collections.OrderedDict(DEMO_ENV)
                m.took.append("stores.apple.review.demoAccount (environment variable names)")
                m.not_copied.append("the demo account: set %s" % ", ".join(DEMO_ENV.values()))
    if not any((m.apple().get("platforms") or {}).values()):
        m.add_platform_screen("IOS", "iphone")
        m.node(["screens"]).setdefault("iphone", collections.OrderedDict([("kind", "phone")]))
        m.notes.append("store.config.json has no screenshots: stores.apple.platforms.IOS lists an 'iphone' screen; "
                       "add the platforms and screens you ship, and the pictures")


# ---------------------------------------------------------------------------------------------------------
# Google: fastlane supply and Triple-T

def _set_google_words(m, values):
    """Each locale's Play words (``{loc: {title, shortDescription, fullDescription, video, releaseNotes}}``),
    primary first."""
    order = sorted(values, key=lambda l: (l != m.primary, list(values).index(l)))
    for loc in order:
        v = values[loc]
        m.set_word(loc, "google", "title", v.get("title"))
        m.set_word(loc, "google", "shortDescription", v.get("shortDescription"))
        m.set_description(loc, "google", "fullDescription", v.get("fullDescription"))
        m.set_word(loc, "google", "video", v.get("video"))
        m.set_word(loc, "google", "releaseNotes", v.get("releaseNotes"))
    if m.get(["app", "name"]) is None:
        title = (values.get(m.primary) or {}).get("title")
        if title:
            m.set(["app", "name"], title.split(":")[0].strip() or title)
            m.notes.append("app.name was taken from Play's title (%r): check it" % title)


def _same_files(a, b):
    """True when two lists of pictures are the same files, byte for byte, in the same order."""
    return len(a) == len(b) and all(filecmp.cmp(x, y, shallow=False) for x, y in zip(a, b))


def _play_screens(per_locale_images):
    """``{image type: screen}`` for the Play slots that have pictures: a slot whose pictures are byte for byte
    another's in every language shares its screen (Play's 7-inch and 10-inch slots often do); the tablets are
    one ``android-tablet`` screen unless both slots have their own pictures."""
    used = [t for t in SUPPLY_SCREENSHOTS if any(imgs.get(t) for imgs in per_locale_images.values())]
    same_as = collections.OrderedDict()
    for i, t in enumerate(used):
        for earlier in used[:i]:
            if earlier in same_as:
                continue
            if all(_same_files(imgs.get(t) or [], imgs.get(earlier) or []) for imgs in per_locale_images.values()):
                same_as[t] = earlier
                break
    own = [t for t in used if t not in same_as]
    tablets = [t for t in own if SUPPLY_SCREENSHOTS[t][2] == "tablet"]
    screens = collections.OrderedDict()
    for t in used:
        base = same_as.get(t, t)
        name = SUPPLY_SCREENSHOTS[base][1]
        if SUPPLY_SCREENSHOTS[base][2] == "tablet" and len(tablets) == 1:
            name = "android-tablet"
        screens[t] = name
    return screens, same_as


def _google_images(m, per_locale_images, per_locale_graphics, preferred=None):
    """Screenshots (``{loc: {imageType: [paths]}}``) and graphics (``{loc: {graphic: path}}``) into the config;
    ``preferred`` is the layout's own default language, if it names one."""
    g = m.google()
    screens, same_as = _play_screens(per_locale_images)
    order = sorted(per_locale_images, key=lambda l: (l != m.primary, l))
    for loc in order:
        for image_type, files in per_locale_images[loc].items():
            if not files:
                continue
            slot, _, kind = SUPPLY_SCREENSHOTS[image_type]
            if image_type not in same_as:
                m.add_screenshots(files, loc, screens[image_type], kind)
            m.set(["stores", "google", "slots", slot], screens[image_type])
    for t, base in same_as.items():
        m.notes.append("Play's %s are the %s's pictures, byte for byte: one screen, %s, fills both slots"
                       % (t, base, screens[t]))
    chosen = {}
    for loc in sorted(per_locale_graphics, key=lambda l: (l != m.primary, l)):
        for name, src in per_locale_graphics[loc].items():
            if name not in chosen:
                chosen[name] = (loc, src)
            elif not filecmp.cmp(chosen[name][1], src, shallow=False):
                m.notes.append("%s has its own %s; the config keeps one for every language (%s's was imported)"
                               % (loc, name, chosen[name][0]))
    for name in SUPPLY_GRAPHICS:
        if name in chosen:
            src = chosen[name][1]
            ext = os.path.splitext(src)[1].lower()
            rel = m.copy(src, os.path.join("graphics", name + (".jpg" if ext == ".jpeg" else ext)))
            m.set(["stores", "google", "graphics", name], rel)
    # Play's default is one of the languages imported here (an earlier import may have set the primary locale
    # from the App Store's): the layout's own default if it says, else the primary if Play has it, else en-US,
    # else the first.
    play_locs = list(per_locale_images)
    for default in (preferred, m.primary, "en-US") + tuple(play_locs[:1]):
        if default in play_locs:
            break
    else:
        default = m.primary
    m.set_store_locales("google", play_locs, "defaultLanguage", None)
    if m.set(["stores", "google", "defaultLanguage"], default):
        m.notes.append("stores.google.defaultLanguage is %s: check it matches Play Console's default" % default)
    if (m.get(["app", "ids", "google", "package"]) is None):
        m.notes.append("set app.ids.google.package (the metadata doesn't say it)")


def import_supply(m, path):
    """fastlane supply's ``metadata/android`` into the config."""
    base = path
    for cand in (os.path.join(path, "metadata", "android"), os.path.join(path, "android")):
        if os.path.isdir(cand):
            base = cand
            break
    if not os.path.isdir(base):
        raise ImportError_("%s isn't a folder" % path)
    codes = [n for n in sorted(os.listdir(base)) if os.path.isdir(os.path.join(base, n)) and _is_locale(n, "google")]
    if not codes:
        raise ImportError_("no fastlane supply metadata in %s (expected <locale>/title.txt…)" % path)
    m.google()
    bcp = collections.OrderedDict((c, _bcp47(c, "google")) for c in codes)
    m.choose_primary(list(bcp.values()))
    values = collections.OrderedDict()
    images = collections.OrderedDict()
    graphics = collections.OrderedDict()
    for code, loc in bcp.items():
        d = os.path.join(base, code)
        notes, which = _changelog(os.path.join(d, "changelogs"))
        values[loc] = {"title": _read(os.path.join(d, "title.txt")),
                       "shortDescription": _read(os.path.join(d, "short_description.txt")),
                       "fullDescription": _read(os.path.join(d, "full_description.txt")),
                       "video": _read(os.path.join(d, "video.txt")), "releaseNotes": notes}
        if which:
            m.notes.append("%s releaseNotes came from changelogs/%s (Play's release notes go with a release, "
                           "which this skill doesn't send)" % (loc, which))
        imgs = os.path.join(d, "images")
        images[loc] = collections.OrderedDict((t, _pictures_in(os.path.join(imgs, t))) for t in SUPPLY_SCREENSHOTS)
        graphics[loc] = collections.OrderedDict()
        for name in SUPPLY_GRAPHICS:
            found = [p for p in _pictures_in(imgs) if os.path.splitext(os.path.basename(p))[0] == name]
            if not found and os.path.isdir(os.path.join(imgs, name)):
                found = _pictures_in(os.path.join(imgs, name))
            if found:
                graphics[loc][name] = found[0]
    _set_google_words(m, values)
    _google_images(m, images, graphics)


def _changelog(folder):
    """The release notes to keep from a changelogs folder: ``default.txt``, else the highest version code."""
    if not os.path.isdir(folder):
        return None, None
    names = [n for n in os.listdir(folder) if n.endswith(".txt")]
    if "default.txt" in names:
        return _read(os.path.join(folder, "default.txt")), "default.txt"
    numbered = sorted((n for n in names if n[:-4].isdigit()), key=lambda n: int(n[:-4]))
    if numbered:
        return _read(os.path.join(folder, numbered[-1])), numbered[-1]
    return None, None


def import_triple_t(m, path):
    """Gradle Play Publisher's ``play/`` folder into the config."""
    base = path
    for cand in (os.path.join(path, "src", "main", "play"), os.path.join(path, "play")):
        if os.path.isdir(cand):
            base = cand
            break
    listings = os.path.join(base, "listings")
    if not os.path.isdir(listings):
        raise ImportError_("no Triple-T play/ folder at %s (expected play/listings/<locale>/)" % path)
    m.google()
    codes = [n for n in sorted(os.listdir(listings)) if os.path.isdir(os.path.join(listings, n))
             and _is_locale(n, "google")]
    bcp = collections.OrderedDict((c, _bcp47(c, "google")) for c in codes)
    default = _read(os.path.join(base, "default-language.txt"))
    preferred = _bcp47(default, "google") if default else None
    m.choose_primary(list(bcp.values()), preferred)
    m.set(["app", "contact", "email"], _read(os.path.join(base, "contact-email.txt")))
    m.set(["app", "contact", "phone"], _read(os.path.join(base, "contact-phone.txt")))
    m.set(["app", "contact", "website"], _read(os.path.join(base, "contact-website.txt")))
    values = collections.OrderedDict()
    images = collections.OrderedDict()
    graphics = collections.OrderedDict()
    for code, loc in bcp.items():
        d = os.path.join(listings, code)
        notes = None
        rn = os.path.join(base, "release-notes", code)
        if os.path.isdir(rn):
            tracks = sorted(n for n in os.listdir(rn) if n.endswith(".txt"))
            pick = "production.txt" if "production.txt" in tracks else ("default.txt" if "default.txt" in tracks
                                                                       else (tracks[0] if tracks else None))
            if pick:
                notes = _read(os.path.join(rn, pick))
                m.notes.append("%s releaseNotes came from release-notes/%s/%s" % (loc, code, pick))
        values[loc] = {"title": _read(os.path.join(d, "title.txt")),
                       "shortDescription": _read(os.path.join(d, "short-description.txt")),
                       "fullDescription": _read(os.path.join(d, "full-description.txt")),
                       "video": _read(os.path.join(d, "video-url.txt")), "releaseNotes": notes}
        gfx = os.path.join(d, "graphics")
        images[loc] = collections.OrderedDict(
            (image_type, _pictures_in(os.path.join(gfx, folder)))
            for folder, image_type in TRIPLE_T_SCREENSHOTS.items())
        graphics[loc] = collections.OrderedDict()
        for folder, name in TRIPLE_T_GRAPHICS.items():
            found = _pictures_in(os.path.join(gfx, folder))
            if found:
                graphics[loc][name] = found[0]
    _set_google_words(m, values)
    _google_images(m, images, graphics, preferred)


# ---------------------------------------------------------------------------------------------------------
# What's live: push.py pull's existing/<store>/

LIVE_VERSION_FIELDS = ("description", "keywords", "promotionalText", "whatsNew", "marketingUrl", "supportUrl")
LIVE_URLS = {"marketingUrl": "marketing", "supportUrl": "support"}
PLATFORM_KIND = {"IOS": "phone", "MAC_OS": "desktop", "TV_OS": "tv", "VISION_OS": "xr"}


def _blank(value):
    """A store's empty value (``None``, ``""``, ``[]``) as None: nothing to take."""
    if value is None or (isinstance(value, (str, list)) and not value):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def import_live(m, path):
    """What ``push.py pull`` wrote (``existing/``, or one store's folder) into the config: the words, ids, URLs,
    categories, age rating answers, App Review's notes and the pictures, as the other imports do (a value the
    config has is never replaced)."""
    import listing_live
    try:
        found = listing_live.find(path)
    except listing_live.LiveError as e:
        raise ImportError_(str(e))
    except jsonio.JsonError as e:
        raise ImportError_(str(e))
    m.live = found
    if "apple" in found:
        _live_apple(m, *found["apple"])
    if "google" in found:
        _live_google(m, *found["google"])


def _live_apple(m, folder, doc):
    import listing
    A = doc["apple"]
    m.apple()
    m.set(["app", "ids", "apple", "bundleId"], A.get("bundleId"))
    m.set(["app", "ids", "apple", "appId"], A.get("appId"))
    app = A.get("app") or {}
    infos = app.get("localizations") or {}
    plats = [(p, A["platforms"][p]) for p in listing.APPLE_PLATFORMS
             if isinstance((A.get("platforms") or {}).get(p), dict)]
    codes = list(infos)
    for _, P in plats:
        codes += [c for c in (P.get("localizations") or {}) if c not in codes]
    bcp = collections.OrderedDict((c, _bcp47(c, "apple")) for c in codes)
    store_primary = _bcp47(A["primaryLocale"], "apple") if A.get("primaryLocale") else None
    m.choose_primary(list(bcp.values()), store_primary)
    apple_locs = list(bcp.values())
    apple_primary = None
    for cand in (m.get(["stores", "apple", "primaryLocale"]), store_primary, m.primary) + tuple(apple_locs[:1]):
        if cand in apple_locs:
            apple_primary = cand
            break
    if apple_locs:
        m.set_store_locales("apple", apple_locs, "primaryLocale", apple_primary)
    first = plats[0][0] if plats else None
    overriding_first = "apple" not in m.new_stores and first not in m.old_platforms and bool(m.old_platforms)
    overridden = []
    order = sorted(bcp.items(), key=lambda kv: (kv[1] != apple_primary, kv[1] != m.primary, codes.index(kv[0])))
    for code, loc in order:
        a = infos.get(code) or {}
        name = _blank(a.get("name"))
        if loc == m.primary and name is not None and m.set(["app", "name"], name):
            name = None
        if name is not None and name == m.get(["app", "name"]) and m.primary_value("apple", "name") is None:
            name = None
        m.set_word(loc, "apple", "name", name)
        m.set_word(loc, "apple", "subtitle", _blank(a.get("subtitle")))
        for key, target in (("privacyPolicyUrl", "privacy"), ("privacyChoicesUrl", "privacyChoices")):
            value = _blank(a.get(key))
            if value is None:
                continue
            if loc == apple_primary or m.get(["app", "urls", target]) is None:
                m.set(["app", "urls", target], value)
            elif m.get(["app", "urls", target]) != value:
                m.notes.append("%s's %s differs from the primary locale's: the config has one for every locale"
                               % (loc, key))
        if _blank(a.get("privacyPolicyText")) and loc == apple_primary:
            rel = "apple-tv-privacy.txt"
            dst = os.path.join(m.dir, rel)
            if not os.path.exists(dst):
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(a["privacyPolicyText"].strip() + "\n")
            m.set(["stores", "apple", "tvPrivacyText"], rel)
        for i, (platform, P) in enumerate(plats):
            words = (P.get("localizations") or {}).get(code)
            if not words:
                continue
            overriding = i > 0 or overriding_first
            for field in LIVE_VERSION_FIELDS:
                value = _blank(words.get(field))
                if field == "keywords":
                    value = _keywords(value)
                if value is None:
                    continue
                if overriding:
                    now = listing.Listing(m.path, m.data).resolve(loc, "apple." + field, "apple", platform)[0]
                    if now is not None:
                        if now != value:
                            m.set(["locales", loc, "apple", "platforms", platform, field], value)
                            overridden.append("%s %s %s" % (loc, platform, field))
                        continue
                if field == "description":
                    m.set_description(loc, "apple", "description", value)
                elif field in LIVE_URLS:
                    key = LIVE_URLS[field]
                    if loc == apple_primary or m.get(["app", "urls", key]) is None:
                        m.set(["app", "urls", key], value)
                    elif m.get(["app", "urls", key]) != value:
                        m.set(["locales", loc, "apple", "platforms", platform, field], value)
                else:
                    m.set_word(loc, "apple", field, value)
            if loc == apple_primary and _blank(words.get("whatsNew")) and i == 0:
                text = words["whatsNew"].strip()
                m.notes.append("%s What's New came across from version %s (\"%s\"): the next version needs its own"
                               % (loc, P.get("version") or "?", text[:60] + ("…" if len(text) > 60 else "")))
    if overridden:
        m.notes.append("words that differ between the live platforms are each platform's own "
                       "(locales.<loc>.apple.platforms.<P>): %s" % ", ".join(overridden))
    _live_apple_empties(m, plats, order, infos, apple_primary, overriding_first)
    for _, P in plats:
        text, changed = _copyright(_blank(P.get("copyright")))
        if text and m.set(["app", "copyright"], text) and changed:
            m.notes.append("the copyright's leading sign was dropped: Apple adds it")
        if text:
            break
    cats = app.get("categories") or {}
    for which in ("primary", "secondary"):
        m.set(["stores", "apple", "categories", which], _blank(cats.get(which)))
        subs = [x for x in (cats.get(which + "Subcategories") or []) if x]
        node = m.node(["stores", "apple", "categories"])
        if subs and not node.get(which + "Subcategories"):
            node[which + "Subcategories"] = subs[:2]
            m.took.append("stores.apple.categories.%sSubcategories" % which)
    rating = app.get("ageRating") or {}
    if rating:
        try:
            known = jsonio.load(os.path.join(RULES_DIR, "apple.json")).get("ageRating", {}).get("attributes", {})
        except (jsonio.JsonError, OSError):
            known = {}
        skipped = []
        for key, value in rating.items():
            if value is None:
                continue
            if key in known:
                m.set(["stores", "apple", "ageRating", key], value)
            else:
                skipped.append(key)
        if skipped:
            m.notes.append("age rating answers App Store Connect keeps that aren't in the rules' current attributes "
                           "weren't imported: %s" % ", ".join(sorted(skipped)))
    review = A.get("review") or {}
    m.set(["stores", "apple", "review", "notes"], _blank(review.get("notes")))
    if review.get("demoAccountRequired"):
        a = m.apple()
        if a["review"].get("demoAccount") is None:
            a["review"]["demoAccount"] = collections.OrderedDict(DEMO_ENV)
            m.took.append("stores.apple.review.demoAccount (environment variable names)")
            m.not_copied.append("the demo account (App Review needs a sign-in): set %s" % ", ".join(DEMO_ENV.values()))
    m.not_copied.append("App Review's contact (personal: never pulled): set %s" % ", ".join(REVIEW_ENV.values()))
    _live_apple_pictures(m, folder, plats, apple_primary)
    if doc.get("notPublic"):
        m.notes.append("pulled from the public lookup: %s aren't public, so the config doesn't have them yet (pull "
                       "with the key, or write them)" % ", ".join(doc["notPublic"]))


def _live_apple_empties(m, plats, order, infos, primary, overriding_first):
    """A field a locale leaves empty on the store, where the config would fall back to another locale's words, is
    set to ``""`` (so a plan leaves it empty, not filled with the primary's); a platform missing a locale is said."""
    import listing
    lst = listing.Listing(m.path, m.data)
    emptied, missing = [], []
    for code, loc in order:
        a = infos.get(code)
        if a is not None and loc != primary and _blank(a.get("subtitle")) is None \
                and _blank(lst.resolve(loc, "apple.subtitle")[0]) is not None:
            if m.set(["locales", loc, "apple", "subtitle"], ""):
                emptied.append("%s subtitle" % loc)
        for i, (platform, P) in enumerate(plats):
            words = (P.get("localizations") or {}).get(code)
            if words is None:
                missing.append("%s %s" % (platform, loc))
                continue
            own = i > 0 or overriding_first
            if not own and loc == primary:
                continue
            for field in ("description", "keywords", "promotionalText", "whatsNew"):
                if _blank(words.get(field)) is not None:
                    continue
                if _blank(lst.resolve(loc, "apple." + field, "apple", platform)[0]) is None:
                    continue
                keys = ["locales", loc, "apple"] + (["platforms", platform] if own else []) + [field]
                if m.set(keys, [] if field == "keywords" else ""):
                    emptied.append("%s%s %s" % (loc, " " + platform if own else "", field))
    if emptied:
        m.notes.append("empty on the store, so set to \"\" (not left to fall back to another locale's words): %s"
                       % ", ".join(emptied))
    if missing:
        m.notes.append("the store has no %s listing: the config gives every App Store locale to every platform, so "
                       "a plan would add %s (with the locale's words): leave the locale out of stores.apple.locales "
                       "if that's not wanted" % (", ".join(missing), "it" if len(missing) == 1 else "them"))


def _live_apple_pictures(m, folder, plats, primary):
    """The pulled screenshots into the config's layout (their slot by display type, or by pixel size for the
    public lookup's device folders); pictures at no store size stay in existing/ as the current set."""
    import listing
    slots = _apple_slots()
    pictures, names = [], {}
    reference = collections.Counter()
    copies = 0
    for platform, P in plats:
        for code, by_slot in (P.get("screenshots") or {}).items():
            loc = _bcp47(code, "apple")
            for slot_key, items in (by_slot or {}).items():
                for item in items or []:
                    src = os.path.join(folder, item["file"]) if item.get("file") else None
                    if not src or not os.path.isfile(src):
                        continue
                    try:
                        info = png.info(src)
                    except (png.ImageError, OSError) as e:
                        m.notes.append("%s wasn't imported: %s" % (item["file"], e))
                        continue
                    key, slot = slot_key, slots.get(slot_key)
                    if slot is None or not listing.fits((info.width, info.height), slot.get("sizes") or [],
                                                        slot.get("orientation")):
                        key, slot = _apple_slot_for((info.width, info.height), slots, platform)
                    if key is None:
                        reference[slot_key] += 1
                        continue
                    pictures.append((src, loc, key, slot))
                    names[src] = item.get("fileName") or os.path.basename(src)
                    if item.get("md5") and item.get("downloadedMd5") and item["md5"] != item["downloadedMd5"]:
                        copies += 1
    _import_apple_screenshots(m, pictures, names, primary)
    for platform, P in plats:
        if not isinstance((m.apple().get("platforms") or {}).get(platform), dict):
            kind = PLATFORM_KIND[platform]
            screen = DEVICE_CLASS.get((platform, kind))
            m.add_platform_screen(platform, screen)
            m.node(["screens"]).setdefault(screen, collections.OrderedDict([("kind", kind)]))
            m.notes.append("no %s screenshots at a store size were imported: stores.apple.platforms.%s lists the "
                           "screen '%s' for the new pictures" % (platform, platform, screen))
    if reference:
        m.notes.append("%s at no App Store size (the public page's smaller copies) weren't copied into the config: "
                       "they're the current set in %s/screenshots/, for making the new ones (%s)" % (
                           "1 picture is" if sum(reference.values()) == 1 else "%d pictures are" % sum(reference.values()),
                           _shown(folder), ", ".join("%s %d" % kv for kv in reference.items())))
    if copies:
        m.notes.append("%d screenshot%s copied in %s App Store Connect's own cop%s, not the file%s uploaded: if %s "
                       "stay, push.py plan replaces the store's with %s. Put the originals or the new set in their "
                       "place before planning, or leave a screen out of stores.apple.platforms.<P>.screens to keep "
                       "that slot as the store has it" % (
                           copies, "" if copies == 1 else "s", "is" if copies == 1 else "are", "y" if copies == 1 else "ies",
                           "" if copies == 1 else "s", "it" if copies == 1 else "they", "it" if copies == 1 else "them"))


def _live_files(folder, items, copies):
    """A pulled image type's files that are there, in order; ``copies`` gains each that isn't Play's original."""
    out = []
    for item in items or []:
        src = os.path.join(folder, item["file"]) if item.get("file") else None
        if src and os.path.isfile(src):
            out.append(src)
            if item.get("sha256") and item.get("downloadedSha256") and item["sha256"] != item["downloadedSha256"]:
                copies.append(src)
    return out


def _live_google(m, folder, doc):
    G = doc["google"]
    m.google()
    m.set(["app", "ids", "google", "package"], G.get("package"))
    details = G.get("details") or {}
    m.set(["app", "contact", "email"], _blank(details.get("contactEmail")))
    m.set(["app", "contact", "website"], _blank(details.get("contactWebsite")))
    m.set(["app", "contact", "phone"], _blank(details.get("contactPhone")))
    listings = G.get("listings") or {}
    if not listings:
        m.notes.append("Play has no listing in any language yet")
        return
    bcp = collections.OrderedDict((c, _bcp47(c, "google")) for c in listings)
    preferred = _bcp47(G["defaultLanguage"], "google") if G.get("defaultLanguage") else None
    m.choose_primary(list(bcp.values()), preferred)
    values = collections.OrderedDict()
    for code, loc in bcp.items():
        v = listings.get(code) or {}
        values[loc] = {"title": _blank(v.get("title")), "shortDescription": _blank(v.get("shortDescription")),
                       "fullDescription": _blank(v.get("fullDescription")), "video": _blank(v.get("video")),
                       "releaseNotes": None}
    _set_google_words(m, values)
    import listing
    lst = listing.Listing(m.path, m.data)
    emptied = []
    for code, loc in bcp.items():
        if loc == m.get(["stores", "google", "defaultLanguage"]) or loc == preferred:
            continue
        for field in ("title", "shortDescription", "fullDescription", "video"):
            if values[loc][field] is None and _blank(lst.resolve(loc, "google." + field)[0]) is not None:
                if m.set(["locales", loc, "google", field], ""):
                    emptied.append("%s %s" % (loc, field))
    if emptied:
        m.notes.append("empty on Play, so set to \"\" (not left to fall back to another language's): %s"
                       % ", ".join(emptied))
    images = collections.OrderedDict()
    graphics = collections.OrderedDict()
    copies = []
    for code, loc in bcp.items():
        types = (G.get("images") or {}).get(code) or {}
        images[loc] = collections.OrderedDict((t, _live_files(folder, types.get(t), copies)) for t in SUPPLY_SCREENSHOTS)
        graphics[loc] = collections.OrderedDict()
        for name in SUPPLY_GRAPHICS:
            found = _live_files(folder, types.get(name), copies)
            if found:
                graphics[loc][name] = found[0]
    copies = len(copies)
    _google_images(m, images, graphics, preferred)
    m.notes.append("Play Console only, so not pulled: the category (stores.google.category tells the check whether "
                   "it's a game), tags, content rating, target audience and the feature graphic's alt text")
    if copies:
        m.notes.append("%d Play picture%s copied in %s Play's own cop%s, not the file%s uploaded: if they stay, "
                       "push.py plan replaces Play's with them. Put the originals or the new set in their place "
                       "before planning" % (copies, "" if copies == 1 else "s", "is" if copies == 1 else "are",
                                            "y" if copies == 1 else "ies", "" if copies == 1 else "s"))


# ---------------------------------------------------------------------------------------------------------

SOURCES = {"fastlane": import_fastlane, "supply": import_supply, "triple-t": import_triple_t, "expo": import_expo,
           "live": import_live}


def run_import(source, path, out, platform=None):
    """Import ``path`` (a ``source`` layout) into the config at ``out``; return the ``Merge`` (saved).
    ``platform``: the Apple platform a fastlane folder is (else its screenshots say, else IOS)."""
    if not os.path.exists(path):
        raise ImportError_("%s doesn't exist%s" % (path, ": run push.py pull apple|google first (it writes existing/)"
                                                   if source == "live" else ""))
    if platform and source != "fastlane":
        raise ImportError_("--platform is for --from fastlane (an Apple platform's folder)")
    m = Merge(out)
    if source == "fastlane":
        import_fastlane(m, path, platform)
    else:
        SOURCES[source](m, path)
    m.save()
    return m


def _shown(path):
    """A path relative to the current folder when it's inside it, else as it is."""
    rel = os.path.relpath(path)
    return path if rel.startswith("..") else rel


def main(args):
    """``listing.py import``: returns the exit code."""
    import listing
    try:
        m = run_import(args.source, args.path, args.out, getattr(args, "platform", None))
    except ImportError_ as e:
        raise listing.UsageError(str(e))
    except jsonio.JsonError as e:
        sys.stderr.write("listing.py import: %s\n" % e)
        return listing.EXIT_ERRORS
    out = sys.stdout
    out.write("%s %s from %s (%s).\n" % ("Merged into" if m.existed else "Wrote", _shown(m.path),
                                         args.path, args.source))
    if m.took:
        out.write("Took (%d):\n" % len(m.took))
        for t in m.took:
            out.write("  %s\n" % t)
    if m.copied:
        out.write("Copied %d picture%s into the config's folder.\n" % (m.copied, "" if m.copied == 1 else "s"))
    if m.kept:
        out.write("Kept what the config already had (the import's value differs):\n")
        for k in m.kept:
            out.write("  %s\n" % k)
    if m.not_copied:
        out.write("Not copied:\n")
        for n in m.not_copied:
            out.write("  %s\n" % n)
    if m.notes:
        out.write("Notes:\n")
        for n in m.notes:
            out.write("  %s\n" % n)
    live = getattr(m, "live", None)
    if live:
        import listing_live
        out.write("What's live (as pulled):\n")
        for store, (folder, doc) in live.items():
            for line in listing_live.describe(doc):
                out.write("  %s\n" % line)
        out.write("Next: look at the draft with the user and decide what to keep, then listing.py diff --config %s "
                  "--existing %s shows what a new listing would change; listing.py check --config %s\n"
                  % (_shown(m.path), args.path, _shown(m.path)))
        return listing.EXIT_OK
    out.write("Next: read the config, fill what's missing (ids, URLs, the other store), then run "
              "listing.py check --config %s\n" % _shown(m.path))
    return listing.EXIT_OK
