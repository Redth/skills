"""``listing.py import``: start or extend ``store-listing.json`` from metadata a project already keeps.

Sources (``references/importing.md``):

- ``fastlane``: fastlane ``deliver``'s ``metadata/`` (and ``screenshots/``) for the App Store.
- ``supply``: fastlane ``supply``'s ``metadata/android/`` for Google Play.
- ``triple-t``: Gradle Play Publisher's ``play/`` folder for Google Play.
- ``expo``: Expo's ``store.config.json`` (EAS Metadata) for the App Store.

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

    def add_screenshot(self, src, loc, screen, kind, shot):
        """Copy a screenshot into ``<folder>/<locale>/<screen>/<shot>.<ext>`` and list its screen and shot."""
        folder = self.node(["screenshots"]).setdefault("folder", "screenshots")
        self.node(["screenshots"]).setdefault("shots", [])
        ext = os.path.splitext(src)[1].lower()
        ext = ".jpg" if ext == ".jpeg" else ext
        self.copy(src, os.path.join(folder, loc, screen, shot + ext))
        screens = self.node(["screens"])
        if screen not in screens:
            screens[screen] = collections.OrderedDict([("kind", kind)])
            self.took.append("screens.%s" % screen)
        shots = self.data["screenshots"]["shots"]
        if shot not in [s.get("id") for s in shots]:
            shots.append(collections.OrderedDict([("id", shot), ("screens", None), ("stores", None)]))

    # -- stores ------------------------------------------------------------------------------------------

    def apple(self):
        """``stores.apple``, made (enabled) if missing."""
        stores = self.node(["stores"])
        if not isinstance(stores.get("apple"), dict):
            stores["apple"] = collections.OrderedDict([
                ("enabled", True),
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


def _screen_for_slot(key):
    """Our screen name for an Apple display type: APP_IPHONE_67 -> iphone-67, APP_DESKTOP -> mac."""
    name = key.lower()
    if name.startswith("app_"):
        name = name[4:]
    return "mac" if name == "desktop" else name.replace("_", "-")


def _apple_slot_for(size, slots):
    import listing  # the slot rules live with the check
    for key, slot in slots.items():
        if listing.fits(size, slot.get("sizes") or [], slot.get("orientation")):
            return key, slot
    return None, None


def import_fastlane(m, path):
    """fastlane deliver's metadata (and screenshots) into the config."""
    meta = path
    if os.path.isdir(os.path.join(path, "metadata")):
        meta = os.path.join(path, "metadata")
    if not os.path.isdir(meta):
        raise ImportError_("%s isn't a folder" % path)
    shots_dir = os.path.join(os.path.dirname(meta), "screenshots")
    locs = [n for n in sorted(os.listdir(meta)) if os.path.isdir(os.path.join(meta, n)) and _is_locale(n, "apple")]
    if not locs and not os.path.isfile(os.path.join(meta, "copyright.txt")):
        raise ImportError_("no fastlane deliver metadata in %s (expected metadata/<locale>/*.txt)" % path)
    m.apple()
    bcp = collections.OrderedDict((n, _bcp47(n, "apple")) for n in locs)
    m.choose_primary(list(bcp.values()))
    default = os.path.join(meta, "default")
    values = collections.OrderedDict()
    for code, loc in bcp.items():
        values[loc] = collections.OrderedDict()
        for fname in list(FASTLANE_FIELDS) + list(FASTLANE_URLS) + ["apple_tv_privacy_policy"]:
            values[loc][fname] = _read(os.path.join(meta, code, fname + ".txt"))
    if os.path.isdir(default):
        target = m.primary if m.primary in values else (list(values)[0] if values else None)
        if target:
            for fname in values[target]:
                if values[target][fname] is None:
                    values[target][fname] = _read(os.path.join(default, fname + ".txt"))
            m.notes.append("metadata/default/ was used where %s had no file of its own" % target)
    order = sorted(values, key=lambda l: (l != m.primary, list(values).index(l)))
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
        m.set_description(loc, "apple", "description", v.get("description"))
        m.set_word(loc, "apple", "keywords", _keywords(v.get("keywords")))
        m.set_word(loc, "apple", "promotionalText", v.get("promotional_text"))
        m.set_word(loc, "apple", "whatsNew", v.get("release_notes"))
        for fname, key in FASTLANE_URLS.items():
            if v.get(fname) is None:
                continue
            if loc == m.primary or m.get(["app", "urls", key]) is None:
                m.set(["app", "urls", key], v[fname])
            elif m.get(["app", "urls", key]) != v[fname]:
                m.notes.append("%s's %s differs from the primary locale's: the config has one for every locale"
                               % (loc, fname))
        if v.get("release_notes"):
            m.notes.append("%s What's New came across as \"%s\": rewrite it for the next version's changes"
                           % (loc, v["release_notes"][:60] + ("…" if len(v["release_notes"]) > 60 else "")))
        if v.get("apple_tv_privacy_policy") and loc == m.primary:
            rel = "apple-tv-privacy.txt"
            dst = os.path.join(m.dir, rel)
            if not os.path.exists(dst):
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(v["apple_tv_privacy_policy"] + "\n")
            m.set(["stores", "apple", "tvPrivacyText"], rel)
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
    n = _import_apple_screenshots(m, shots_dir)
    if n == 0 and not any((m.apple().get("platforms") or {}).values()):
        m.add_platform_screen("IOS", "iphone")
        m.node(["screens"]).setdefault("iphone", collections.OrderedDict([("kind", "phone")]))
        m.notes.append("no screenshots were found: stores.apple.platforms.IOS lists an 'iphone' screen; add the "
                       "platforms and screens you ship")
    if os.path.isdir(os.path.join(os.path.dirname(meta), "app_previews")):
        m.notes.append("app_previews/ weren't imported: list them under stores.apple.platforms.<platform>.previews")


def _import_apple_screenshots(m, shots_dir):
    """fastlane's ``screenshots/<locale>/*.png``: each picture's slot by its pixel size."""
    if not os.path.isdir(shots_dir):
        return 0
    slots = _apple_slots()
    count = 0
    for code in sorted(os.listdir(shots_dir)):
        folder = os.path.join(shots_dir, code)
        if not os.path.isdir(folder) or not _is_locale(code, "apple"):
            continue
        loc = _bcp47(code, "apple")
        per_slot = collections.Counter()
        for src in _pictures_in(folder):
            try:
                info = png.info(src)
            except (png.ImageError, OSError) as e:
                m.notes.append("%s wasn't imported: %s" % (os.path.basename(src), e))
                continue
            key, slot = _apple_slot_for((info.width, info.height), slots)
            if key is None:
                m.notes.append("%s (%dx%d) fits no App Store slot and wasn't imported" % (
                    os.path.join(code, os.path.basename(src)), info.width, info.height))
                continue
            per_slot[key] += 1
            screen = _screen_for_slot(key)
            m.add_screenshot(src, loc, screen, slot.get("kind") or "phone", "shot-%02d" % per_slot[key])
            m.add_platform_screen(slot.get("platform") or "IOS", screen)
            count += 1
    if count:
        m.notes.append("screenshots were named shot-01, shot-02… per screen, in file order: rename them to "
                       "meaningful ids (in screenshots.shots and the files) and check the order")
    return count


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


def _google_images(m, per_locale_images, per_locale_graphics, preferred=None):
    """Screenshots (``{loc: {imageType: [paths]}}``) and graphics (``{loc: {graphic: path}}``) into the config;
    ``preferred`` is the layout's own default language, if it names one."""
    g = m.google()
    order = sorted(per_locale_images, key=lambda l: (l != m.primary, l))
    for loc in order:
        for image_type, files in per_locale_images[loc].items():
            slot, screen, kind = SUPPLY_SCREENSHOTS[image_type]
            for i, src in enumerate(files, 1):
                m.add_screenshot(src, loc, screen, kind, "shot-%02d" % i)
            if files:
                m.set(["stores", "google", "slots", slot], screen)
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

SOURCES = {"fastlane": import_fastlane, "supply": import_supply, "triple-t": import_triple_t, "expo": import_expo}


def run_import(source, path, out):
    """Import ``path`` (a ``source`` layout) into the config at ``out``; return the ``Merge`` (saved)."""
    if not os.path.exists(path):
        raise ImportError_("%s doesn't exist" % path)
    m = Merge(out)
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
        m = run_import(args.source, args.path, args.out)
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
    out.write("Next: read the config, fill what's missing (ids, URLs, the other store), then run "
              "listing.py check --config %s\n" % _shown(m.path))
    return listing.EXIT_OK
