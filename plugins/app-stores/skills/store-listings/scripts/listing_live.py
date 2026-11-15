"""What's live on the stores, as ``push.py pull`` wrote it into ``existing/<store>/``: loading it, describing it
(the import's summary and the pull's README) and ``listing.py diff`` (the config's words against it).

Offline: this module only reads files. ``existing/<store>/listing.json`` is the store's own shape, in the
contract's ``listing.json`` vocabulary (``references/existing.md``); locale keys are each store's own codes.
"""

from __future__ import annotations

import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appstores_lib import jsonio  # noqa: E402
from appstores_lib import locales  # noqa: E402

STORES = ("apple", "google")
STORE_NAMES = {"apple": "App Store", "google": "Google Play"}
APPLE_PLATFORMS = ("IOS", "MAC_OS", "TV_OS", "VISION_OS")
APP_FIELDS = ("name", "subtitle", "privacyPolicyUrl", "privacyChoicesUrl")
VERSION_FIELDS = ("description", "keywords", "promotionalText", "whatsNew", "marketingUrl", "supportUrl")
LISTING_FIELDS = ("title", "shortDescription", "fullDescription", "video")
DETAIL_FIELDS = (("contactEmail", "email"), ("contactWebsite", "website"), ("contactPhone", "phone"))
# Play's image types in the order Play Console shows them, and the config's slot for each
GOOGLE_IMAGE_SLOTS = collections.OrderedDict([
    ("phoneScreenshots", "phone"), ("sevenInchScreenshots", "tablet7"), ("tenInchScreenshots", "tablet10"),
    ("tvScreenshots", "tv"), ("wearScreenshots", "wear"), ("icon", "icon"), ("featureGraphic", "featureGraphic"),
    ("tvBanner", "tvBanner")])
# The public lookup's picture sets, named by device class (it doesn't say the display type)
PUBLIC_SLOTS = {"iphone": "phone", "ipad": "tablet", "apple-tv": "tv", "mac": "desktop", "vision-pro": "xr"}


class LiveError(Exception):
    """No pulled listing where one was expected (exit 3)."""


def find(path, stores=STORES):
    """``{store: (folder, doc)}`` for each pulled store under ``path`` (``existing/``, ``existing/<store>/`` or a
    ``listing.json``). Raises ``LiveError`` when there's none."""
    found = collections.OrderedDict()
    if os.path.isfile(path):
        candidates = [os.path.dirname(os.path.abspath(path))]
    elif os.path.isfile(os.path.join(path, "listing.json")):
        candidates = [os.path.abspath(path)]
    else:
        candidates = [os.path.join(os.path.abspath(path), s) for s in stores]
    for folder in candidates:
        file = os.path.join(folder, "listing.json")
        if not os.path.isfile(file):
            continue
        doc = jsonio.load(file)
        store = doc.get("store") if isinstance(doc, dict) else None
        if store not in STORES or not isinstance(doc.get(store), dict):
            raise LiveError("%s isn't a listing push.py pull wrote (no \"store\": apple or google)" % file)
        if store in stores:
            found[store] = (folder, doc)
    if not found:
        raise LiveError("no pulled listing in %s: run push.py pull apple|google first (references/existing.md)"
                        % path)
    return found


def text(value):
    """Text as the stores compare it: ``None`` as empty, line endings normalised, the ends trimmed."""
    if value is None:
        return ""
    if isinstance(value, list):
        value = ",".join(str(v).strip() for v in value)
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def keywords(value):
    """Keywords as one comma-separated text with no spaces round the commas."""
    if isinstance(value, list):
        return ",".join(str(v).strip() for v in value if str(v).strip())
    return ",".join(p.strip() for p in text(value).split(",") if p.strip())


def short(value, limit=60):
    """A value quoted for a line, at most ``limit`` characters."""
    t = text(value).replace("\n", " ")
    if not t:
        return "(none)"
    if len(t) > limit:
        t = t[:limit - 3] + "…"
    return "'%s'" % t


def measure(value):
    """``"N characters, M words"`` for a text (keywords: ``"N characters, M keywords"``)."""
    t = text(value)
    return "%s, %s" % (_plural(len(t), "character"), _plural(len(t.split()), "word"))


def bcp47(code, store):
    """A store's locale code as BCP 47 (its canonical spelling where the tables don't know it)."""
    try:
        return locales.from_apple(code) if store == "apple" else locales.from_google(code)
    except locales.LocaleError:
        return locales.canonical(code)


def _plural(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


# ------------------------------------------------------------------------------------------ describing


def picture_counts(doc):
    """``[(platform or None, locale, slot, count)]`` of the pictures pulled, in order."""
    out = []
    store = doc["store"]
    S = doc[store]
    if store == "apple":
        for platform in APPLE_PLATFORMS:
            P = (S.get("platforms") or {}).get(platform)
            if not isinstance(P, dict):
                continue
            for kind in ("screenshots", "previews"):
                for loc, slots in (P.get(kind) or {}).items():
                    for slot, items in (slots or {}).items():
                        out.append((platform, loc, slot + (" (previews)" if kind == "previews" else ""),
                                    len(items or [])))
    else:
        for loc, types in (S.get("images") or {}).items():
            for image_type, items in (types or {}).items():
                if items:
                    out.append((None, loc, image_type, len(items)))
    return out


def describe(doc):
    """Lines describing a pulled listing: where it came from, each locale's words (lengths), the pictures per
    slot, and what it lacks."""
    store = doc["store"]
    S = doc[store]
    lines = ["%s, %s, pulled %s" % (STORE_NAMES[store], doc.get("source") or "?", doc.get("pulledAt") or "?")]
    if store == "apple":
        lines.append("  app %s (%s), primary language %s" % (S.get("bundleId") or "?", S.get("appId") or "?",
                                                              S.get("primaryLocale") or "?"))
        app = S.get("app") or {}
        cats = app.get("categories") or {}
        if cats.get("primary") or cats.get("secondary"):
            lines.append("  categories: %s%s" % (cats.get("primary") or "(none)",
                                                 ", " + cats["secondary"] if cats.get("secondary") else ""))
        locs = list((app.get("localizations") or {}))
        for P in (S.get("platforms") or {}).values():
            for loc in (P or {}).get("localizations") or {}:
                if loc not in locs:
                    locs.append(loc)
        lines.append("  locales: %s" % (", ".join(locs) or "(none)"))
        for loc in locs:
            a = (app.get("localizations") or {}).get(loc) or {}
            lines.append("  %s" % loc)
            for f in ("name", "subtitle"):
                if f in a:
                    lines.append("    %s: %s (%s)" % (f, short(a.get(f), 40), measure(a.get(f))))
            for platform in APPLE_PLATFORMS:
                P = (S.get("platforms") or {}).get(platform)
                if not isinstance(P, dict):
                    continue
                w = (P.get("localizations") or {}).get(loc)
                if not w:
                    continue
                for f in VERSION_FIELDS:
                    if f not in w or f.endswith("Url"):
                        continue
                    v = w.get(f)
                    size = ("%s, %s" % (_plural(len(keywords(v)), "character"),
                                        _plural(len(keywords(v).split(",")) if keywords(v) else 0, "keyword"))
                            if f == "keywords" else measure(v))
                    lines.append("    %s %s: %s" % (platform, f, size if text(v) else "(none)"))
        for platform in APPLE_PLATFORMS:
            P = (S.get("platforms") or {}).get(platform)
            if isinstance(P, dict):
                lines.append("  %s: version %s (%s)" % (platform, P.get("version") or "?", P.get("state") or "?"))
    else:
        lines.append("  app %s, default language %s" % (S.get("package") or "?", S.get("defaultLanguage") or "?"))
        listings = S.get("listings") or {}
        lines.append("  locales: %s" % (", ".join(listings) or "(none)"))
        for loc, w in listings.items():
            lines.append("  %s" % loc)
            for f in LISTING_FIELDS:
                v = (w or {}).get(f)
                lines.append("    %s: %s" % (f, (short(v, 40) if f in ("title", "video") else measure(v))
                                             if text(v) else "(none)"))
    counts = picture_counts(doc)
    if counts:
        lines.append("  pictures (per slot):")
        for platform, loc, slot, n in counts:
            lines.append("    %s%s %s: %d" % (platform + " " if platform else "", loc, slot, n))
    else:
        lines.append("  pictures: none pulled")
    if doc.get("notPublic"):
        lines.append("  not public (pull with keys to read them): %s" % ", ".join(doc["notPublic"]))
    return lines


# ------------------------------------------------------------------------------------------ the diff


class Entry(object):
    """One compared value: ``status`` is ``unchanged``, ``changed``, ``only-live`` or ``only-ours``."""

    def __init__(self, store, locale, platform, field, live, ours, kind="words", kept=False):
        self.kept = kept
        self.store = store
        self.locale = locale
        self.platform = platform
        self.field = field
        self.live = live
        self.ours = ours
        self.kind = kind
        if kept:
            self.status = "unchanged"
        elif kind == "pictures":
            self.status = ("unchanged" if live == ours else "only-live" if not ours else "only-ours" if not live
                           else "changed")
        elif kind == "listing":
            self.status = "only-ours" if ours else "only-live"
        else:
            a, b = (keywords(live), keywords(ours)) if field == "keywords" else (text(live), text(ours))
            self.status = ("unchanged" if a == b else "only-live" if not b else "only-ours" if not a else "changed")

    def to_json(self):
        return collections.OrderedDict([("store", self.store), ("locale", self.locale), ("platform", self.platform),
                                        ("field", self.field), ("kind", self.kind), ("status", self.status),
                                        ("live", self.live), ("ours", self.ours), ("kept", self.kept)])

    def line(self):
        where = "%s%s" % (self.platform + " " if self.platform else "", self.field)
        if self.kept:
            return "= %s: %s live, kept as the store has it (stores.%s.keep: a plan doesn't send them)" % (
                where, self.live or 0, self.store)
        if self.kind == "pictures":
            if self.status == "unchanged":
                return "= %s: %s, the same number (a plan compares the pictures themselves)" % (
                    where, _plural(self.live, "picture"))
            return "%s %s: %s live, %s ours" % ({"changed": "~", "only-live": "-", "only-ours": "+"}[self.status],
                                                where, self.live or 0, self.ours or 0)
        if self.kind == "listing":
            return "+ %s: only ours: the store has no %s listing there, so a plan would add one (%s)" % (
                where, self.locale, ", ".join(sorted(self.ours)))
        if self.status == "unchanged":
            return "= %s" % where
        if self.status == "only-live":
            return "- %s: only live, %s (the config leaves it: the store keeps it)" % (where, short(self.live))
        if self.status == "only-ours":
            return "+ %s: only ours, %s (the store has none)" % (where, short(self.ours))
        a, b = text(self.live).replace("\n", " "), text(self.ours).replace("\n", " ")
        long_ = len(a) > 60 or len(b) > 60
        sizes = " (%d → %d characters)" % (len(a), len(b)) if long_ else ""
        same = 0
        while same < min(len(a), len(b)) and a[same] == b[same]:
            same += 1
        if long_ and same > 20:  # the same opening: show where they part
            start = max(0, same - 15)
            return "~ %s%s, from character %d: '…%s' → '…%s'" % (where, sizes, same + 1, _cut(a[start:], 50),
                                                                 _cut(b[start:], 50))
        return "~ %s%s: %s → %s" % (where, sizes, short(self.live), short(self.ours))


def _cut(t, limit):
    return t if len(t) <= limit else t[:limit - 1] + "…"


def _store_code(store, loc):
    try:
        return locales.for_store(store, loc)
    except locales.LocaleError:
        return None


def diff_apple(listing, doc, report=None):
    """The App Store's entries: app info per locale, each platform's version words per locale, the categories,
    the copyright and the pictures per slot. ``report``: a check's ``StoreCheck`` (for our pictures), or None."""
    S = doc["apple"]
    not_public = set(doc.get("notPublic") or [])
    entries = []
    ours_codes = collections.OrderedDict()
    if listing.store("apple"):
        for loc in listing.store_locale_codes("apple"):
            code = _store_code("apple", loc)
            if code:
                ours_codes[code] = loc
    app = S.get("app") or {}
    live_app = app.get("localizations") or {}
    platforms = [p for p in APPLE_PLATFORMS if p in listing.apple_platforms()
                 or isinstance((S.get("platforms") or {}).get(p), dict)]
    codes = list(ours_codes)
    for c in list(live_app) + [c for P in (S.get("platforms") or {}).values() if isinstance(P, dict)
                               for c in (P.get("localizations") or {})]:
        if c not in codes:
            codes.append(c)
    urls = (listing.data.get("app") or {}).get("urls") or {}
    for code in codes:
        loc = ours_codes.get(code)
        theirs = live_app.get(code) or {}
        for field in APP_FIELDS:
            if field in not_public:
                continue
            if loc is None:
                ours = None
            elif field in ("name", "subtitle"):
                ours = listing.resolve(loc, "apple." + field)[0]
            else:
                ours = urls.get("privacy" if field == "privacyPolicyUrl" else "privacyChoices")
            if theirs.get(field) is None and ours is None:
                continue
            entries.append(Entry("apple", code, None, field, theirs.get(field), ours))
        for platform in platforms:
            P = (S.get("platforms") or {}).get(platform) or {}
            ours_here = loc is not None and platform in listing.apple_platforms() \
                and loc in listing.platform_locale_codes(platform)
            if isinstance((S.get("platforms") or {}).get(platform), dict) and code not in (P.get("localizations") or {}) \
                    and ours_here:
                ours = collections.OrderedDict()
                for field in VERSION_FIELDS:
                    value = listing.resolve(loc, "apple." + field, "apple", platform)[0]
                    if text(value):
                        ours[field] = value
                if ours:
                    entries.append(Entry("apple", code, platform, "listing", None, ours, "listing"))
                continue
            words = (P.get("localizations") or {}).get(code) or {}
            for field in VERSION_FIELDS:
                if field in not_public:
                    continue
                ours = listing.resolve(loc, "apple." + field, "apple", platform)[0] if ours_here else None
                if words.get(field) is None and ours is None:
                    continue
                entries.append(Entry("apple", code, platform, field, words.get(field), ours))
    cats_live = app.get("categories") or {}
    cats_ours = (listing.store("apple").get("categories") or {})
    for side in ("primary", "secondary"):
        if side + "Category" in not_public:
            continue
        if cats_live.get(side) is None and cats_ours.get(side) is None:
            continue
        entries.append(Entry("apple", None, None, side + " category", cats_live.get(side), cats_ours.get(side)))
    copyright_ = (listing.data.get("app") or {}).get("copyright")
    if "copyright" not in not_public:
        for platform in platforms:
            P = (S.get("platforms") or {}).get(platform) or {}
            if P.get("copyright") is None and copyright_ is None:
                continue
            entries.append(Entry("apple", None, platform, "copyright", P.get("copyright"), copyright_))
    entries.extend(_apple_pictures(listing, doc, report, ours_codes))
    return entries


def _apple_pictures(listing, doc, report, ours_codes):
    """Picture counts per platform, locale and slot, ours against live (the public lookup's sets are by device
    class: ours are counted by the class's largest slot)."""
    S = doc["apple"]
    entries = []
    slots = report.slots if report is not None else {}
    for platform in APPLE_PLATFORMS:
        P = (S.get("platforms") or {}).get(platform)
        live = (P or {}).get("screenshots") or {} if isinstance(P, dict) else {}
        codes = list(live) + [c for c in ours_codes if c not in live]
        for code in codes:
            loc = ours_codes.get(code)
            ours = {}
            if report is not None and loc is not None:
                for slot, pics in (report.pictures.get((platform, loc)) or {}).items():
                    ours[slot] = len(pics)
            theirs = dict((k, len(v or [])) for k, v in (live.get(code) or {}).items())
            if any(k in PUBLIC_SLOTS for k in theirs):
                by_class = collections.OrderedDict()
                for slot, n in ours.items():
                    kind = (slots.get(slot) or {}).get("kind")
                    cls = next((c for c, k in PUBLIC_SLOTS.items() if k == kind), slot)
                    by_class[cls] = max(by_class.get(cls, 0), n)
                ours = by_class
            for slot in list(theirs) + [s for s in ours if s not in theirs]:
                if not theirs.get(slot) and not ours.get(slot):
                    continue
                entries.append(Entry("apple", code, platform, slot, theirs.get(slot, 0), ours.get(slot, 0),
                                     "pictures", slot in listing.keep("apple")))
    return entries


def diff_google(listing, doc, report=None):
    """Play's entries: the contact details, each language's listing, and the pictures per image type."""
    S = doc["google"]
    entries = []
    contact = (listing.data.get("app") or {}).get("contact") or {}
    details = S.get("details") or {}
    for field, key in DETAIL_FIELDS:
        if details.get(field) is None and contact.get(key) is None:
            continue
        entries.append(Entry("google", None, None, field, details.get(field), contact.get(key)))
    ours_codes = collections.OrderedDict()
    if listing.store("google"):
        for loc in listing.store_locale_codes("google"):
            code = _store_code("google", loc)
            if code:
                ours_codes[code] = loc
    live = S.get("listings") or {}
    codes = list(ours_codes) + [c for c in live if c not in ours_codes]
    for code in codes:
        loc = ours_codes.get(code)
        theirs = live.get(code) or {}
        for field in LISTING_FIELDS:
            ours = listing.resolve(loc, "google." + field)[0] if loc is not None else None
            if theirs.get(field) is None and ours is None:
                continue
            entries.append(Entry("google", code, None, field, theirs.get(field), ours))
    images = S.get("images") or {}
    slots = report.slots if report is not None else {}
    for code in list(images) + [c for c in ours_codes if c not in images]:
        loc = ours_codes.get(code)
        ours = {}
        if report is not None and loc is not None:
            for slot, pics in (report.pictures.get((None, loc)) or {}).items():
                ours[(slots.get(slot) or {}).get("imageType") or slot] = len(pics)
        theirs = dict((k, len(v or [])) for k, v in (images.get(code) or {}).items())
        for image_type in GOOGLE_IMAGE_SLOTS:
            if not theirs.get(image_type) and not ours.get(image_type):
                continue
            entries.append(Entry("google", code, None, image_type, theirs.get(image_type, 0), ours.get(image_type, 0),
                                 "pictures", GOOGLE_IMAGE_SLOTS[image_type] in listing.keep("google")))
    return entries


def run_diff(config_path, existing, stores=None):
    """``(results, notes)``: ``results`` is ``{store: (folder, doc, [Entry])}`` for each pulled store."""
    import listing as listing_mod
    lst = listing_mod.load_listing(config_path)
    found = find(existing, tuple(stores or STORES))
    notes = []
    checks = {}
    try:
        report, _, checks = listing_mod.run_check(config_path, list(found))
        if not checks:
            notes.append("the config doesn't pass its schema, so our pictures weren't counted (listing.py check "
                         "says why)")
    except listing_mod.UsageError:
        checks = {}
    results = collections.OrderedDict()
    for store, (folder, doc) in found.items():
        if not lst.store(store):
            notes.append("the config has no stores.%s: everything live there shows as only live" % store)
        fn = diff_apple if store == "apple" else diff_google
        results[store] = (folder, doc, fn(lst, doc, checks.get(store)))
        if doc.get("notPublic"):
            notes.append("%s was pulled from the public lookup: %s aren't public, so they aren't compared"
                         % (folder, ", ".join(doc["notPublic"])))
    return results, notes


def cmd_diff(args):
    """``listing.py diff``: returns the exit code."""
    import listing as listing_mod
    stores = [s.strip() for s in args.stores.split(",")] if getattr(args, "stores", None) else None
    if stores:
        unknown = [s for s in stores if s not in STORES]
        if unknown:
            raise listing_mod.UsageError("unknown store %s (apple, google)" % ", ".join(unknown))
    try:
        results, notes = run_diff(args.config, args.existing, stores)
    except LiveError as e:
        raise listing_mod.UsageError(str(e))
    if args.json:
        out = collections.OrderedDict()
        out["stores"] = collections.OrderedDict()
        for store, (folder, doc, entries) in results.items():
            out["stores"][store] = collections.OrderedDict([
                ("existing", os.path.relpath(folder)), ("source", doc.get("source")), ("pulledAt", doc.get("pulledAt")),
                ("notPublic", doc.get("notPublic") or []), ("entries", [e.to_json() for e in entries])])
        out["notes"] = notes
        sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
        return listing_mod.EXIT_OK
    w = sys.stdout.write
    total = collections.Counter()
    for store, (folder, doc, entries) in results.items():
        w("%s: the config against what's live (%s, %s, pulled %s)\n" % (
            STORE_NAMES[store], os.path.relpath(folder), doc.get("source") or "?", doc.get("pulledAt") or "?"))
        group = None
        for e in entries:
            g = (e.locale or "(the whole app)") + (" pictures" if e.kind == "pictures" else "")
            if g != group:
                w("  %s\n" % g)
                group = g
            w("    %s\n" % e.line())
            total[e.status] += 1
        if not entries:
            w("  (nothing to compare)\n")
    w("Legend: = unchanged, ~ changed (live → ours), - only live (left as the store has it), + only ours\n")
    w("Summary: %d changed, %d unchanged, %d only live, %d only ours.\n" % (
        total["changed"], total["unchanged"], total["only-live"], total["only-ours"]))
    for n in notes:
        w("Note: %s\n" % n)
    w("Nothing was sent; this compares files. push.py plan reads the store itself before anything changes.\n")
    return listing_mod.EXIT_OK
