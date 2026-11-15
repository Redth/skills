"""``push.py pull``: read what's live on a store into ``existing/<store>/``. Read-only, like ``plan``.

    python3 push.py pull apple  [--out existing] [--config store-listing.json] [--id BUNDLE_ID] [--public]
                                [--country us,gb,de]
    python3 push.py pull google [--out existing] [--config store-listing.json] [--id PACKAGE]

With the store's key (the same environment variables ``plan`` uses) it reads the listing through the store's
API: App Store Connect's app information and each platform's version words, categories, age rating answers,
App Review's notes (never its contact), and the screenshots and previews per slot and locale; Google Play's
listings per language, contact details and images (inside an edit it opens and deletes, as ``plan`` does).
``--public`` (Apple only, no key) reads Apple's public iTunes Lookup API instead: the name, description,
release notes, categories, seller and the screenshots' URLs, per storefront country.

It writes ``existing/<store>/listing.json`` (the store's shape in the contract's ``listing.json`` vocabulary),
``existing/<store>/screenshots/<locale>/<slot>/<NN>.<ext>`` (and ``previews/``), and ``existing/<store>/README.md``.
Every request is a GET to the store's own hosts (``HOSTS``), but for Google's edit, which is opened and
deleted, never committed. Downloads follow redirects only to those hosts.
"""

from __future__ import annotations

import collections
import hashlib
import os
import re
import shutil
import sys
import tempfile
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appstores_lib import jsonio, locales, png, web  # noqa: E402

import push  # noqa: E402  (push.py makes this its own module when it runs)

LOOKUP = "https://itunes.apple.com/lookup"

# The hosts a pull may reach: the stores' APIs, Apple's public lookup, and the stores' own image hosts.
API_HOSTS = ("api.appstoreconnect.apple.com", "oauth2.googleapis.com", "androidpublisher.googleapis.com",
             "itunes.apple.com")
_MEDIA_HOST = re.compile(r"^([a-z0-9-]+\.)*mzstatic\.com$|^(play-lh|lh[0-9])\.googleusercontent\.com$")


def allowed(url):
    """True for an https URL on the stores' own hosts: their APIs, ``itunes.apple.com``, Apple's image and media
    CDN (``*.mzstatic.com``) and Play's image hosts (``play-lh.googleusercontent.com``, ``lhN.googleusercontent.com``)."""
    parts = urllib.parse.urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host in API_HOSTS or bool(_MEDIA_HOST.match(host)))


# The storefront country's language, as App Store Connect names it (``--country CC:locale`` says another).
COUNTRY_LOCALE = {
    "us": "en-US", "gb": "en-GB", "au": "en-AU", "ca": "en-CA", "nz": "en-AU", "ie": "en-GB", "de": "de-DE",
    "at": "de-DE", "ch": "de-DE", "fr": "fr-FR", "be": "fr-FR", "es": "es-ES", "mx": "es-MX", "it": "it", "jp": "ja",
    "kr": "ko", "cn": "zh-Hans", "tw": "zh-Hant", "hk": "zh-Hant", "br": "pt-BR", "pt": "pt-PT", "nl": "nl-NL",
    "se": "sv", "no": "no", "dk": "da", "fi": "fi", "pl": "pl", "cz": "cs", "sk": "sk", "hu": "hu", "ro": "ro",
    "gr": "el", "tr": "tr", "ru": "ru", "ua": "uk", "il": "he", "sa": "ar-SA", "th": "th", "vn": "vi", "id": "id",
    "my": "ms", "hr": "hr", "in": "hi"}

# Apple's public genre ids -> App Store Connect's category ids (iOS 60xx, Mac 12xxx, game genres 70xx)
GENRES = {
    6000: "BUSINESS", 6001: "WEATHER", 6002: "UTILITIES", 6003: "TRAVEL", 6004: "SPORTS", 6005: "SOCIAL_NETWORKING",
    6006: "REFERENCE", 6007: "PRODUCTIVITY", 6008: "PHOTO_AND_VIDEO", 6009: "NEWS", 6010: "NAVIGATION",
    6011: "MUSIC", 6012: "LIFESTYLE", 6013: "HEALTH_AND_FITNESS", 6014: "GAMES", 6015: "FINANCE",
    6016: "ENTERTAINMENT", 6017: "EDUCATION", 6018: "BOOKS", 6020: "MEDICAL", 6021: "MAGAZINES_AND_NEWSPAPERS",
    6023: "FOOD_AND_DRINK", 6024: "SHOPPING", 6025: "STICKERS", 6026: "DEVELOPER_TOOLS", 6027: "GRAPHICS_AND_DESIGN",
    12001: "BUSINESS", 12002: "DEVELOPER_TOOLS", 12003: "EDUCATION", 12004: "ENTERTAINMENT", 12005: "FINANCE",
    12006: "GAMES", 12007: "HEALTH_AND_FITNESS", 12008: "LIFESTYLE", 12010: "MEDICAL", 12011: "MUSIC", 12012: "NEWS",
    12013: "PHOTO_AND_VIDEO", 12014: "PRODUCTIVITY", 12015: "REFERENCE", 12016: "SOCIAL_NETWORKING",
    12017: "SPORTS", 12018: "TRAVEL", 12019: "UTILITIES", 12020: "PHOTO_AND_VIDEO", 12021: "WEATHER",
    12022: "GRAPHICS_AND_DESIGN"}
GAME_GENRES = {
    7001: "GAMES_ACTION", 7002: "GAMES_ADVENTURE", 7003: "GAMES_CASUAL", 7004: "GAMES_BOARD", 7005: "GAMES_CARD",
    7006: "GAMES_CASINO", 7009: "GAMES_FAMILY", 7011: "GAMES_MUSIC", 7012: "GAMES_PUZZLE", 7013: "GAMES_RACING",
    7014: "GAMES_ROLE_PLAYING", 7015: "GAMES_SIMULATION", 7016: "GAMES_SPORTS", 7017: "GAMES_STRATEGY",
    7018: "GAMES_TRIVIA", 7019: "GAMES_WORD"}

# What the public lookup never says (the config's names for them)
NOT_PUBLIC = ["subtitle", "keywords", "promotionalText", "supportUrl", "privacyPolicyUrl", "privacyChoicesUrl",
              "copyright", "ageRating answers", "review notes", "previews"]
# The lookup's picture lists -> (platform, our slot folder)
PUBLIC_SHOTS = (("screenshotUrls", "IOS", "iphone"), ("ipadScreenshotUrls", "IOS", "ipad"),
                ("appletvScreenshotUrls", "TV_OS", "apple-tv"))
# Play's image types, in Console order
GOOGLE_IMAGE_TYPES = ("phoneScreenshots", "sevenInchScreenshots", "tenInchScreenshots", "tvScreenshots",
                      "wearScreenshots", "icon", "featureGraphic", "tvBanner")
LIVE_STATES = frozenset(["READY_FOR_DISTRIBUTION", "READY_FOR_SALE"])
VERSION_FIELDS = ("description", "keywords", "promotionalText", "whatsNew", "marketingUrl", "supportUrl")
APP_INFO_FIELDS = ("name", "subtitle", "privacyPolicyUrl", "privacyChoicesUrl", "privacyPolicyText")
PULLED_BY = "push.py pull"


def od(*pairs):
    return collections.OrderedDict(pairs)


class ConfigAuth(object):
    """The config's ``stores.<store>.auth`` variable names (``push.Listing.auth``'s job, from the config)."""

    def __init__(self, data, path):
        self.data = data or {}
        self.path = path

    def auth(self, store, defaults):
        names = dict(defaults)
        found = ((self.data.get("stores") or {}).get(store) or {}).get("auth")
        for key, value in (found or {}).items():
            if key in names and isinstance(value, str) and value:
                names[key] = value
        return names


def _load_config(path):
    if not path or not os.path.isfile(path):
        return {}
    try:
        data = jsonio.load(path)
    except ValueError as e:
        raise push.Usage("%s isn't valid JSON: %s" % (path, e))
    return data if isinstance(data, dict) else {}


# ------------------------------------------------------------------------------------------ files


class Pulled(object):
    """The folder being written (a temporary one, swapped in at the end) and what went wrong on the way."""

    def __init__(self, out, store):
        self.final = os.path.join(out, store)
        self.store = store
        if os.path.exists(self.final):
            mine = os.path.join(self.final, "listing.json")
            ok = False
            if os.path.isfile(mine):
                try:
                    ok = jsonio.load(mine).get("pulledBy") == PULLED_BY
                except (ValueError, OSError, AttributeError):
                    ok = False
            if not ok and os.listdir(self.final):
                raise push.Usage("%s isn't a folder push.py pull wrote: it isn't replaced. Pull into another --out."
                                 % self.final)
        os.makedirs(out, exist_ok=True)
        self.dir = tempfile.mkdtemp(prefix=".%s-pulling-" % store, dir=out)
        self.failed = []
        self.notes = []
        self.downloaded = 0

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def download(self, url, rel_stem, ext=None):
        """GET a picture or video from the stores' hosts into ``<rel_stem>.<ext>``; ``(rel path, bytes)`` or
        ``(None, None)`` (noted) when it can't be had."""
        if not allowed(url):
            self.failed.append("%s: not one of the stores' hosts, not fetched (%s)" % (rel_stem, _host(url)))
            return None, None
        try:
            res = push.send("the store's image host", "GET", url, {"Accept": "*/*"}, retry=True, timeout=300)
        except push.Failure as e:
            self.failed.append("%s: %s" % (rel_stem, e.message))
            return None, None
        if res.status >= 400 or 300 <= res.status < 400:
            self.failed.append("%s: %s answered %d" % (rel_stem, _host(url), res.status))
            return None, None
        data = res.body
        ext = _extension(data, res.header("content-type"), url, ext)
        rel = "%s.%s" % (rel_stem, ext)
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        self.downloaded += 1
        return rel, data

    def size(self, rel):
        try:
            info = png.info(os.path.join(self.dir, rel))
            return info.width, info.height
        except (png.ImageError, OSError, ValueError):
            return None, None

    def finish(self, doc):
        """Write listing.json and README.md, then swap the folder in for the old one."""
        doc["failed"] = self.failed
        doc["notes"] = self.notes
        jsonio.dump(doc, os.path.join(self.dir, "listing.json"))
        with open(os.path.join(self.dir, "README.md"), "w", encoding="utf-8") as f:
            f.write(readme(doc))
        if os.path.exists(self.final):
            shutil.rmtree(self.final)
        os.replace(self.dir, self.final)

    def abandon(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _host(url):
    return urllib.parse.urlsplit(url or "").hostname or url


def _extension(data, content_type, url, fallback):
    if data[:8] == png.PNG_SIGNATURE:
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    ct = (content_type or "").split(";")[0].strip().lower()
    known = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4",
             "video/quicktime": "mov", "video/x-m4v": "m4v"}
    if ct in known:
        return known[ct]
    tail = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lstrip(".").lower()
    return {"jpeg": "jpg"}.get(tail, tail) or fallback or "bin"


def readme(doc):
    """``existing/<store>/README.md``: what was pulled, from where, and what to do with it."""
    import listing_live
    store = doc["store"]
    lines = ["# What's live on %s" % listing_live.STORE_NAMES[store], "",
             "Pulled by `push.py pull %s%s` on %s from %s. Read-only: nothing was sent to the store." % (
                 store, " --public" if doc.get("notPublic") else "", doc.get("pulledAt"), doc.get("source")), "",
             "```"]
    lines.extend(listing_live.describe(doc))
    lines += ["```", ""]
    if doc.get("notPublic"):
        lines += ["**Not in the public data:** %s. Pull with the store's key to read them (`references/existing.md`)."
                  % ", ".join(doc["notPublic"]), ""]
    if doc.get("notes"):
        lines += ["## Notes", ""] + ["- " + n for n in doc["notes"]] + [""]
    if doc.get("failed"):
        lines += ["## Not downloaded", ""] + ["- " + n for n in doc["failed"]] + [""]
    lines += ["## Next", "",
              "- `listing.py import --from live existing/` turns this into a draft `store-listing.json` (it never "
              "overwrites what the config already says).",
              "- `listing.py diff --existing existing/` shows what a new listing would change, field by field.",
              "- `screenshots/` is the current set: the starting point for new screenshots.",
              "- This folder is a snapshot: pull again to refresh it. Don't edit it; edit the config.", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------ App Store Connect


def _apple_live_first(items, state_of):
    """Items in the order a pull prefers them: what's live first (newest first), then the rest, newest first."""
    def created(i):
        return push.attrs(i).get("createdDate") or ""
    live = sorted([i for i in items if state_of(i) in LIVE_STATES or push.attrs(i).get("appStoreState") in LIVE_STATES],
                  key=created, reverse=True)
    rest = sorted([i for i in items if i not in live], key=created, reverse=True)
    return live + rest


def _template(asset, ext="png"):
    """An App Store Connect image asset's URL at its full size (``templateUrl`` with ``{w}``, ``{h}``, ``{f}``)."""
    asset = asset or {}
    url = asset.get("templateUrl") or ""
    if not url or not asset.get("width") or not asset.get("height"):
        return None
    return (url.replace("{w}", str(asset["width"])).replace("{h}", str(asset["height"]))
            .replace("{c}", "bb").replace("{f}", ext))


def pull_apple(client, ident, pulled):
    """Read App Store Connect (GETs only) into the pulled folder; returns the listing document."""
    if ident.isdigit():
        doc = client.get("/v1/apps/%s" % ident, ok404=True)
        apps = [doc["data"]] if doc and doc.get("data") else []
    else:
        apps = [a for a in client.get_all("/v1/apps?filter[bundleId]=%s&limit=200" % urllib.parse.quote(ident, safe=""))
                if push.attrs(a).get("bundleId") in (None, ident)]
    if not apps:
        raise push.Failure("No app %s in App Store Connect for this key's team: check the id (or the key's team)."
                           % ident)
    app = apps[0]
    app_id = app["id"]
    aa = push.attrs(app)
    out = od(("appId", app_id), ("bundleId", aa.get("bundleId") or (None if ident.isdigit() else ident)),
             ("primaryLocale", aa.get("primaryLocale")))

    infos = _apple_live_first(client.get_all("/v1/apps/%s/appInfos?limit=200" % app_id), push.info_state)
    app_section = od(("state", None), ("categories", od()), ("ageRating", od()), ("localizations", od()))
    if infos:
        info = infos[0]
        app_section["state"] = push.info_state(info)
        if len(infos) > 1:
            pulled.note("App Store Connect also has app information in %s: the pull read the %s one (what's live)"
                        % (", ".join(sorted(set(str(push.info_state(i)) for i in infos[1:]))), app_section["state"]))
        doc = client.get("/v1/appInfos/%s?include=%s" % (info["id"], ",".join(push.CATEGORY_RELATIONS))) or {}
        rels = ((doc.get("data") or {}).get("relationships")) or {}

        def cat(rel):
            data = (rels.get(rel) or {}).get("data")
            return data.get("id") if isinstance(data, dict) else None
        cats = app_section["categories"]
        for side in ("primary", "secondary"):
            cats[side] = cat(side + "Category")
            cats[side + "Subcategories"] = [s for s in (cat(side + "SubcategoryOne"), cat(side + "SubcategoryTwo")) if s]
        for l in client.get_all("/v1/appInfos/%s/appInfoLocalizations?limit=200" % info["id"]):
            la = push.attrs(l)
            app_section["localizations"][la.get("locale")] = od(*[(f, la.get(f)) for f in APP_INFO_FIELDS])
        rating = (client.get("/v1/appInfos/%s/ageRatingDeclaration" % info["id"], ok404=True) or {}).get("data")
        if rating:
            app_section["ageRating"] = od(*[(k, v) for k, v in sorted(push.attrs(rating).items())])
    out["app"] = app_section

    versions = client.get_all("/v1/apps/%s/appStoreVersions?limit=200" % app_id)
    by_platform = collections.OrderedDict()
    for v in versions:
        by_platform.setdefault(push.attrs(v).get("platform") or "IOS", []).append(v)
    platforms = od()
    review = None
    for platform in [p for p in ("IOS", "MAC_OS", "TV_OS", "VISION_OS") if p in by_platform]:
        ordered = _apple_live_first(by_platform[platform], push.version_state)
        version = ordered[0]
        va = push.attrs(version)
        state = push.version_state(version)
        preparing = [push.attrs(v).get("versionString") for v in ordered[1:] if push.version_state(v) in push.EDITABLE]
        if state not in LIVE_STATES:
            pulled.note("%s has no version on sale: the pull read version %s (%s)" % (platform, va.get("versionString"),
                                                                                       state))
        if preparing:
            pulled.note("%s also has version %s in preparation: its words may differ from what's live (the pull read "
                        "version %s, on sale)" % (platform, ", ".join(str(p) for p in preparing), va.get("versionString")))
        P = od(("version", va.get("versionString")), ("state", state), ("copyright", va.get("copyright")),
               ("localizations", od()), ("screenshots", od()), ("previews", od()))
        for l in client.get_all("/v1/appStoreVersions/%s/appStoreVersionLocalizations?limit=200" % version["id"]):
            la = push.attrs(l)
            loc = la.get("locale")
            P["localizations"][loc] = od(*[(f, la.get(f)) for f in VERSION_FIELDS])
            _apple_media(client, pulled, l["id"], loc, P)
        detail = (client.get("/v1/appStoreVersions/%s/appStoreReviewDetail" % version["id"], ok404=True)
                  or {}).get("data")
        if detail:
            da = push.attrs(detail)
            # Only the notes and whether a sign-in is needed: App Review's contact and demo account are personal.
            P["review"] = od(("notes", da.get("notes")), ("demoAccountRequired", da.get("demoAccountRequired")))
            if review is None:
                review = P["review"]
        platforms[platform] = P
    if not platforms:
        pulled.note("App Store Connect has no version of this app yet: only the app information was read")
    out["platforms"] = platforms
    out["review"] = review or od(("notes", None), ("demoAccountRequired", None))
    return od(("version", 1), ("store", "apple"), ("source", "App Store Connect"), ("pulledBy", PULLED_BY),
              ("pulledAt", push.now_utc()), ("apple", out))


def _apple_media(client, pulled, loc_id, loc, P):
    """A version localization's screenshots and previews, per slot, downloaded in their order."""
    for s in client.get_all("/v1/appStoreVersionLocalizations/%s/appScreenshotSets?limit=200" % loc_id):
        slot = push.attrs(s).get("screenshotDisplayType")
        items = []
        for i, shot in enumerate(client.get_all("/v1/appScreenshotSets/%s/appScreenshots?limit=200" % s["id"]), 1):
            sa = push.attrs(shot)
            asset = sa.get("imageAsset") or {}
            stem = "screenshots/%s/%s/%02d" % (loc, slot, i)
            url = _template(asset)
            rel, data = pulled.download(url, stem, "png") if url else (None, None)
            if url is None:
                pulled.failed.append("%s: App Store Connect gave no picture address (still processing?)" % stem)
            entry = od(("file", rel), ("fileName", sa.get("fileName")), ("width", asset.get("width")),
                       ("height", asset.get("height")), ("md5", (sa.get("sourceFileChecksum") or "").lower() or None))
            if data is not None:
                entry["downloadedMd5"] = hashlib.md5(data).hexdigest()
            items.append(entry)
        if items:
            P["screenshots"].setdefault(loc, od())[slot] = items
    for s in client.get_all("/v1/appStoreVersionLocalizations/%s/appPreviewSets?limit=200" % loc_id):
        slot = push.attrs(s).get("previewType")
        items = []
        for i, prev in enumerate(client.get_all("/v1/appPreviewSets/%s/appPreviews?limit=200" % s["id"]), 1):
            pa = push.attrs(prev)
            stem = "previews/%s/%s/%02d" % (loc, slot, i)
            url = pa.get("videoUrl")
            rel = None
            if url and urllib.parse.urlsplit(url).path.lower().endswith(".m3u8"):
                pulled.note("%s is a streaming playlist, not a file: not downloaded (its address is in "
                            "listing.json)" % stem)
            elif url:
                rel, _ = pulled.download(url, stem, "mp4")
            items.append(od(("file", rel), ("url", url if rel is None else None), ("fileName", pa.get("fileName")),
                            ("posterFrame", pa.get("previewFrameTimeCode")), ("mime", pa.get("mimeType")),
                            ("md5", (pa.get("sourceFileChecksum") or "").lower() or None)))
        if items:
            P["previews"].setdefault(loc, od())[slot] = items


# ------------------------------------------------------------------------------------------ the public lookup


def parse_countries(value):
    """``us,gb,ca:fr-CA`` -> ``[(country, BCP 47 locale)]``; an unknown country needs ``CC:locale``."""
    out = []
    for part in [p.strip() for p in (value or "us").split(",") if p.strip()]:
        cc, _, loc = part.partition(":")
        cc = cc.strip().lower()
        if not re.match(r"^[a-z]{2}$", cc):
            raise push.Usage("--country %s: a storefront is a two-letter country code (us, gb, de), optionally "
                             "with its language (ca:fr-CA)." % part)
        loc = loc.strip() or COUNTRY_LOCALE.get(cc)
        if not loc:
            raise push.Usage("--country %s: say which language that storefront's words are in, as %s:<locale> "
                             "(e.g. %s:en-GB)." % (cc, cc, cc))
        try:
            locales.apple(loc)
        except locales.LocaleError as e:
            raise push.Usage("--country %s: %s" % (part, e))
        out.append((cc, locales.canonical(loc)))
    return out


def _lookup(ident, country, entity=None):
    query = [("id" if ident.isdigit() else "bundleId", ident), ("country", country)]
    if entity:
        query.append(("entity", entity))
    url = LOOKUP + "?" + urllib.parse.urlencode(query)
    res = push.send("Apple's iTunes Lookup", "GET", url, {"Accept": "application/json"}, retry=True)
    if res.status >= 400:
        raise push.StoreError("Apple's iTunes Lookup", res.status, "GET", url, res.text())
    try:
        data = res.json() or {}
    except ValueError:
        raise push.StoreError("Apple's iTunes Lookup", res.status, "GET", url, "the answer isn't JSON: " + res.text()[:300])
    return [r for r in (data.get("results") or []) if isinstance(r, dict)
            and r.get("kind") in ("software", "mac-software", None)]


def _genres(result):
    """App Store Connect's categories from a lookup result's genre ids (the first is the primary)."""
    ids = []
    for g in [result.get("primaryGenreId")] + list(result.get("genreIds") or []):
        try:
            ids.append(int(g))
        except (TypeError, ValueError):
            continue
    primary = GENRES.get(ids[0]) if ids else None
    subs = [GAME_GENRES[i] for i in ids if i in GAME_GENRES][:2] if primary == "GAMES" else []
    others = [GENRES[i] for i in ids[1:] if i in GENRES and GENRES[i] != primary]
    return od(("primary", primary), ("primarySubcategories", subs), ("secondary", others[0] if others else None),
              ("secondarySubcategories", []))


def _uploaded_name(url):
    """The uploaded file's name an mzstatic URL carries (``…/iPhone_1_Hero.png/320x480bb.jpg``), or None."""
    parts = [urllib.parse.unquote(p) for p in urllib.parse.urlsplit(url or "").path.split("/") if p]
    if len(parts) >= 2 and re.search(r"\.(png|jpe?g)$", parts[-2], re.IGNORECASE):
        return parts[-2]
    return None


def pull_public(ident, countries, pulled):
    """Read Apple's public lookup, one storefront country at a time, into the pulled folder."""
    out = od(("appId", None), ("bundleId", None if ident.isdigit() else ident), ("primaryLocale", None))
    app = od(("state", "READY_FOR_SALE"), ("categories", od()), ("ageRating", od()), ("localizations", od()))
    platforms = od()
    public = od()
    seen_words = {}
    for cc, loc in countries:
        results = _lookup(ident, cc)
        if not results:
            results = _lookup(ident, cc, "macSoftware")
        if not results:
            pulled.note("%s: the %s storefront has no app %s (not sold there, or not live yet)" % (cc, cc, ident))
            continue
        r = results[0]
        code = locales.apple(loc)
        words = (r.get("trackName"), r.get("description"), r.get("releaseNotes"))
        if words in seen_words.values():
            first = next(c for c, w in seen_words.items() if w == words)
            pulled.note("%s's words are the same as %s's: the app probably has no %s listing (the storefront shows "
                        "another language's), so it's left out" % (cc, first, loc))
            continue
        seen_words[cc] = words
        if out["appId"] is None:
            out["appId"] = str(r.get("trackId")) if r.get("trackId") else None
            out["bundleId"] = r.get("bundleId") or out["bundleId"]
            out["primaryLocale"] = code
            app["categories"] = _genres(r)
            if app["categories"]["primary"] is None:
                pulled.note("the genre %r isn't one this pull knows: set stores.apple.categories.primary by hand"
                            % r.get("primaryGenreName"))
        platform = "MAC_OS" if r.get("kind") == "mac-software" else "IOS"
        app["localizations"][code] = od(("name", r.get("trackName")))
        P = platforms.setdefault(platform, od(("version", r.get("version")), ("state", "READY_FOR_SALE"),
                                              ("copyright", None), ("localizations", od()), ("screenshots", od()),
                                              ("previews", od())))
        P["localizations"][code] = od(("description", r.get("description")), ("whatsNew", r.get("releaseNotes")),
                                      ("marketingUrl", r.get("sellerUrl")))
        public[cc] = od(("locale", code), ("trackViewUrl", r.get("trackViewUrl")), ("sellerName", r.get("sellerName")),
                        ("artistName", r.get("artistName")), ("sellerUrl", r.get("sellerUrl")),
                        ("version", r.get("version")), ("releaseDate", r.get("currentVersionReleaseDate")),
                        ("genres", r.get("genres")), ("contentAdvisoryRating", r.get("contentAdvisoryRating")),
                        ("advisories", r.get("advisories")), ("languages", r.get("languageCodesISO2A")),
                        ("formattedPrice", r.get("formattedPrice")), ("artworkUrl512", r.get("artworkUrl512")))
        for key, plat, slot in PUBLIC_SHOTS:
            if platform == "MAC_OS" and key == "screenshotUrls":
                plat, slot = "MAC_OS", "mac"
            urls = [u for u in (r.get(key) or []) if isinstance(u, str)]
            if not urls:
                continue
            items = []
            for i, url in enumerate(urls, 1):
                rel, data = pulled.download(url, "screenshots/%s/%s/%02d" % (code, slot, i))
                w, h = pulled.size(rel) if rel else (None, None)
                items.append(od(("file", rel), ("url", url), ("fileName", _uploaded_name(url)), ("width", w),
                                ("height", h)))
            target = platforms.setdefault(plat, od(("version", r.get("version")), ("state", "READY_FOR_SALE"),
                                                   ("copyright", None), ("localizations", od()), ("screenshots", od()),
                                                   ("previews", od())))
            target["screenshots"].setdefault(code, od())[slot] = items
    if out["appId"] is None:
        raise push.Failure("Apple's public lookup has no app %s in %s: it may not be live, or not in those "
                           "storefronts (try --country)." % (ident, ", ".join(c for c, _ in countries)))
    pulled.note("The public pictures are the App Store web page's copies, at the size that page shows (often smaller "
                "than the uploads), so they're a reference for the current set, not files to send again")
    pulled.note("The public data doesn't say which display type a picture fills: its slot folders are by device "
                "(iphone, ipad, apple-tv, mac)")
    if app["categories"].get("primary"):
        pulled.note("The categories come from the public genres (%s): check them in App Store Connect"
                    % ", ".join(public[next(iter(public))].get("genres") or []))
    out["app"] = app
    out["platforms"] = platforms
    out["review"] = od(("notes", None), ("demoAccountRequired", None))
    return od(("version", 1), ("store", "apple"), ("source", "iTunes Lookup (public)"), ("pulledBy", PULLED_BY),
              ("pulledAt", push.now_utc()), ("notPublic", list(NOT_PUBLIC)), ("apple", out), ("public", public))


# ------------------------------------------------------------------------------------------ Google Play


def pull_google(client, edit_id, pulled):
    """Read Play's listing inside an open edit (GETs only) into the pulled folder."""
    base = client.edit_url(edit_id)
    details = client.call("GET", base + "/details") or {}
    out = od(("package", client.package), ("defaultLanguage", details.get("defaultLanguage")),
             ("details", od(("contactEmail", details.get("contactEmail")),
                            ("contactWebsite", details.get("contactWebsite")),
                            ("contactPhone", details.get("contactPhone")))),
             ("listings", od()), ("images", od()))
    found = (client.call("GET", base + "/listings") or {}).get("listings") or []
    order = sorted(found, key=lambda l: (l.get("language") != out["defaultLanguage"], l.get("language") or ""))
    for l in order:
        lang = l.get("language")
        out["listings"][lang] = od(("title", l.get("title")), ("shortDescription", l.get("shortDescription")),
                                   ("fullDescription", l.get("fullDescription")), ("video", l.get("video")))
        types = od()
        for image_type in GOOGLE_IMAGE_TYPES:
            got = client.call("GET", "%s/listings/%s/%s" % (base, urllib.parse.quote(lang, safe=""), image_type),
                              ok404=True) or {}
            items = []
            for i, image in enumerate(got.get("images") or [], 1):
                stem = "screenshots/%s/%s/%02d" % (lang, image_type, i)
                rel, data = pulled.download(image.get("url"), stem, "png") if image.get("url") else (None, None)
                w, h = pulled.size(rel) if rel else (None, None)
                entry = od(("file", rel), ("sha256", (image.get("sha256") or "").lower() or None), ("width", w),
                           ("height", h))
                if data is not None:
                    entry["downloadedSha256"] = hashlib.sha256(data).hexdigest()
                items.append(entry)
            if items:
                types[image_type] = items
        out["images"][lang] = types
    pulled.note("Play Console only (not in the API, so not pulled): the category, tags, content rating, target "
                "audience, the feature graphic's alt text, and release notes (they're a release's, on a track)")
    return od(("version", 1), ("store", "google"), ("source", "Google Play Developer API"), ("pulledBy", PULLED_BY),
              ("pulledAt", push.now_utc()), ("google", out))


# ------------------------------------------------------------------------------------------ the command


def cmd_pull(args):
    store = args.store
    config = _load_config(args.config)
    ids = (config.get("app") or {}).get("ids") or {}
    if store == "google" and args.public:
        raise push.Usage("Google Play has no public API for a listing: pull google needs the service account's key "
                         "(GOOGLE_PLAY_SERVICE_ACCOUNT, as plan uses). Without one, paste the listing's words from "
                         "Play Console into the config by hand.")
    if args.country and not (store == "apple" and args.public):
        raise push.Usage("--country is for pull apple --public (a storefront's public words).")
    ident = args.id or ((ids.get("apple") or {}).get("bundleId") or (ids.get("apple") or {}).get("appId")
                        if store == "apple" else (ids.get("google") or {}).get("package"))
    if not ident:
        raise push.Usage("Which app? Pass --id (%s), or point --config at a store-listing.json with %s."
                         % ("the bundle id, or Apple's numeric app id" if store == "apple" else "the package name",
                            "app.ids.apple.bundleId" if store == "apple" else "app.ids.google.package"))
    ident = str(ident).strip()
    auth = ConfigAuth(config, args.config)
    if store == "apple" and not args.public:
        names = auth.auth("apple", push.APPLE_ENV)
        if not all(os.environ.get(names[k]) for k in ("keyIdEnv", "issuerIdEnv", "privateKeyEnv")):
            missing = [names[k] for k in ("keyIdEnv", "issuerIdEnv", "privateKeyEnv") if not os.environ.get(names[k])]
            raise push.Usage("%s %s set, so App Store Connect can't be read. Set the key (references/apple.md, Keys "
                             "and roles), or pull what the App Store shows anyone: push.py pull apple --public (no "
                             "subtitle, keywords or promotional text: they aren't public)."
                             % (", ".join(missing), "isn't" if len(missing) == 1 else "aren't"))
    countries = parse_countries(args.country) if store == "apple" and args.public else None
    pulled = Pulled(args.out, store)
    old_guard = getattr(web, "REDIRECT_ALLOWED", None)
    try:
        web.REDIRECT_ALLOWED = allowed
        if store == "apple" and args.public:
            say("Reading the App Store's public pages (%s; %s)..." % (ident, ", ".join(c for c, _ in countries)))
            doc = pull_public(ident, countries, pulled)
        elif store == "apple":
            client = push.AppleClient.from_env(auth)
            say("Reading the store (%s, App Store Connect)..." % ident)
            doc = pull_apple(client, ident, pulled)
        else:
            client = push.GoogleClient.from_env(auth, ident)
            say("Reading the store (%s, Google Play)..." % ident)
            edit_id = client.open_edit()
            try:
                doc = pull_google(client, edit_id, pulled)
            finally:
                client.delete_edit(edit_id, "opened to read wasn't committed")
            pulled.note("To read the listing, pull opened a Play edit and deleted it: nothing was committed or "
                        "changed. Play keeps one open edit an app, so don't pull while another tool is sending.")
        pulled.finish(doc)
    except BaseException:
        pulled.abandon()
        raise
    finally:
        web.REDIRECT_ALLOWED = old_guard
    import listing_live
    for line in listing_live.describe(doc):
        say(line)
    for n in doc.get("notes") or []:
        say("Note: " + n)
    say("Wrote %s (listing.json, README.md, %d downloaded). Nothing was sent to the store." % (
        pulled.final, pulled.downloaded))
    say("Next: listing.py import --from live %s, then listing.py diff --existing %s" % (args.out, args.out))
    if doc.get("failed"):
        for f in doc["failed"]:
            push.warn("Not downloaded: " + f)
        push.warn("%d file%s couldn't be downloaded (listed in %s/README.md); the words were written."
                  % (len(doc["failed"]), "" if len(doc["failed"]) == 1 else "s", pulled.final))
        return 1
    return 0


def say(text):
    push.say(text)
