#!/usr/bin/env python3
"""Look at what a store has, plan what would change, and apply exactly that plan.

    python3 push.py plan apple  [--out out] [--plan plan-apple.json] [--age-rating] [--new-version 1.2.0]
    python3 push.py plan google [--out out] [--plan plan-google.json]
    python3 push.py apply <plan file> [--cancel-review]

``plan`` reads ``out/listing.json`` (written by ``listing.py build``) and the store, writes the plan file and
prints it. It never writes to a store: on Google Play it opens an edit to read (the API needs one) and deletes
it before returning, never committing.

``apply`` refuses (exit 2) when ``out/listing.json``, a picture or the App Review contact in the environment
changed since the plan, or when the store's values the plan compared against changed (its fingerprint). Then it
performs exactly the plan's actions in order and reports each. Google Play commits with
``changesInReviewBehavior=ERROR_IF_IN_REVIEW`` unless ``--cancel-review``.

Exit codes: 0 done; 1 a store's error (printed as it came) or a stale build; 2 a refusal; 3 usage or
environment (a missing key, openssl). Keys come only from environment variables and are never printed.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime
import hashlib
import hmac
import http.client
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appstores_lib import jsonio, jwt, web  # noqa: E402

APPLE_API = "https://api.appstoreconnect.apple.com"
GOOGLE_API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
GOOGLE_UPLOAD = "https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/androidpublisher"

# App Store Connect's states in which a version or an app info can be edited.
EDITABLE = frozenset(["PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED",
                      "INVALID_BINARY"])
# A version on sale (appVersionState, then the deprecated appStoreState): its promotional text changes any time.
LIVE = frozenset(["READY_FOR_DISTRIBUTION", "READY_FOR_SALE"])

APPLE_ENV = {"keyIdEnv": "ASC_KEY_ID", "issuerIdEnv": "ASC_ISSUER_ID", "privateKeyEnv": "ASC_PRIVATE_KEY"}
GOOGLE_ENV = {"serviceAccountEnv": "GOOGLE_PLAY_SERVICE_ACCOUNT"}

POLL_SECONDS = 5
TOKEN_REUSE_SECONDS = 15 * 60

APP_INFO_FIELDS = (("name", "name"), ("subtitle", "subtitle"), ("privacyPolicyUrl", "privacy policy URL"),
                   ("privacyChoicesUrl", "privacy choices URL"), ("privacyPolicyText", "Apple TV privacy text"))
VERSION_FIELDS = (("description", "description"), ("keywords", "keywords"),
                  ("promotionalText", "promotional text"), ("whatsNew", "What's New"),
                  ("marketingUrl", "marketing URL"), ("supportUrl", "support URL"))
CATEGORY_RELATIONS = ("primaryCategory", "primarySubcategoryOne", "primarySubcategoryTwo",
                      "secondaryCategory", "secondarySubcategoryOne", "secondarySubcategoryTwo")
REVIEW_CONTACT = (("contactFirstName", "firstNameEnv", "first name"),
                  ("contactLastName", "lastNameEnv", "last name"),
                  ("contactPhone", "phoneEnv", "phone"),
                  ("contactEmail", "emailEnv", "email"))
REVIEW_PRIVATE = ("contactFirstName", "contactLastName", "contactPhone", "contactEmail", "demoAccountName",
                  "demoAccountPassword")
LISTING_FIELDS = (("title", "title"), ("shortDescription", "short description"),
                  ("fullDescription", "full description"), ("video", "video"))
DETAIL_FIELDS = (("contactEmail", "contact email"), ("contactWebsite", "website"), ("contactPhone", "phone"))
IMAGE_NAMES = {
    "phoneScreenshots": ("phone screenshot", "phone screenshots"),
    "sevenInchScreenshots": ("7-inch tablet screenshot", "7-inch tablet screenshots"),
    "tenInchScreenshots": ("10-inch tablet screenshot", "10-inch tablet screenshots"),
    "tvScreenshots": ("TV screenshot", "TV screenshots"),
    "wearScreenshots": ("Wear OS screenshot", "Wear OS screenshots"),
    "icon": ("icon", "icons"),
    "featureGraphic": ("feature graphic", "feature graphics"),
    "tvBanner": ("TV banner", "TV banners"),
}
PREVIEW_MIME = {".mp4": "video/mp4", ".m4v": "video/x-m4v", ".mov": "video/quicktime"}


class Asset(object):
    """What App Store Connect keeps in sets, one set a slot: screenshots or previews (videos)."""

    def __init__(self, name, sets, items, type_field, set_relation, capacity, wait, prefix):
        self.name = name
        self.sets = sets
        self.items = items
        self.type_field = type_field
        self.set_relation = set_relation
        self.capacity = capacity        # the most a set holds (10 screenshots, 3 previews)
        self.wait = wait                # seconds to wait for processing (previews take longer: less is awaited)
        self.prefix = prefix            # the action kinds' prefix


SCREENSHOTS = Asset("screenshot", "appScreenshotSets", "appScreenshots", "screenshotDisplayType",
                    "appScreenshotSet", 10, 300, "apple.screenshots")
PREVIEWS = Asset("preview", "appPreviewSets", "appPreviews", "previewType", "appPreviewSet", 3, 120,
                 "apple.previews")


# ------------------------------------------------------------------------------------------ errors and output

class Exit(Exception):
    """Stop with an exit code and a message (printed to stderr)."""

    code = 1

    def __init__(self, message):
        super(Exit, self).__init__(message)
        self.message = message
        self.after = []  # lines printed after the message (what happened to the edit, what to do)


class Usage(Exit):
    """Usage or environment: a missing key, file or program (exit 3)."""

    code = 3


class Refusal(Exit):
    """``apply`` refusing because something changed since the plan (exit 2)."""

    code = 2


class Failure(Exit):
    """A failure that isn't a store's answer, such as a stale build or a picture App Store Connect refused (exit 1)."""

    code = 1


class StoreError(Exception):
    """A store's error answer, kept as it came."""

    def __init__(self, store, status, method, url, body):
        self.store = store
        self.status = status
        self.method = method
        self.url = url
        self.body = body
        self.after = []  # lines printed after the error as it came
        super(StoreError, self).__init__("%s answered %d" % (store, status))

    def reason(self):
        """Google's ``error.status`` (e.g. ``FAILED_PRECONDITION``), or ``None``."""
        try:
            data = json.loads(self.body)
        except ValueError:
            return None
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            status = data["error"].get("status")
            return status if isinstance(status, str) else None
        return None

    def report(self):
        """The error as it came: the store, the status, what was asked, and the body untouched."""
        reason = self.reason()
        head = "%s answered %d%s:" % (self.store, self.status, " " + reason if reason else "")
        body = self.body.strip() or "(an empty answer)"
        lines = [head, "  (%s %s)" % (self.method, _shown_url(self.url))]
        lines.extend("  " + line for line in body.splitlines())
        return "\n".join(lines)


def _shown_url(url):
    """A URL as printed (no fragment; the stores' URLs carry no secrets: tokens go in headers)."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def say(text=""):
    """Progress and results, to stdout."""
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def warn(text):
    """Warnings and errors, to stderr."""
    sys.stdout.flush()
    sys.stderr.write(text + "\n")
    sys.stderr.flush()


def hint_for(error):
    """What a store's error usually means, as a line after it (or ``None``)."""
    body = error.body
    if "CHANGES_ALREADY_IN_REVIEW" in body or "changes already in review" in body.lower():
        return ("Something is already in review on Google Play, and this apply asked Play to stop rather than cancel "
                "it. Choose: wait for the review to finish, then plan and apply again; or apply again with "
                "--cancel-review, which cancels what's in review (a release included) and resubmits it with these "
                "changes. That choice is yours.")
    if "accessNotConfigured" in body or "SERVICE_DISABLED" in body:
        return ("The Google Play Android Developer API isn't enabled in the service account's Cloud project "
                "(references/google.md, Service account and permissions).")
    if "caller does not have permission" in body.lower():
        return ("The service account lacks the Play Console permission for this app (Manage store presence; Manage "
                "policy declarations for Data safety), or wasn't invited for it.")
    if "edit has expired" in body.lower() or "editAlreadyCommitted" in body or "editNotFound" in body:
        return ("Another tool opened or committed an edit for this app meanwhile (Play keeps one open edit an app): "
                "run one sender at a time, then plan again.")
    if error.store == "App Store Connect" and error.status == 401:
        return "A 401 is usually the key id, the issuer id, the key itself or this machine's clock."
    if error.store == "App Store Connect" and error.status == 403:
        return "A 403 is usually the key's role: it must be App Manager or Admin."
    if error.store == "Google's sign-in":
        return "Google turned the service account's key down: check GOOGLE_PLAY_SERVICE_ACCOUNT and this machine's clock."
    return None


# ------------------------------------------------------------------------------------------ small helpers

def norm(value):
    """Text as the stores keep it: ``None`` as empty, line endings normalised, the ends trimmed."""
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def norm_keywords(value):
    return ",".join(part.strip() for part in norm(value).split(","))


def differs(theirs, ours, field=None):
    """Whether two texts differ as the stores compare them."""
    if field == "keywords":
        return norm_keywords(theirs) != norm_keywords(ours)
    return norm(theirs) != norm(ours)


def short(value):
    """A value quoted for a summary, at most 60 characters."""
    text = norm(value).replace("\n", " ")
    if not text:
        return "(none)"
    if len(text) > 60:
        text = text[:57] + "…"
    return "'%s'" % text


def masked_phone(value):
    """A phone number with only its last 4 digits."""
    digits = "".join(c for c in str(value or "") if c.isdigit())
    if not digits:
        return "(none)"
    return "'…%s'" % digits[-4:]


def digest(obj):
    """SHA-256 of an object's canonical JSON."""
    return hashlib.sha256(jsonio.canonical(obj).encode("utf-8")).hexdigest()


def attrs(resource):
    return (resource or {}).get("attributes") or {}


def plural(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resource(type_, id_=None, attributes=None, relationships=None):
    data = {"type": type_}
    if id_ is not None:
        data["id"] = id_
    if attributes is not None:
        data["attributes"] = attributes
    if relationships is not None:
        data["relationships"] = relationships
    return {"data": data}


def to(type_, id_):
    return {"data": {"type": type_, "id": id_}}


def send(store, method, url, headers=None, body=None, retry=None, timeout=120):
    """One request through ``web.request``; a connection that fails every try becomes a ``Failure``.

    ``retry`` defaults to idempotent methods only: a POST that creates something or commits isn't sent twice.
    """
    if retry is None:
        retry = method in ("GET", "PUT", "PATCH", "DELETE")
    try:
        return web.request(method, url, headers=headers, body=body, timeout=timeout, retry=retry)
    except (OSError, http.client.HTTPException) as e:
        tries = " (%d tries)" % web.TRIES if retry else ""
        raise Failure("%s: %s %s failed: %s%s" % (store, method, _shown_url(url), e, tries))


# ------------------------------------------------------------------------------------------ what was compared

class Seen(object):
    """The store's values the plan compared against, by a readable key; the fingerprint is their hash.

    Private values (App Review's contact and demo account) go in as an HMAC keyed with the store key's own
    hash, so neither the fingerprint nor the plan file can be guessed back to a phone number.
    """

    def __init__(self, secret=b""):
        self.values = {}
        self.counts = {}
        self.secret = secret

    def put(self, key, value, count=None, private=False):
        if private:
            value = {"hmac": hmac.new(self.secret, jsonio.canonical(value).encode("utf-8"), hashlib.sha256).hexdigest()}
        self.values[key] = value
        if count is not None:
            self.counts[key] = count

    def fingerprint(self):
        return digest(self.values)

    def compared(self):
        out = {}
        for key in sorted(self.values):
            entry = {"sha256": digest(self.values[key])}
            if key in self.counts:
                entry["count"] = self.counts[key]
            out[key] = entry
        return out


def explain_difference(then, now):
    """Lines naming what differs between two ``compared`` maps."""
    lines = []
    for key in sorted(set(then) | set(now)):
        a, b = then.get(key), now.get(key)
        if a == b:
            continue
        if a is None:
            lines.append("%s is there now and wasn't when the plan was made" % key)
        elif b is None:
            lines.append("%s is gone since the plan was made" % key)
        elif "count" in a and "count" in b and a["count"] != b["count"]:
            lines.append("%s: %s then, %d now" % (key, plural(a["count"], "picture"), b["count"]))
        else:
            lines.append("%s differs from when the plan was made" % key)
    return lines


class Plan(object):
    """The actions, what's unchanged and the notes, as a survey of the store finds them."""

    def __init__(self):
        self.actions = []
        self.unchanged = []
        self.notes = []

    def add(self, kind, summary, **fields):
        action = {"id": len(self.actions) + 1, "kind": kind}
        for key in ("platform", "locale", "displayType", "previewType", "imageType"):
            if key in fields:
                action[key] = fields.pop(key)
        action["summary"] = summary
        action.update(fields)
        self.actions.append(action)
        return action

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)


def where(action):
    """The platform, locale and slot an action is about, for its printed line."""
    parts = [action.get(k) for k in ("platform", "locale", "displayType", "previewType", "imageType")]
    return " ".join(p for p in parts if p)


# ------------------------------------------------------------------------------------------ the listing

class Listing(object):
    """``out/listing.json`` and the files it names (paths relative to its folder)."""

    def __init__(self, path):
        self.path = path
        if not os.path.isfile(path):
            raise Usage("No %s: run listing.py build first (it writes out/listing.json)." % path)
        try:
            self.data = jsonio.load(path)
        except ValueError as e:
            raise Usage("%s isn't valid JSON: %s" % (path, e))
        with open(path, "rb") as f:
            self.sha256 = hashlib.sha256(f.read()).hexdigest()
        self.folder = os.path.dirname(os.path.abspath(path))
        self._hashes = {}

    def section(self, store):
        data = self.data.get(store)
        if not isinstance(data, dict):
            raise Usage("%s has no %s section: is stores.%s enabled in the config? Run listing.py build again."
                        % (self.path, store, store))
        return data

    def file(self, rel):
        path = rel if os.path.isabs(rel) else os.path.join(self.folder, rel)
        if not os.path.isfile(path):
            raise Failure("%s names %s, which isn't there: run listing.py build again." % (self.path, rel))
        return path

    def hash(self, rel, algo):
        key = (rel, algo)
        if key not in self._hashes:
            h = hashlib.new(algo)
            with open(self.file(rel), "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            self._hashes[key] = h.hexdigest()
        return self._hashes[key]

    def checked(self, entry, algo):
        """A picture entry's hash from the file itself; a stale hash in the listing stops the plan."""
        rel = entry["file"] if isinstance(entry, dict) else entry
        actual = self.hash(rel, algo)
        said = entry.get(algo) if isinstance(entry, dict) else None
        if said and said.lower() != actual:
            raise Failure("%s says %s's %s is %s, but the file's is %s: run listing.py build again."
                          % (self.path, rel, algo.upper(), said, actual))
        return actual

    def _config_paths(self):
        """Where the config may be: ``config`` is relative to out/'s parent (listing.py build), else to here."""
        config = self.data.get("config")
        if not isinstance(config, str) or not config:
            return []
        if os.path.isabs(config):
            return [config]
        return [os.path.join(os.path.dirname(self.folder), config), config]

    def side_file(self, rel):
        """A file the listing names that may sit beside out/ (the Data safety CSV, the Apple TV privacy text)."""
        if os.path.isabs(rel):
            candidates = [rel]
        else:
            candidates = [os.path.join(self.folder, rel)]
            candidates += [os.path.join(os.path.dirname(os.path.abspath(c)), rel) for c in self._config_paths()]
            candidates.append(os.path.join(os.path.dirname(self.folder), rel))
        for path in candidates:
            if os.path.isfile(path):
                return path
        raise Failure("%s names %s, which isn't there (looked in out/ and beside the config)." % (self.path, rel))

    def auth(self, store, defaults):
        """The environment variable names for a store's key: the listing's or the config's ``auth``, or the defaults."""
        names = dict(defaults)
        found = self.section(store).get("auth")
        if not isinstance(found, dict):
            for path in self._config_paths():
                if os.path.isfile(path):
                    try:
                        found = ((jsonio.load(path).get("stores") or {}).get(store) or {}).get("auth")
                    except (ValueError, OSError, AttributeError):
                        found = None
                    break
        for key, value in (found or {}).items():
            if key in names and isinstance(value, str) and value:
                names[key] = value
        return names


# ------------------------------------------------------------------------------------------ App Store Connect

class AppleClient(object):
    """App Store Connect's API with a 20-minute ES256 token, signed by openssl."""

    store = "App Store Connect"

    def __init__(self, key_id, issuer, pem):
        self.key_id = key_id
        self.issuer = issuer
        self.pem = pem
        self.secret = hashlib.sha256(pem.encode("utf-8")).digest()
        self._token = None
        self._made = 0.0

    @classmethod
    def from_env(cls, listing):
        names = listing.auth("apple", APPLE_ENV)
        missing = [names[k] for k in ("keyIdEnv", "issuerIdEnv", "privateKeyEnv") if not os.environ.get(names[k])]
        if missing:
            raise Usage("%s %s set: export the App Store Connect API key's id, its issuer id and the .p8 key (a path, "
                        "its text, or base64) from App Store Connect ▸ Users and Access ▸ Integrations "
                        "(references/apple.md, Keys and roles)." % (", ".join(missing),
                                                                     "isn't" if len(missing) == 1 else "aren't"))
        try:
            pem = jwt.load_key(os.environ[names["privateKeyEnv"]])
        except jwt.KeyProblem as e:
            raise Usage("%s: %s." % (names["privateKeyEnv"], e))
        return cls(os.environ[names["keyIdEnv"]].strip(), os.environ[names["issuerIdEnv"]].strip(), pem)

    def token(self):
        if self._token and time.time() - self._made < TOKEN_REUSE_SECONDS:
            return self._token
        issued = int(time.time())
        try:
            self._token = jwt.es256(self.pem, {"kid": self.key_id, "typ": "JWT"},
                                    {"iss": self.issuer, "iat": issued, "exp": issued + 1200,
                                     "aud": "appstoreconnect-v1"})
        except RuntimeError as e:
            raise Usage(str(e))
        except jwt.KeyProblem as e:
            raise Usage("The App Store Connect key: %s." % e)
        self._made = time.time()
        return self._token

    def call(self, method, path, body=None, ok404=False, retry=None):
        url = path if path.startswith("https://") else APPLE_API + path
        headers = {"Authorization": "Bearer " + self.token(), "Accept": "application/json"}
        res = send(self.store, method, url, headers, body, retry)
        if ok404 and res.status == 404:
            return None
        if res.status >= 400:
            raise StoreError(self.store, res.status, method, url, res.text())
        try:
            return res.json()
        except ValueError:
            raise StoreError(self.store, res.status, method, url, "the answer isn't JSON: " + res.text()[:300])

    def get(self, path, ok404=False):
        return self.call("GET", path, ok404=ok404)

    def get_all(self, path):
        """Every item of a list, following ``links.next``."""
        items, url, visited = [], path, set()
        while url:
            if url in visited:
                break
            visited.add(url)
            doc = self.get(url) or {}
            items.extend(doc.get("data") or [])
            nxt = (doc.get("links") or {}).get("next")
            if nxt and not nxt.startswith(APPLE_API + "/"):
                raise Failure("App Store Connect's next page is at %s, not its own API: stopped." % nxt)
            url = nxt
        return items


def version_state(version):
    a = attrs(version)
    return a.get("appVersionState") or a.get("appStoreState")


def info_state(info):
    a = attrs(info)
    return a.get("state") or a.get("appStoreState")


def apple_survey(client, listing, options):
    """Read App Store Connect (GET only) and work out the plan for Apple, with what it compared."""
    plan, seen = Plan(), Seen(client.secret)
    A = listing.section("apple")
    bundle = A.get("bundleId")
    if not bundle:
        raise Usage("%s has no apple.bundleId." % listing.path)
    apps = [a for a in client.get_all("/v1/apps?filter[bundleId]=%s&limit=200" % urllib.parse.quote(bundle, safe=""))
            if attrs(a).get("bundleId") in (None, bundle)]
    if not apps:
        raise Failure("No app with the bundle ID %s in App Store Connect: create it there first (Apps ▸ +); the API "
                      "can't." % bundle)
    app = apps[0]
    app_id = app["id"]
    if A.get("appId") and str(A["appId"]) != app_id:
        raise Failure("The bundle ID %s is app %s in App Store Connect, not %s: check app.ids.apple.appId."
                      % (bundle, app_id, A["appId"]))
    primary = attrs(app).get("primaryLocale")
    seen.put("the app", {"id": app_id, "primaryLocale": primary})
    if primary and A.get("primaryLocale") and primary != A["primaryLocale"]:
        plan.note("The app's primary language in App Store Connect is %s, and the listing's is %s: what's written for "
                  "%s goes in as another language, and %s is what most people see." % (primary, A["primaryLocale"],
                                                                                       A["primaryLocale"], primary))
    app_section = A.get("app") or {}
    _apple_app_info(client, listing, A, app_section, app_id, options, plan, seen)
    for platform, P in sorted((A.get("platforms") or {}).items()):
        if not isinstance(P, dict):
            continue
        _apple_platform(client, listing, A, app_section, app_id, platform, P, options, plan, seen)
    plan.note("App Store Connect only (no API): App Privacy, price and availability, the EU trader status, content "
              "rights, and submitting for review (see out/checklist.md).")
    return plan, seen


def _apple_app_info(client, listing, A, app_section, app_id, options, plan, seen):
    infos = client.get_all("/v1/apps/%s/appInfos?limit=200" % app_id)
    seen.put("app infos", sorted([i["id"], info_state(i)] for i in infos))
    editable = [i for i in infos if info_state(i) in EDITABLE]
    if not editable:
        plan.note("The app information (name, subtitle, privacy URLs, categories, age rating) can change only while a "
                  "version is in preparation, and none is (%s): left out." %
                  (", ".join(sorted(set(str(info_state(i)) for i in infos))) or "no app info"))
        return
    info_id = editable[0]["id"]

    # Categories.
    cats = app_section.get("categories") or {}
    want = {}
    for side in ("primary", "secondary"):
        if side in cats and cats[side] is not None:
            want[side + "Category"] = cats[side]
        subs = cats.get(side + "Subcategories")
        if isinstance(subs, list):
            want[side + "SubcategoryOne"] = subs[0] if len(subs) > 0 else None
            want[side + "SubcategoryTwo"] = subs[1] if len(subs) > 1 else None
    if want:
        doc = client.get("/v1/appInfos/%s?include=%s" % (info_id, ",".join(CATEGORY_RELATIONS))) or {}
        rels = ((doc.get("data") or {}).get("relationships")) or {}
        current = {}
        for rel in CATEGORY_RELATIONS:
            data = (rels.get(rel) or {}).get("data")
            current[rel] = data.get("id") if isinstance(data, dict) else None
        seen.put("categories", current)
        changes = dict((rel, value) for rel, value in want.items() if current.get(rel) != value)
        if changes:
            said = ["%s %s → %s" % (rel, current.get(rel) or "(none)", value or "(none)")
                    for rel, value in sorted(changes.items())]
            plan.add("apple.categories.update", "set the categories: " + "; ".join(said), appInfoId=info_id, set=changes)
        else:
            plan.unchanged.append("categories, as they are")

    # Name, subtitle and privacy URLs per locale.
    locs = dict((attrs(l).get("locale"), l) for l in client.get_all("/v1/appInfos/%s/appInfoLocalizations?limit=200"
                                                                       % info_id))
    tv_text = None
    if A.get("tvPrivacyText"):
        with open(listing.side_file(A["tvPrivacyText"]), "r", encoding="utf-8") as f:
            tv_text = f.read()
    for locale, ours in sorted((app_section.get("localizations") or {}).items()):
        ours = dict(ours or {})
        if tv_text is not None and ours.get("privacyPolicyText") is None:
            ours["privacyPolicyText"] = tv_text
        theirs = locs.get(locale)
        if theirs is None:
            seen.put("%s app info" % locale, None)
            values = dict((f, ours[f]) for f, _ in APP_INFO_FIELDS if ours.get(f) is not None)
            if values:
                plan.add("apple.appInfo.localization.create", "add the %s app information (name %s)"
                         % (locale, short(values.get("name"))), locale=locale, appInfoId=info_id, set=values)
            continue
        ta = attrs(theirs)
        seen.put("%s app info" % locale, dict([("id", theirs["id"])] + [(f, ta.get(f)) for f, _ in APP_INFO_FIELDS]))
        changes, said = {}, []
        for field, label in APP_INFO_FIELDS:
            if ours.get(field) is not None and differs(ta.get(field), ours[field]):
                changes[field] = ours[field]
                said.append("change %s: %s → %s" % (label, short(ta.get(field)), short(ours[field])))
        if changes:
            plan.add("apple.appInfo.localization.update", "; ".join(said), locale=locale,
                     localizationId=theirs["id"], set=changes)
        else:
            plan.unchanged.append("%s app information, as it is" % locale)

    # The age rating, only when asked.
    rating = app_section.get("ageRating")
    if options.get("ageRating"):
        if not isinstance(rating, dict) or not rating:
            plan.note("--age-rating: the listing has no age rating answers (stores.apple.ageRating).")
        else:
            doc = client.get("/v1/appInfos/%s/ageRatingDeclaration" % info_id, ok404=True) or {}
            decl = doc.get("data")
            if not decl:
                plan.note("App Store Connect has no age rating declaration for this app info to change.")
            else:
                da = attrs(decl)
                seen.put("age rating", dict([("id", decl["id"])] + [(k, da.get(k)) for k in sorted(rating)]))
                changes = dict((k, v) for k, v in rating.items()
                               if k != "$comment" and jsonio.canonical(da.get(k)) != jsonio.canonical(v))
                if changes:
                    said = ["%s %s → %s" % (k, json.dumps(da.get(k)), json.dumps(v)) for k, v in sorted(changes.items())]
                    plan.add("apple.ageRating.update", "answer the age rating: " + "; ".join(said),
                             declarationId=decl["id"], set=changes)
                else:
                    plan.unchanged.append("age rating answers, as they are")
    elif isinstance(rating, dict) and rating:
        plan.note("The age rating answers aren't compared without --age-rating (they're the whole app's: send them "
                  "once settled).")


def _apple_platform(client, listing, A, app_section, app_id, platform, P, options, plan, seen):
    versions = client.get_all("/v1/apps/%s/appStoreVersions?filter[platform]=%s&limit=200" % (app_id, platform))
    seen.put("%s versions" % platform, sorted([v["id"], attrs(v).get("versionString"), version_state(v)]
                                              for v in versions))
    editable = sorted([v for v in versions if version_state(v) in EDITABLE],
                      key=lambda v: attrs(v).get("createdDate") or "", reverse=True)
    copyright_ = app_section.get("copyright")
    if not editable:
        others = ", ".join("%s %s" % (attrs(v).get("versionString"), version_state(v)) for v in versions) or "none"
        if options.get("newVersion"):
            values = {"platform": platform, "versionString": options["newVersion"]}
            if copyright_ is not None:
                values["copyright"] = copyright_
            plan.add("apple.version.create", "create version %s (copyright %s)" % (options["newVersion"],
                                                                                     short(copyright_)),
                     platform=platform, appId=app_id, set=values)
            plan.note("%s: version %s is created by this plan. App Store Connect fills a new version from the last "
                      "one, so its words, screenshots and App Review details are planned once it exists: after apply, "
                      "run plan apple again." % (platform, options["newVersion"]))
            return
        plan.note("%s: no version in preparation (versions: %s), so its description, keywords, What's New, URLs, "
                  "screenshots, previews and App Review details are left out. Create one in App Store Connect, or "
                  "plan again with --new-version X.Y.Z (ask first: it's a new version in the account)."
                  % (platform, others))
        _apple_live_promotional_text(client, platform, P, versions, plan, seen)
        return
    if options.get("newVersion"):
        plan.note("%s already has version %s in preparation: --new-version isn't needed for it."
                  % (platform, attrs(editable[0]).get("versionString")))
    version = editable[0]
    vid = version["id"]
    va = attrs(version)
    first = len(versions) == 1
    seen.put("%s version %s" % (platform, va.get("versionString")), {"id": vid, "copyright": va.get("copyright")})

    if copyright_ is not None and differs(va.get("copyright"), copyright_):
        plan.add("apple.version.update", "set the copyright: %s → %s" % (short(va.get("copyright")), short(copyright_)),
                 platform=platform, versionId=vid, set={"copyright": copyright_})

    locs = dict((attrs(l).get("locale"), l) for l in
                client.get_all("/v1/appStoreVersions/%s/appStoreVersionLocalizations?limit=200" % vid))
    words = P.get("localizations") or {}
    shots = P.get("screenshots") or {}
    previews = P.get("previews") or {}
    loc_ids = {}
    for locale in sorted(set(words) | set(shots) | set(previews)):
        ours = words.get(locale) or {}
        theirs = locs.get(locale)
        fields = list(VERSION_FIELDS)
        if first and norm(ours.get("whatsNew")):
            plan.note("%s %s: What's New is left out on a first version (App Store Connect turns it down)."
                      % (platform, locale))
            fields = [f for f in fields if f[0] != "whatsNew"]
        if theirs is None:
            seen.put("%s %s listing" % (platform, locale), None)
            values = dict((f, ours[f]) for f, _ in fields if ours.get(f) is not None)
            action = plan.add("apple.version.localization.create", "add the %s %s listing" % (platform, locale),
                              platform=platform, locale=locale, versionId=vid, set=values)
            loc_ids[locale] = (None, action["id"])
            continue
        loc_ids[locale] = (theirs["id"], None)
        ta = attrs(theirs)
        seen.put("%s %s listing" % (platform, locale),
                 dict([("id", theirs["id"])] + [(f, ta.get(f)) for f, _ in VERSION_FIELDS]))
        changes, said = {}, []
        for field, label in fields:
            if ours.get(field) is not None and differs(ta.get(field), ours[field], field):
                changes[field] = ours[field]
                said.append("change %s: %s → %s" % (label, short(ta.get(field)), short(ours[field])))
        if changes:
            plan.add("apple.version.localization.update", "; ".join(said), platform=platform, locale=locale,
                     localizationId=theirs["id"], set=changes)
        elif locale in words:
            plan.unchanged.append("%s %s listing's words, as they are" % (platform, locale))

    _apple_review(client, A, platform, vid, plan, seen)

    for asset, slots in ((SCREENSHOTS, shots), (PREVIEWS, previews)):
        for locale in sorted(slots):
            loc_id, made_by = loc_ids[locale]
            _apple_assets(client, listing, asset, platform, locale, loc_id, made_by, slots[locale] or {}, plan, seen)


def _apple_live_promotional_text(client, platform, P, versions, plan, seen):
    """Promotional text changes on the version on sale, without review, even with no version in preparation."""
    wanted = dict((loc, w.get("promotionalText")) for loc, w in (P.get("localizations") or {}).items()
                  if isinstance(w, dict) and w.get("promotionalText") is not None)
    live = sorted([v for v in versions if version_state(v) in LIVE or attrs(v).get("appStoreState") in LIVE],
                  key=lambda v: attrs(v).get("createdDate") or "", reverse=True)
    if not wanted or not live:
        return
    vid = live[0]["id"]
    locs = dict((attrs(l).get("locale"), l) for l in
                client.get_all("/v1/appStoreVersions/%s/appStoreVersionLocalizations?limit=200" % vid))
    for locale, text in sorted(wanted.items()):
        theirs = locs.get(locale)
        if theirs is None:
            continue
        current = attrs(theirs).get("promotionalText")
        seen.put("%s %s live promotional text" % (platform, locale), {"id": theirs["id"], "promotionalText": current})
        if differs(current, text):
            plan.add("apple.version.localization.update",
                     "change promotional text on version %s, on sale (no review needed): %s → %s"
                     % (attrs(live[0]).get("versionString"), short(current), short(text)),
                     platform=platform, locale=locale, localizationId=theirs["id"], set={"promotionalText": text})
        else:
            plan.unchanged.append("%s %s promotional text, as it is" % (platform, locale))


def _apple_review(client, A, platform, vid, plan, seen):
    review = A.get("review")
    if not isinstance(review, dict):
        return
    doc = client.get("/v1/appStoreVersions/%s/appStoreReviewDetail" % vid, ok404=True) or {}
    detail = doc.get("data")
    da = attrs(detail)
    seen.put("%s App Review details" % platform, {"id": (detail or {}).get("id"), "notes": da.get("notes"),
                                                  "demoAccountRequired": da.get("demoAccountRequired")})
    seen.put("%s App Review contact or demo account" % platform, dict((k, da.get(k)) for k in REVIEW_PRIVATE),
             private=True)
    values, env, said = {}, {}, []
    if review.get("notes") is not None and differs(da.get("notes"), review["notes"]):
        values["notes"] = review["notes"]
        said.append("notes: %s → %s" % (short(da.get("notes")), short(review["notes"])))
    contact = review.get("contact") or {}
    unset = []
    for field, key, label in REVIEW_CONTACT:
        var = contact.get(key)
        if not var:
            continue
        value = os.environ.get(var, "").strip()
        if not value:
            unset.append(var)
            continue
        if field == "contactPhone" and not value.startswith("+"):
            plan.note("App Review's contact phone (%s) needs + and the country code, like +1 555 555 0100: left as "
                      "App Store Connect has it." % var)
            continue
        if differs(da.get(field), value):
            env[field] = var
            if field == "contactPhone":
                said.append("contact phone: %s → %s" % (masked_phone(da.get(field)), masked_phone(value)))
            else:
                said.append("contact %s: from %s" % (label, var))
    if unset:
        plan.note("App Review's contact: %s %s set, so %s left as App Store Connect has %s." % (
            ", ".join(unset), "isn't" if len(unset) == 1 else "aren't", "it's" if len(unset) == 1 else "they're",
            "it" if len(unset) == 1 else "them"))
    if "demoAccount" in review:
        demo = review["demoAccount"]
        if demo is None:
            if da.get("demoAccountRequired") is not False:
                values["demoAccountRequired"] = False
                said.append("demo account: none needed")
        elif isinstance(demo, dict):
            user_var, pass_var = demo.get("usernameEnv"), demo.get("passwordEnv")
            missing = [v for v in (user_var, pass_var) if not v or not os.environ.get(v)]
            if missing:
                plan.note("App Review's demo account: %s isn't set, so it's left as App Store Connect has it."
                          % ", ".join(str(m) for m in missing))
            else:
                if da.get("demoAccountRequired") is not True:
                    values["demoAccountRequired"] = True
                    said.append("demo account: required")
                if differs(da.get("demoAccountName"), os.environ[user_var]):
                    env["demoAccountName"] = user_var
                    said.append("demo account name: from %s" % user_var)
                if differs(da.get("demoAccountPassword"), os.environ[pass_var]):
                    env["demoAccountPassword"] = pass_var
                    said.append("demo account password: from %s (not shown)" % pass_var)
    if not values and not env:
        plan.unchanged.append("%s App Review details, as they are" % platform)
        return
    env_hmac = _env_hmac(client.secret, env)
    summary = "App Review: " + "; ".join(said)
    if detail:
        plan.add("apple.review.update", summary, platform=platform, detailId=detail["id"], set=values, env=env,
                 envHmac=env_hmac)
    else:
        plan.add("apple.review.create", summary, platform=platform, versionId=vid, set=values, env=env,
                 envHmac=env_hmac)


def _env_hmac(secret, env):
    values = dict((field, os.environ.get(var, "").strip()) for field, var in env.items())
    return hmac.new(secret, jsonio.canonical(values).encode("utf-8"), hashlib.sha256).hexdigest()


def _apple_assets(client, listing, asset, platform, locale, loc_id, made_by, slots, plan, seen):
    sets = {}
    if loc_id:
        for s in client.get_all("/v1/appStoreVersionLocalizations/%s/%s?limit=200" % (loc_id, asset.sets)):
            sets.setdefault(attrs(s).get(asset.type_field), s["id"])
        seen.put("%s %s %s sets" % (platform, locale, asset.name), sorted([t, i] for t, i in sets.items()))
    type_key = "displayType" if asset is SCREENSHOTS else "previewType"
    for slot, entries in sorted(slots.items()):
        ours = []
        for entry in entries or []:
            item = {"file": entry["file"], "md5": listing.checked(entry, "md5"),
                    "size": os.path.getsize(listing.file(entry["file"]))}
            if asset is PREVIEWS:
                ext = os.path.splitext(entry["file"])[1].lower()
                item["mime"] = entry.get("mime") or PREVIEW_MIME.get(ext, "video/mp4")
                if entry.get("posterFrame"):
                    item["posterFrame"] = entry["posterFrame"]
            ours.append(item)
        if not ours:
            continue
        set_id = sets.get(slot)
        theirs = []
        if set_id:
            for it in client.get_all("/v1/%s/%s/%s?limit=200" % (asset.sets, set_id, asset.items)):
                ia = attrs(it)
                t = {"id": it["id"], "md5": (ia.get("sourceFileChecksum") or "").lower()}
                if asset is PREVIEWS:
                    t["frame"] = ia.get("previewFrameTimeCode")
                theirs.append(t)
        key = "%s %s %s" % (platform, locale, slot)
        seen.put(key, theirs, count=len(theirs))
        fields = {"platform": platform, "locale": locale, type_key: slot}
        noun = asset.name
        their_md5 = [t["md5"] for t in theirs]
        our_md5 = [o["md5"] for o in ours]
        matched = []  # (ours, the store's item reused for it or None)
        unused = list(theirs)
        for o in ours:
            hit = next((t for t in unused if t["md5"] == o["md5"]), None)
            if hit is not None:
                unused.remove(hit)
            matched.append((o, hit))
        if their_md5 == our_md5:
            plan.unchanged.append("%s: %s, as %s" % (key, plural(len(ours), noun),
                                                     "it is" if len(ours) == 1 else "they are"))
        elif not unused and all(hit is not None for _, hit in matched):
            plan.add(asset.prefix + ".reorder", "reorder the %s (the same pictures, a new order)"
                     % plural(len(ours), noun), setId=set_id, order=[hit["id"] for _, hit in matched], **fields)
        else:
            items = [{"reuse": hit["id"]} if hit is not None else {"upload": o} for o, hit in matched]
            kept = sum(1 for _, hit in matched if hit is not None)
            new = len(ours) - kept
            if theirs:
                summary = "replace the %s with %d (%d kept, %d new, %d removed; the new ones go up before the old " \
                          "ones are deleted)" % (plural(len(theirs), noun), len(ours), kept, new, len(unused))
            else:
                summary = "add %s" % plural(len(ours), noun)
            extra = {"setId": set_id, "localizationId": loc_id, "items": items, "delete": [t["id"] for t in unused]}
            if made_by:
                extra["localizationFrom"] = made_by
            plan.add(asset.prefix + ".replace", summary, **dict(fields, **extra))
        if asset is PREVIEWS:
            frames = [{"id": hit["id"], "previewFrameTimeCode": o["posterFrame"]} for o, hit in matched
                      if hit is not None and o.get("posterFrame") and differs(hit.get("frame"), o["posterFrame"])]
            if frames:
                plan.add("apple.previews.frame", "set the poster frame of %s" % plural(len(frames), "preview"),
                         items=frames, **fields)


# ------------------------------------------------------------------------------------------ Apple: applying

class AppleApplier(object):
    """Performs a plan's Apple actions, in order."""

    def __init__(self, client, listing):
        self.client = client
        self.listing = listing
        self.created = {}

    def run(self, action):
        kind = action["kind"]
        c = self.client
        if kind == "apple.categories.update":
            rels = dict((rel, {"data": {"type": "appCategories", "id": v} if v else None})
                        for rel, v in action["set"].items())
            c.call("PATCH", "/v1/appInfos/%s" % action["appInfoId"],
                   resource("appInfos", action["appInfoId"], relationships=rels))
        elif kind == "apple.appInfo.localization.update":
            c.call("PATCH", "/v1/appInfoLocalizations/%s" % action["localizationId"],
                   resource("appInfoLocalizations", action["localizationId"], action["set"]))
        elif kind == "apple.appInfo.localization.create":
            made = c.call("POST", "/v1/appInfoLocalizations", resource(
                "appInfoLocalizations", None, dict(action["set"], locale=action["locale"]),
                {"appInfo": to("appInfos", action["appInfoId"])}))
            self.created[action["id"]] = made["data"]["id"]
        elif kind == "apple.ageRating.update":
            c.call("PATCH", "/v1/ageRatingDeclarations/%s" % action["declarationId"],
                   resource("ageRatingDeclarations", action["declarationId"], action["set"]))
        elif kind == "apple.version.create":
            made = c.call("POST", "/v1/appStoreVersions", resource(
                "appStoreVersions", None, action["set"], {"app": to("apps", action["appId"])}))
            self.created[action["id"]] = made["data"]["id"]
            return "done (version %s)" % made["data"]["id"]
        elif kind == "apple.version.update":
            c.call("PATCH", "/v1/appStoreVersions/%s" % action["versionId"],
                   resource("appStoreVersions", action["versionId"], action["set"]))
        elif kind == "apple.version.localization.update":
            c.call("PATCH", "/v1/appStoreVersionLocalizations/%s" % action["localizationId"],
                   resource("appStoreVersionLocalizations", action["localizationId"], action["set"]))
        elif kind == "apple.version.localization.create":
            made = c.call("POST", "/v1/appStoreVersionLocalizations", resource(
                "appStoreVersionLocalizations", None, dict(action["set"], locale=action["locale"]),
                {"appStoreVersion": to("appStoreVersions", action["versionId"])}))
            self.created[action["id"]] = made["data"]["id"]
        elif kind in ("apple.review.update", "apple.review.create"):
            values = dict(action.get("set") or {})
            for field, var in (action.get("env") or {}).items():
                values[field] = os.environ.get(var, "").strip()
            if kind == "apple.review.update":
                c.call("PATCH", "/v1/appStoreReviewDetails/%s" % action["detailId"],
                       resource("appStoreReviewDetails", action["detailId"], values))
            else:
                c.call("POST", "/v1/appStoreReviewDetails", resource(
                    "appStoreReviewDetails", None, values,
                    {"appStoreVersion": to("appStoreVersions", action["versionId"])}))
        elif kind in ("apple.screenshots.reorder", "apple.previews.reorder"):
            asset = SCREENSHOTS if kind.startswith("apple.screenshots") else PREVIEWS
            self._order(asset, action["setId"], action["order"])
        elif kind in ("apple.screenshots.replace", "apple.previews.replace"):
            return self._replace(SCREENSHOTS if kind.startswith("apple.screenshots") else PREVIEWS, action)
        elif kind == "apple.previews.frame":
            for item in action["items"]:
                c.call("PATCH", "/v1/appPreviews/%s" % item["id"],
                       resource("appPreviews", item["id"], {"previewFrameTimeCode": item["previewFrameTimeCode"]}))
        else:
            raise Usage("The plan has an action this push.py doesn't know: %s." % kind)
        return "done"

    def _order(self, asset, set_id, ids):
        self.client.call("PATCH", "/v1/%s/%s/relationships/%s" % (asset.sets, set_id, asset.items),
                         {"data": [{"type": asset.items, "id": i} for i in ids]})

    def _replace(self, asset, action):
        """New pictures go up before old ones are deleted (an old one goes early only to make room in a full set)."""
        c = self.client
        set_id = action.get("setId")
        if not set_id:
            loc_id = action.get("localizationId") or self.created.get(action.get("localizationFrom"))
            if not loc_id:
                raise Failure("The %s localization this action needs wasn't created." % action.get("locale"))
            type_value = action.get("displayType") or action.get("previewType")
            made = c.call("POST", "/v1/%s" % asset.sets, resource(
                asset.sets, None, {asset.type_field: type_value},
                {"appStoreVersionLocalization": to("appStoreVersionLocalizations", loc_id)}))
            set_id = made["data"]["id"]
        to_delete = list(action.get("delete") or [])
        count = len(to_delete) + sum(1 for it in action["items"] if "reuse" in it)
        final, uploaded = [], []
        for item in action["items"]:
            if "reuse" in item:
                final.append(item["reuse"])
                continue
            if count >= asset.capacity and to_delete:
                c.call("DELETE", "/v1/%s/%s" % (asset.items, to_delete.pop(0)))
                count -= 1
            new_id = self._upload(asset, set_id, item["upload"])
            count += 1
            final.append(new_id)
            uploaded.append(new_id)
        still = self._processed(asset, uploaded)
        self._order(asset, set_id, final + to_delete)
        for old in to_delete:
            c.call("DELETE", "/v1/%s/%s" % (asset.items, old))
        result = "done (%d uploaded, %d kept, %d removed)" % (len(uploaded), len(final) - len(uploaded),
                                                              len(action.get("delete") or []))
        if still:
            result += "; %s still processing: App Store Connect shows them when done, and says there if one's " \
                      "refused" % plural(still, asset.name)
        return result

    def _upload(self, asset, set_id, item):
        """Reserve, send each part where Apple says (retrying a part's 5xx, 408 and 429), commit with the MD5."""
        path = self.listing.file(item["file"])
        name = os.path.basename(path)
        values = {"fileName": name, "fileSize": item["size"]}
        if asset is PREVIEWS:
            values["mimeType"] = item.get("mime") or "video/mp4"
            if item.get("posterFrame"):
                values["previewFrameTimeCode"] = item["posterFrame"]
        reserved = self.client.call("POST", "/v1/%s" % asset.items, resource(
            asset.items, None, values, {asset.set_relation: to(asset.sets, set_id)}))
        data = reserved["data"]
        new_id = data["id"]
        with open(path, "rb") as f:
            content = f.read()
        for op in attrs(data).get("uploadOperations") or []:
            url = op.get("url") or ""
            if not url.startswith("https://"):
                raise Failure("App Store Connect gave an upload address that isn't https: stopped.")
            offset, length = int(op.get("offset") or 0), int(op.get("length") or 0)
            headers = dict((h.get("name"), h.get("value")) for h in (op.get("requestHeaders") or []) if h.get("name"))
            method = op.get("method") or "PUT"
            res = send("Apple's upload server", method, url, headers, content[offset: offset + length],
                       retry=True, timeout=300)
            if res.status >= 400:
                raise StoreError("Apple's upload server (%s, the part at %d)" % (name, offset), res.status, method,
                                 url, res.text())
        self.client.call("PATCH", "/v1/%s/%s" % (asset.items, new_id), resource(
            asset.items, new_id, {"uploaded": True, "sourceFileChecksum": item["md5"]}))
        say("      sent %s" % name)
        return new_id

    def _processed(self, asset, ids):
        """Wait for App Store Connect to process what was sent; a refused one stops with Apple's errors."""
        waiting = list(ids)
        polls = max(1, asset.wait // POLL_SECONDS)
        for attempt in range(polls):
            for item_id in list(waiting):
                doc = self.client.get("/v1/%s/%s" % (asset.items, item_id)) or {}
                ia = attrs(doc.get("data"))
                state = ia.get("assetDeliveryState") or {}
                if state.get("state") == "COMPLETE":
                    waiting.remove(item_id)
                elif state.get("state") == "FAILED":
                    raise Failure("App Store Connect refused a %s (%s): %s. The old ones are still there."
                                  % (asset.name, ia.get("fileName") or item_id,
                                     json.dumps(state.get("errors") or state)))
            if not waiting or attempt == polls - 1:
                break
            web.SLEEP(POLL_SECONDS)
        return len(waiting)


# ------------------------------------------------------------------------------------------ Google Play

def load_service_account(value, var):
    """A service account's JSON key from a path, its text, or base64 of either; never shown in a message."""
    text = value.strip()
    if not text.startswith("{"):
        path = os.path.expanduser(text)
        if len(text) < 4096 and "\n" not in text and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
        else:
            try:
                compact = "".join(text.split())
                text = base64.b64decode(compact + "=" * (-len(compact) % 4)).decode("utf-8").strip()
            except (binascii.Error, ValueError, UnicodeDecodeError):
                text = ""
            if text and not text.startswith("{") and os.path.isfile(os.path.expanduser(text)):
                with open(os.path.expanduser(text), "r", encoding="utf-8") as f:
                    text = f.read().strip()
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict) or not data.get("client_email") or not data.get("private_key"):
        raise Usage("%s doesn't hold a service account's JSON key (a path to it, its text, or base64 of either) "
                    "with client_email and private_key." % var)
    try:
        data["private_key"] = jwt.load_key(data["private_key"])
    except jwt.KeyProblem as e:
        raise Usage("%s: the service account's private_key: %s." % (var, e))
    return data


class GoogleClient(object):
    """The Android Publisher API with a service account's token (RS256, traded at oauth2.googleapis.com)."""

    store = "Google Play"

    def __init__(self, account, package):
        self.account = account
        self.package = package
        self._token = None
        self._made = 0.0

    @classmethod
    def from_env(cls, listing, package):
        var = listing.auth("google", GOOGLE_ENV)["serviceAccountEnv"]
        value = os.environ.get(var)
        if not value or not value.strip():
            raise Usage("%s isn't set: export the service account's JSON key (a path, its text, or base64), from a "
                        "Google Cloud project with the Google Play Android Developer API enabled "
                        "(references/google.md, Service account and permissions)." % var)
        return cls(load_service_account(value, var), package)

    def token(self):
        if self._token and time.time() - self._made < 50 * 60:
            return self._token
        issued = int(time.time())
        header = {"typ": "JWT"}
        if self.account.get("private_key_id"):
            header["kid"] = self.account["private_key_id"]
        try:
            assertion = jwt.rs256(self.account["private_key"], header, {
                "iss": self.account["client_email"], "scope": GOOGLE_SCOPE, "aud": GOOGLE_TOKEN,
                "iat": issued, "exp": issued + 3600})
        except RuntimeError as e:
            raise Usage(str(e))
        except jwt.KeyProblem as e:
            raise Usage("The service account's key: %s." % e)
        form = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                       "assertion": assertion})
        res = send("Google's sign-in", "POST", GOOGLE_TOKEN,
                   {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, form,
                   retry=True)
        if res.status >= 400:
            raise StoreError("Google's sign-in", res.status, "POST", GOOGLE_TOKEN, res.text())
        try:
            self._token = res.json()["access_token"]
        except (ValueError, KeyError, TypeError):
            raise StoreError("Google's sign-in", res.status, "POST", GOOGLE_TOKEN, "no access_token in the answer")
        self._made = time.time()
        return self._token

    def call(self, method, url, body=None, ok404=False, retry=None, content_type=None):
        headers = {"Authorization": "Bearer " + self.token(), "Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        elif method == "POST" and body is None:
            body = b""
        res = send(self.store, method, url, headers, body, retry, timeout=300 if content_type else 120)
        if ok404 and res.status == 404:
            return None
        if res.status >= 400:
            raise StoreError(self.store, res.status, method, url, res.text())
        try:
            return res.json()
        except ValueError:
            raise StoreError(self.store, res.status, method, url, "the answer isn't JSON: " + res.text()[:300])

    def app(self):
        return "%s/%s" % (GOOGLE_API, urllib.parse.quote(self.package, safe=""))

    def open_edit(self):
        made = self.call("POST", self.app() + "/edits", {}, retry=False) or {}
        if not made.get("id"):
            raise StoreError(self.store, 200, "POST", self.app() + "/edits", "no edit id in the answer")
        return made["id"]

    def edit_url(self, edit_id):
        return "%s/edits/%s" % (self.app(), urllib.parse.quote(edit_id, safe=""))

    def delete_edit(self, edit_id, why):
        """Delete an uncommitted edit; a failure is a warning that never replaces the error that stopped the run."""
        try:
            self.call("DELETE", self.edit_url(edit_id), retry=True)
            return True
        except StoreError as e:
            problem = "%s %s answered %d" % (e.method, _shown_url(e.url), e.status)
        except Exit as e:
            problem = e.message
        warn("Warning: the edit %s %s, and deleting it failed too (%s). Play drops it by itself once it expires or "
             "another edit is opened." % (edit_id, why, problem))
        return False


def google_survey(client, edit_id, listing):
    """Read the listing inside an open edit (GETs only) and work out the plan for Google Play."""
    plan, seen = Plan(), Seen()
    G = listing.section("google")
    base = client.edit_url(edit_id)
    state = {"listings": {}}

    details = client.call("GET", base + "/details") or {}
    for field, _ in (("defaultLanguage", None),) + DETAIL_FIELDS:
        seen.put("details: %s" % field, details.get(field))
    if G.get("defaultLanguage") and details.get("defaultLanguage") and G["defaultLanguage"] != details["defaultLanguage"]:
        plan.note("Play's default language is %s, and the listing's is %s: Play shows the default where there's no "
                  "translation. Change it in Play Console (Store presence ▸ Store settings), or make "
                  "stores.google.defaultLanguage %s." % (details["defaultLanguage"], G["defaultLanguage"],
                                                         details["defaultLanguage"]))
    ours = G.get("details") or {}
    changes, said = {}, []
    for field, label in DETAIL_FIELDS:
        if ours.get(field) is not None and differs(details.get(field), ours[field]):
            changes[field] = ours[field]
            said.append("change %s: %s → %s" % (label, short(details.get(field)), short(ours[field])))
    if changes:
        plan.add("google.details.update", "; ".join(said), set=changes)
    elif ours:
        plan.unchanged.append("details: contact details, as they are")

    current = dict((l.get("language"), l) for l in ((client.call("GET", base + "/listings") or {}).get("listings")
                                                     or []))
    for locale, words in sorted((G.get("listings") or {}).items()):
        words = words or {}
        theirs = current.get(locale)
        state["listings"][locale] = theirs
        if theirs is None:
            seen.put("%s listing" % locale, None)
            values = dict((f, words[f]) for f, _ in LISTING_FIELDS if words.get(f) is not None)
            plan.add("google.listing.update", "add the %s listing (title %s)" % (locale, short(values.get("title"))),
                     locale=locale, set=values)
            continue
        for field, _ in LISTING_FIELDS:
            seen.put("%s listing: %s" % (locale, field), theirs.get(field))
        changes, said = {}, []
        for field, label in LISTING_FIELDS:
            if words.get(field) is not None and differs(theirs.get(field), words[field]):
                changes[field] = words[field]
                said.append("change %s: %s → %s" % (label, short(theirs.get(field)), short(words[field])))
        if changes:
            plan.add("google.listing.update", "; ".join(said), locale=locale, set=changes)
        else:
            plan.unchanged.append("%s listing, as it is" % locale)

    for locale, types in sorted((G.get("images") or {}).items()):
        for image_type, entries in sorted((types or {}).items()):
            if not entries:
                continue
            files = [e["file"] if isinstance(e, dict) else e for e in entries]
            ours = [listing.checked(e if isinstance(e, dict) else {"file": e}, "sha256") for e in entries]
            for f in files:
                listing.file(f)
            found = client.call("GET", "%s/listings/%s/%s" % (base, locale, image_type), ok404=True) or {}
            theirs = [(i.get("sha256") or "").lower() for i in (found.get("images") or [])]
            key = "%s %s" % (locale, image_type)
            seen.put(key, theirs, count=len(theirs))
            one, many = IMAGE_NAMES.get(image_type, (image_type, image_type))
            if theirs == ours:
                plan.unchanged.append("%s: %s, as %s" % (key, plural(len(ours), "picture"),
                                                         "it is" if len(ours) == 1 else "they are"))
                continue
            if not theirs:
                summary = "add %s" % (plural(len(ours), one, many) if len(ours) > 1 else "the " + one)
            elif len(theirs) == 1 and len(ours) == 1:
                summary = "replace the %s" % one
            else:
                summary = "replace %s with %d" % (plural(len(theirs), one, many), len(ours))
            plan.add("google.images.replace", summary, locale=locale, imageType=image_type, files=files, sha256=ours)

    if G.get("dataSafetyCsv"):
        path = listing.side_file(G["dataSafetyCsv"])
        with open(path, "rb") as f:
            raw = f.read()
        plan.add("google.dataSafety.update", "send the Data safety form from %s (it replaces every answer in Play "
                 "Console)" % G["dataSafetyCsv"], file=path if os.path.isabs(G["dataSafetyCsv"]) else G["dataSafetyCsv"],
                 sha256=hashlib.sha256(raw).hexdigest())

    plan.note("Play Console only (no API): the category, tags, content rating, target audience, ads, Sign-in details "
              "and the other App content declarations, alt text, and release notes (they go with a release on a "
              "track; see out/checklist.md).")
    return plan, seen, state


def _google_data_safety_path(listing, action):
    return listing.side_file(action["file"])


class GoogleApplier(object):
    """Performs a plan's Google Play actions inside one edit (the Data safety form outside it)."""

    def __init__(self, client, listing, edit_id, state):
        self.client = client
        self.listing = listing
        self.edit_id = edit_id
        self.state = state

    def run(self, action):
        c = self.client
        base = c.edit_url(self.edit_id)
        kind = action["kind"]
        if kind == "google.details.update":
            c.call("PATCH", base + "/details", action["set"])
        elif kind == "google.listing.update":
            locale = action["locale"]
            body = {"language": locale}
            for field, _ in LISTING_FIELDS:
                value = (self.state["listings"].get(locale) or {}).get(field)
                if value is not None:
                    body[field] = value
            body.update(action["set"])
            c.call("PUT", "%s/listings/%s" % (base, locale), body)
        elif kind == "google.images.replace":
            return self._images(action)
        elif kind == "google.dataSafety.update":
            with open(_google_data_safety_path(self.listing, action), "r", encoding="utf-8") as f:
                text = f.read()
            c.call("POST", c.app() + "/dataSafety", {"safetyLabels": text}, retry=True)
        else:
            raise Usage("The plan has an action this push.py doesn't know: %s." % kind)
        return "done"

    def _images(self, action):
        """Delete the type's pictures, upload ours in order, then check Play has exactly ours (resend once if not:
        an upload retried after a lost answer can land twice)."""
        c = self.client
        locale, image_type = action["locale"], action["imageType"]
        url = "%s/listings/%s/%s" % (c.edit_url(self.edit_id), locale, image_type)
        upload = "%s/%s/edits/%s/listings/%s/%s?uploadType=media" % (
            GOOGLE_UPLOAD, urllib.parse.quote(c.package, safe=""), urllib.parse.quote(self.edit_id, safe=""),
            locale, image_type)
        want = list(action["sha256"])
        for attempt in (1, 2):
            c.call("DELETE", url)
            for rel in action["files"]:
                path = self.listing.file(rel)
                with open(path, "rb") as f:
                    content = f.read()
                mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
                c.call("POST", upload, content, retry=True, content_type=mime)
            now = [(i.get("sha256") or "").lower() for i in ((c.call("GET", url) or {}).get("images") or [])]
            if now == want:
                return "done (%d uploaded)" % len(want)
            if attempt == 2:
                raise Failure("%s %s: Play has %s after sending, not our %d in order."
                              % (locale, image_type, plural(len(now), "picture"), len(want)))
            say("      Play has %s, not our %d in order: sending them again" % (plural(len(now), "picture"),
                                                                             len(want)))
        return "done"


# ------------------------------------------------------------------------------------------ the commands

def _print_plan(doc, store_name, target):
    say("Plan for %s (%s): %s" % (store_name, target, plural(len(doc["actions"]), "action")))
    for a in doc["actions"]:
        w = where(a)
        say("  %d %s%s: %s" % (a["id"], a["kind"], " " + w if w else "", a["summary"]))
    if not doc["actions"]:
        say("  (none: the store already matches)")
    if doc["unchanged"]:
        say("Unchanged:")
        for line in doc["unchanged"]:
            say("  " + line)
    if doc["notes"]:
        say("Notes:")
        for line in doc["notes"]:
            say("  " + line)


def _plan_doc(store, listing_arg, listing, options, plan, seen):
    return {
        "version": 1,
        "store": store,
        "createdAt": now_utc(),
        "listing": listing_arg,
        "listingSha256": listing.sha256,
        "fingerprint": seen.fingerprint(),
        "options": options,
        "actions": plan.actions,
        "unchanged": plan.unchanged,
        "notes": plan.notes,
        "compared": seen.compared(),
    }


def cmd_plan(args):
    store = args.store
    listing_arg = os.path.join(args.out, "listing.json")
    listing = Listing(listing_arg)
    section = listing.section(store)
    plan_path = args.plan or "plan-%s.json" % store
    options = {"ageRating": bool(args.age_rating), "newVersion": args.new_version}
    if store == "apple":
        client = AppleClient.from_env(listing)
        target = section.get("bundleId")
        say("Reading the store (%s, App Store Connect)..." % target)
        plan, seen = apple_survey(client, listing, options)
        store_name = "App Store Connect"
    else:
        if args.age_rating or args.new_version:
            raise Usage("--age-rating and --new-version are for plan apple.")
        package = section.get("package")
        if not package:
            raise Usage("%s has no google.package." % listing.path)
        client = GoogleClient.from_env(listing, package)
        target = package
        say("Reading the store (%s, Google Play)..." % target)
        edit_id = client.open_edit()
        try:
            plan, seen, _state = google_survey(client, edit_id, listing)
        finally:
            client.delete_edit(edit_id, "opened to read wasn't committed")
        plan.note("To read the listing, plan opened a Play edit and deleted it: nothing was committed or changed. "
                  "Play keeps one open edit an app, so don't plan while another tool is sending.")
        store_name = "Google Play"
    doc = _plan_doc(store, listing_arg, listing, options, plan, seen)
    jsonio.dump(doc, plan_path)
    _print_plan(doc, store_name, target)
    say("Wrote %s. Nothing was sent. To send exactly this: push.py apply %s" % (plan_path, plan_path))
    return 0


def _load_plan(path):
    if not os.path.isfile(path):
        raise Usage("No plan file %s: run push.py plan apple|google first." % path)
    try:
        doc = jsonio.load(path)
    except ValueError as e:
        raise Usage("%s isn't valid JSON: %s" % (path, e))
    if not isinstance(doc, dict) or doc.get("version") != 1 or doc.get("store") not in ("apple", "google") \
            or not isinstance(doc.get("actions"), list) or not doc.get("fingerprint"):
        raise Usage("%s isn't a plan push.py wrote (version 1, store apple or google, actions, fingerprint)." % path)
    return doc


def _find_listing(doc, plan_path):
    rel = doc.get("listing") or os.path.join("out", "listing.json")
    for path in (rel, os.path.join(os.path.dirname(os.path.abspath(plan_path)), rel)):
        if os.path.isfile(path):
            return Listing(path)
    raise Usage("The plan's listing %s isn't there (run apply from the folder you planned in)." % rel)


def _check_files(listing, actions):
    """Refuse when a picture or file the plan sends changed since the plan."""
    changed = []
    for a in actions:
        if a["kind"].endswith(".replace") and a["kind"].startswith("apple."):
            for item in a.get("items") or []:
                up = item.get("upload")
                if up and listing.hash(up["file"], "md5") != up["md5"]:
                    changed.append(up["file"])
        elif a["kind"] == "google.images.replace":
            for rel, sha in zip(a.get("files") or [], a.get("sha256") or []):
                if listing.hash(rel, "sha256") != sha:
                    changed.append(rel)
        elif a["kind"] == "google.dataSafety.update":
            with open(_google_data_safety_path(listing, a), "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() != a.get("sha256"):
                    changed.append(a["file"])
    if changed:
        raise Refusal("Refused: %s changed since you planned: plan again.\n  %s\nNothing was sent."
                      % ("a file the plan sends" if len(changed) == 1 else "files the plan sends",
                         "\n  ".join(changed)))


def _refuse_store_changed(doc, seen, closing):
    lines = explain_difference(doc.get("compared") or {}, seen.compared())
    if not lines:
        lines = ["what the plan compared against (the fingerprint) differs"]
    raise Refusal("Refused: the store changed since you planned: plan again.\n"
                  "  The fingerprint of what the plan compared against differs:\n    "
                  + "\n    ".join(lines) + "\n" + closing)


def _run_actions(applier, actions):
    done = 0
    for a in actions:
        w = where(a)
        label = "  %d %s%s" % (a["id"], a["kind"], " " + w if w else "")
        try:
            result = applier.run(a)
        except (StoreError, Exit):
            say("%s: failed" % label)
            raise
        say("%s: %s" % (label, result))
        done += 1
    return done


def cmd_apply(args):
    doc = _load_plan(args.plan)
    store = doc["store"]
    listing = _find_listing(doc, args.plan)
    if listing.sha256 != doc.get("listingSha256"):
        raise Refusal("Refused: %s changed since you planned (it was rebuilt or edited): plan again.\n"
                      "Nothing was sent." % listing.path)
    actions = doc["actions"]
    _check_files(listing, actions)
    options = doc.get("options") or {}
    section = listing.section(store)
    if store == "apple":
        if args.cancel_review:
            say("(--cancel-review is for Google Play; ignored.)")
        client = AppleClient.from_env(listing)
        say("Reading the store (%s, App Store Connect)..." % section.get("bundleId"))
        _plan, seen = apple_survey(client, listing, options)
        if seen.fingerprint() != doc["fingerprint"]:
            _refuse_store_changed(doc, seen, "Nothing was sent.")
        for a in actions:
            if a.get("env") and _env_hmac(client.secret, a["env"]) != a.get("envHmac"):
                raise Refusal("Refused: App Review's contact or demo account in the environment (%s) changed since "
                              "you planned: plan again.\nNothing was sent." % ", ".join(sorted(a["env"].values())))
        if not actions:
            say("The store matches the plan, which has no actions: nothing to do.")
            return 0
        say("The store matches the plan. Applying %s." % plural(len(actions), "action"))
        applier = AppleApplier(client, listing)
        try:
            _run_actions(applier, actions)
        except (StoreError, Exit) as e:
            e.after.append("Stopped: the actions before this one were done; the rest weren't tried. Plan again to "
                           "see where the store stands.")
            raise
        say("Done: %s. Plan again to check it arrived (a new plan should have no actions)."
            % plural(len(actions), "action"))
        return 0

    package = section.get("package")
    client = GoogleClient.from_env(listing, package)
    say("Reading the store (%s, Google Play)..." % package)
    in_edit = [a for a in actions if a["kind"] != "google.dataSafety.update"]
    outside = [a for a in actions if a["kind"] == "google.dataSafety.update"]
    edit_id = client.open_edit()
    committed = False
    refused = False
    deleted = None
    try:
        _plan, seen, state = google_survey(client, edit_id, listing)
        if seen.fingerprint() != doc["fingerprint"]:
            refused = True
        else:
            if not actions:
                say("The store matches the plan, which has no actions: nothing to do.")
            else:
                say("The store matches the plan. Applying %s." % plural(len(actions), "action"))
            if in_edit:
                _run_actions(GoogleApplier(client, listing, edit_id, state), in_edit)
                client.call("POST", client.edit_url(edit_id) + ":validate", retry=True)
                behaviour = "CANCEL_IN_REVIEW_AND_SUBMIT" if args.cancel_review else "ERROR_IF_IN_REVIEW"
                say("Committing the edit (changesInReviewBehavior=%s)..." % behaviour)
                # Never sent twice: a commit that failed on Google's side may have gone through.
                client.call("POST", client.edit_url(edit_id) + ":commit?changesInReviewBehavior=" + behaviour,
                            retry=False)
                committed = True
                say("Committed.")
    except (StoreError, Exit) as e:
        if not committed:
            deleted = client.delete_edit(edit_id, "wasn't committed")
            committed = True  # (the edit is dealt with)
            e.after.append("The edit was not committed; nothing is public.%s"
                           % (" The edit was deleted." if deleted else ""))
        raise
    finally:
        if not committed:
            deleted = client.delete_edit(edit_id, "opened to read wasn't committed" if refused or not in_edit
                                         else "wasn't committed")
    if refused:
        _refuse_store_changed(doc, seen, "Nothing was sent.%s" % (" The edit opened to read was deleted."
                                                                  if deleted else ""))
    if outside:
        try:
            _run_actions(GoogleApplier(client, listing, edit_id, {}), outside)
        except (StoreError, Exit) as e:
            if in_edit:
                e.after.append("The edit before it was committed; the Data safety form wasn't sent.")
            raise
    say("Done: %s. Changes can take hours to show on Google Play; plan again to check (a new plan should have no "
        "actions)." % plural(len(actions), "action"))
    return 0


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("%s: %s\n" % (self.prog, message))
        sys.exit(3)


def build_parser():
    parser = _Parser(prog="push.py", description="Plan what would change on a store, then apply exactly that plan.")
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("plan", help="read the store and write what would change (never writes to the store)")
    p.add_argument("store", choices=["apple", "google"])
    p.add_argument("--out", default="out", help="the folder listing.py build wrote (default: out)")
    p.add_argument("--plan", help="where to write the plan (default: plan-<store>.json here)")
    p.add_argument("--age-rating", action="store_true", help="apple: compare and send the age rating answers too")
    p.add_argument("--new-version", metavar="X.Y.Z",
                   help="apple: create this version where a platform has none in preparation")
    a = sub.add_parser("apply", help="perform exactly a plan's actions, if the store hasn't changed since")
    a.add_argument("plan", help="the plan file push.py plan wrote")
    a.add_argument("--cancel-review", action="store_true",
                   help="google: let the commit cancel what's in review (a release too) and resubmit everything")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in ("plan", "apply"):
        parser.print_usage(sys.stderr)
        return 3
    try:
        return cmd_plan(args) if args.command == "plan" else cmd_apply(args)
    except StoreError as e:
        warn(e.report())
        for line in e.after:
            warn(line)
        hint = hint_for(e)
        if hint:
            warn(hint)
        return 1
    except Exit as e:
        warn(e.message)
        for line in e.after:
            warn(line)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
