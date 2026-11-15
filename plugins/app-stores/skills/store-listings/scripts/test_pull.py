"""Tests for ``push.py pull`` (App Store Connect, the public iTunes Lookup API, Google Play), ``listing.py import
--from live`` and ``listing.py diff``, against recorded synthetic answers (``evals/files/pull/``).

No test reaches a network: ``web.TRANSPORT`` is a fake that serves the recorded answers, draws the pictures the
stores' image hosts would serve (at the size their URL names), and records every request.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import unittest
import urllib.parse
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import listing_testkit as kit  # noqa: E402
import push  # noqa: E402
import push_pull  # noqa: E402
from appstores_lib import jwt, web  # noqa: E402
from test_push import FAKE_PEM  # noqa: E402  (a placeholder key: signing is faked here)

FIXTURES = os.path.join(kit.FILES, "pull")
PALETTE = ((52, 120, 198), (200, 60, 60), (30, 160, 90), (240, 140, 30))
# App Review's contact and demo account in the recorded answers: never in anything a pull or an import writes
PERSONAL = ("Testfirst", "Testlast", "555 555 0142", "reviewer-contact@example.com", "demo-user@example.com",
            "not-a-real-password")


def jpeg_bytes(width, height):
    """A JPEG's headers (SOI, APP0, a baseline frame header, EOI): enough for ``png.info``."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def drawn(path):
    """What an image host serves for a path naming ``WxHbb.png`` (a PNG) or ``.jpg`` (a JPEG); None otherwise."""
    m = re.search(r"/(\d+)x(\d+)bb\.(png|jpg)$", path)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    if m.group(3) == "jpg":
        return jpeg_bytes(w, h)
    colour = PALETTE[int(hashlib.md5(path.rsplit("/", 1)[0].encode()).hexdigest(), 16) % len(PALETTE)]
    return kit.png_bytes(w, h, rgb=colour)


class FakeNet(object):
    """Recorded answers keyed ``'METHOD host/path?query'``; the image hosts' pictures drawn; every request kept."""

    def __init__(self, *fixtures):
        self.routes = {}
        for name in fixtures:
            with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
                self.routes.update(json.load(f)["routes"])
        self.requests = []
        self.unknown = []

    @staticmethod
    def key_of(method, url):
        parts = urllib.parse.urlsplit(url)
        key = "%s %s%s" % (method, parts.hostname, urllib.parse.unquote(parts.path))
        if parts.query:
            key += "?" + urllib.parse.unquote(parts.query)
        return key

    def __call__(self, method, url, headers, body, timeout):
        key = self.key_of(method, url)
        self.requests.append((method, url, dict(headers or {}), key))
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        if method == "GET" and (host.endswith("mzstatic.com") or host.endswith("googleusercontent.com")):
            if parts.path.endswith(".mp4"):
                return web.Response(200, {"Content-Type": "video/mp4"}, b"\x00\x00\x00\x18ftypmp42synthetic")
            data = drawn(parts.path)
            if data is None:
                return web.Response(404, {}, b"")
            return web.Response(200, {"Content-Type": "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"},
                                data)
        answer = self.routes.get(key)
        if answer is None:
            self.unknown.append(key)
            return web.Response(404, {}, json.dumps({"errors": [{"status": "404", "detail": "unrecorded"}]}).encode())
        body = answer.get("body")
        if isinstance(body, dict) and isinstance(body.get("images"), list):  # Play's sha256 of its own originals
            for image in body["images"]:
                if image.get("sha256") is None and image.get("url"):
                    image["sha256"] = hashlib.sha256(drawn(urllib.parse.urlsplit(image["url"]).path)).hexdigest()
        data = json.dumps(body).encode() if body is not None else b""
        return web.Response(answer.get("status", 200), {}, data)

    def hosts(self):
        return set(urllib.parse.urlsplit(u).hostname for _, u, _, _ in self.requests)

    def writes(self):
        return [k for m, _, _, k in self.requests if m != "GET"]


class PullCase(unittest.TestCase):
    fixtures = ("apple-asc.json",)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pull-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.cwd)
        self.net = FakeNet(*self.fixtures)
        for name, value in (("TRANSPORT", self.net), ("SLEEP", lambda s: None)):
            p = mock.patch.object(web, name, value)
            p.start()
            self.addCleanup(p.stop)
        for name in ("es256", "rs256"):
            p = mock.patch.object(jwt, name, lambda pem, header, claims: "e30.e30.c2ln")
            p.start()
            self.addCleanup(p.stop)
        account = os.path.join(self.tmp, "account.json")
        with open(account, "w") as f:
            json.dump({"client_email": "store-listings@example-project.iam.gserviceaccount.com",
                       "private_key": FAKE_PEM, "private_key_id": "0123abcd"}, f)
        env = dict((k, v) for k, v in os.environ.items() if not k.startswith(("ASC_", "APPLE_", "GOOGLE_PLAY")))
        env.update({"ASC_KEY_ID": "TESTKEY123", "ASC_ISSUER_ID": "00000000-0000-4000-8000-000000000000",
                    "ASC_PRIVATE_KEY": FAKE_PEM, "GOOGLE_PLAY_SERVICE_ACCOUNT": account})
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.config = os.path.join(self.tmp, "store-listing.json")

    def push(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = push.main(list(argv))
        return code, buf.getvalue()

    def pulled(self, store="apple"):
        with open(os.path.join(self.tmp, "existing", store, "listing.json"), encoding="utf-8") as f:
            return json.load(f)

    def all_written(self, folder):
        out = []
        for root, _, files in os.walk(folder):
            for name in files:
                if name.endswith((".json", ".md", ".txt")):
                    with open(os.path.join(root, name), encoding="utf-8") as f:
                        out.append(f.read())
        return "\n".join(out)

    def listing(self, *argv):
        return kit.run(list(argv), cwd=self.tmp)

    def data(self):
        with open(self.config, encoding="utf-8") as f:
            return json.load(f)


class AppleKeys(PullCase):

    def test_pull_reads_only_and_writes_existing(self):
        code, text = self.push("pull", "apple", "--id", "com.example.samplerecipes")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.net.writes(), [])
        self.assertEqual(self.net.unknown, [])
        self.assertTrue(self.net.hosts() <= {"api.appstoreconnect.apple.com", "is1-ssl.mzstatic.com",
                                             "example-video.mzstatic.com"}, self.net.hosts())
        for method, url, headers, _ in self.net.requests:
            if "mzstatic.com" in url:
                self.assertNotIn("Authorization", headers)  # the key goes only to App Store Connect
        self.assertIn("Nothing was sent to the store", text)
        base = os.path.join(self.tmp, "existing", "apple")
        for rel in ("listing.json", "README.md", "screenshots/en-US/APP_IPHONE_67/01.png",
                    "screenshots/en-US/APP_IPHONE_67/03.png", "screenshots/en-US/APP_IPAD_PRO_3GEN_129/02.png",
                    "screenshots/de-DE/APP_IPHONE_67/02.png", "screenshots/en-US/APP_APPLE_TV/01.png",
                    "previews/en-US/IPHONE_67/01.mp4"):
            self.assertTrue(os.path.isfile(os.path.join(base, rel)), rel)
        self.assertFalse([n for n in os.listdir(os.path.join(self.tmp, "existing")) if n.startswith(".")])

    def test_the_listing_is_in_the_contracts_vocabulary(self):
        self.push("pull", "apple", "--id", "com.example.samplerecipes")
        d = self.pulled()
        self.assertEqual((d["version"], d["store"], d["source"]), (1, "apple", "App Store Connect"))
        A = d["apple"]
        self.assertEqual((A["appId"], A["bundleId"], A["primaryLocale"]), ("1234567890", "com.example.samplerecipes",
                                                                           "en-US"))
        self.assertEqual(A["app"]["categories"]["primary"], "FOOD_AND_DRINK")
        self.assertEqual(A["app"]["categories"]["secondary"], "LIFESTYLE")
        self.assertEqual(A["app"]["localizations"]["de-DE"]["subtitle"], "Rezepte und Essenspläne")
        self.assertEqual(A["app"]["ageRating"]["alcoholTobaccoOrDrugUseOrReferences"], "INFREQUENT_OR_MILD")
        ios = A["platforms"]["IOS"]
        self.assertEqual((ios["version"], ios["state"]), ("1.3", "READY_FOR_DISTRIBUTION"))  # what's live
        self.assertEqual(ios["localizations"]["en-US"]["keywords"], "recipes, meal plan,grocery")
        shots = ios["screenshots"]["en-US"]["APP_IPHONE_67"]
        self.assertEqual([s["fileName"] for s in shots], ["01_APP_IPHONE_67_week.png", "02_APP_IPHONE_67_recipe.png",
                                                          "03_APP_IPHONE_67_grocery-list.png"])
        self.assertEqual((shots[0]["width"], shots[0]["height"]), (1290, 2796))
        self.assertEqual(shots[0]["md5"], "synthetic-upload-checksum-1")
        self.assertNotEqual(shots[0]["downloadedMd5"], shots[0]["md5"])  # the store's copy, not the upload
        self.assertEqual(ios["previews"]["en-US"]["IPHONE_67"][0]["posterFrame"], "00:00:05:00")
        self.assertIn("TV_OS", A["platforms"])
        self.assertEqual(A["review"], {"notes": "Sign in with the demo account; the pantry fills itself after a day.",
                                       "demoAccountRequired": True})
        self.assertTrue(any("1.4 in preparation" in n for n in d["notes"]), d["notes"])

    def test_app_reviews_contact_is_never_written(self):
        self.push("pull", "apple", "--id", "com.example.samplerecipes")
        text = self.all_written(os.path.join(self.tmp, "existing"))
        for value in PERSONAL:
            self.assertNotIn(value, text)

    def test_the_readme_says_whats_there(self):
        self.push("pull", "apple", "--id", "com.example.samplerecipes")
        with open(os.path.join(self.tmp, "existing", "apple", "README.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Read-only: nothing was sent", text)
        self.assertIn("IOS en-US APP_IPHONE_67: 3", text)
        self.assertIn("locales: en-US, de-DE", text)
        self.assertIn("listing.py import --from live", text)

    def test_the_config_names_the_app(self):
        kit.edit_config(self._config_with_ids(), lambda d: None)
        code, text = self.push("pull", "apple", "--config", self.config)
        self.assertEqual(code, 0, text)

    def _config_with_ids(self):
        with open(self.config, "w") as f:
            json.dump({"version": 1, "app": {"ids": {"apple": {"bundleId": "com.example.samplerecipes"}}}}, f)
        return self.config

    def test_no_key_says_public_and_sends_nothing(self):
        del os.environ["ASC_PRIVATE_KEY"]
        code, text = self.push("pull", "apple", "--id", "com.example.samplerecipes")
        self.assertEqual(code, 3)
        self.assertIn("ASC_PRIVATE_KEY isn't set", text)
        self.assertIn("--public", text)
        self.assertEqual(self.net.requests, [])

    def test_no_app_named_is_usage(self):
        code, text = self.push("pull", "apple")
        self.assertEqual(code, 3)
        self.assertIn("--id", text)

    def test_a_folder_it_didnt_write_isnt_replaced(self):
        os.makedirs(os.path.join(self.tmp, "existing", "apple"))
        with open(os.path.join(self.tmp, "existing", "apple", "mine.txt"), "w") as f:
            f.write("the user's")
        code, text = self.push("pull", "apple", "--id", "com.example.samplerecipes")
        self.assertEqual(code, 3)
        self.assertIn("isn't a folder push.py pull wrote", text)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "existing", "apple", "mine.txt")))

    def test_pulling_again_replaces_the_last_pull(self):
        self.push("pull", "apple", "--id", "com.example.samplerecipes")
        stale = os.path.join(self.tmp, "existing", "apple", "screenshots", "en-US", "APP_IPHONE_67", "09.png")
        with open(stale, "wb") as f:
            f.write(b"old")
        code, _ = self.push("pull", "apple", "--id", "com.example.samplerecipes")
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(stale))

    def test_a_picture_elsewhere_isnt_fetched(self):
        key = "GET api.appstoreconnect.apple.com/v1/appScreenshotSets/set-tv-en/appScreenshots?limit=200"
        shot = self.net.routes[key]["body"]["data"][0]
        shot["attributes"]["imageAsset"]["templateUrl"] = "https://images.example.net/{w}x{h}bb.{f}"
        code, text = self.push("pull", "apple", "--id", "com.example.samplerecipes")
        self.assertEqual(code, 1)
        self.assertNotIn("images.example.net", self.net.hosts())
        self.assertIn("not one of the stores' hosts", text)
        self.assertTrue(self.pulled()["failed"])  # the words were still written

    def test_a_store_error_comes_as_it_came(self):
        self.net.routes["GET api.appstoreconnect.apple.com/v1/apps/1234567890/appInfos?limit=200"] = {
            "status": 403, "body": {"errors": [{"status": "403", "code": "FORBIDDEN_ERROR", "detail": "not allowed"}]}}
        code, text = self.push("pull", "apple", "--id", "com.example.samplerecipes")
        self.assertEqual(code, 1)
        self.assertIn("App Store Connect answered 403", text)
        self.assertIn("FORBIDDEN_ERROR", text)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "existing", "apple")))
        self.assertFalse([n for n in os.listdir(os.path.join(self.tmp, "existing")) if n.startswith(".")])

    def test_the_redirect_guard_is_set_while_pulling_and_put_back(self):
        seen = []
        original = self.net.__call__

        def spy(method, url, headers, body, timeout):
            seen.append(web.REDIRECT_ALLOWED)
            return original(method, url, headers, body, timeout)
        with mock.patch.object(web, "TRANSPORT", spy):
            self.push("pull", "apple", "--id", "com.example.samplerecipes")
        self.assertTrue(seen and all(g is push_pull.allowed for g in seen))
        self.assertIsNone(web.REDIRECT_ALLOWED)


class Hosts(unittest.TestCase):
    def test_only_the_stores_hosts(self):
        for url in ("https://api.appstoreconnect.apple.com/v1/apps", "https://itunes.apple.com/lookup?id=1",
                    "https://is1-ssl.mzstatic.com/image/a.png", "https://example-video.mzstatic.com/v.mp4",
                    "https://play-lh.googleusercontent.com/abc", "https://lh3.googleusercontent.com/abc"):
            self.assertTrue(push_pull.allowed(url), url)
        for url in ("http://is1-ssl.mzstatic.com/a.png", "https://mzstatic.com.example.net/a.png",
                    "https://evil-mzstatic.com/a.png", "https://drive.googleusercontent.com/a",
                    "https://example.com/a.png", "https://apps.apple.com/us/app/x/id1"):
            self.assertFalse(push_pull.allowed(url), url)


class ApplePublic(PullCase):
    fixtures = ("itunes-lookup.json",)

    def test_public_needs_no_key_and_reads_only_the_lookup(self):
        for k in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_PRIVATE_KEY"):
            del os.environ[k]
        code, text = self.push("pull", "apple", "--public", "--id", "com.example.samplerecipes", "--country",
                               "us,gb,de,fr")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.net.writes(), [])
        self.assertEqual(self.net.hosts(), {"itunes.apple.com", "is1-ssl.mzstatic.com"})
        d = self.pulled()
        self.assertEqual(d["source"], "iTunes Lookup (public)")
        for field in ("subtitle", "keywords", "promotionalText"):
            self.assertIn(field, d["notPublic"])
        self.assertIn("not public", text)
        A = d["apple"]
        self.assertEqual(sorted(A["app"]["localizations"]), ["de-DE", "en-US"])  # gb's words are us's
        self.assertTrue(any(n.startswith("gb's words are the same as us's") for n in d["notes"]))
        self.assertTrue(any(n.startswith("fr: the fr storefront has no app") for n in d["notes"]))
        self.assertEqual(A["app"]["categories"]["primary"], "FOOD_AND_DRINK")
        self.assertEqual(A["app"]["categories"]["secondary"], "LIFESTYLE")
        ios = A["platforms"]["IOS"]
        self.assertEqual(ios["localizations"]["de-DE"]["description"], "Plane eine Woche voller Mahlzeiten in Minuten.")
        shots = ios["screenshots"]["en-US"]["iphone"]
        self.assertEqual([s["file"] for s in shots], ["screenshots/en-US/iphone/01.jpg", "screenshots/en-US/iphone/02.jpg"])
        self.assertEqual([s["fileName"] for s in shots], ["01_week.png", "02_recipe.png"])
        self.assertEqual((shots[0]["width"], shots[0]["height"]), (392, 696))
        self.assertEqual(d["public"]["us"]["sellerName"], "Example Studio")

    def test_google_has_no_public_listing(self):
        code, text = self.push("pull", "google", "--public", "--id", "com.example.samplerecipes")
        self.assertEqual(code, 3)
        self.assertIn("no public API", text)
        self.assertIn("paste", text)
        self.assertEqual(self.net.requests, [])

    def test_a_country_it_doesnt_know_needs_its_language(self):
        code, text = self.push("pull", "apple", "--public", "--id", "com.example.samplerecipes", "--country", "zz")
        self.assertEqual(code, 3)
        self.assertIn("zz:<locale>", text)
        self.assertEqual(self.net.requests, [])

    def test_an_app_no_storefront_has(self):
        code, text = self.push("pull", "apple", "--public", "--id", "com.example.samplerecipes", "--country", "fr")
        self.assertEqual(code, 1)
        self.assertIn("has no app com.example.samplerecipes", text)


class GoogleKeys(PullCase):
    fixtures = ("google-play.json",)
    EDIT = "androidpublisher.googleapis.com/androidpublisher/v3/applications/com.example.samplerecipes/edits"

    def test_pull_opens_an_edit_and_deletes_it(self):
        code, text = self.push("pull", "google", "--id", "com.example.samplerecipes")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.net.writes(), ["POST oauth2.googleapis.com/token", "POST " + self.EDIT,
                                             "DELETE " + self.EDIT + "/edit-pull-1"])
        self.assertFalse([k for _, _, _, k in self.net.requests if ":commit" in k])
        self.assertEqual(self.net.unknown, [])
        for _, url, headers, _ in self.net.requests:
            if "googleusercontent.com" in url:
                self.assertNotIn("Authorization", headers)
        d = self.pulled("google")
        G = d["google"]
        self.assertEqual(G["defaultLanguage"], "en-US")
        self.assertEqual(list(G["listings"]), ["en-US", "de-DE"])  # the default first
        self.assertEqual(G["listings"]["en-US"]["title"], "Sample Recipes")
        self.assertEqual(len(G["images"]["en-US"]["phoneScreenshots"]), 3)
        icon = G["images"]["en-US"]["icon"][0]
        self.assertEqual(icon["file"], "screenshots/en-US/icon/01.png")
        self.assertEqual(icon["sha256"], icon["downloadedSha256"])
        self.assertTrue(any("opened a Play edit and deleted it" in n for n in d["notes"]))

    def test_the_edit_is_deleted_when_a_read_fails(self):
        self.net.routes["GET " + self.EDIT + "/edit-pull-1/listings"] = {"status": 403, "body": {"error": {
            "code": 403, "message": "The caller does not have permission", "status": "PERMISSION_DENIED"}}}
        code, text = self.push("pull", "google", "--id", "com.example.samplerecipes")
        self.assertEqual(code, 1)
        self.assertIn("DELETE " + self.EDIT + "/edit-pull-1", self.net.writes())
        self.assertIn("PERMISSION_DENIED", text)


# ------------------------------------------------------------------------------------------ import and diff


class ImportLive(PullCase):
    fixtures = ("apple-asc.json", "google-play.json")

    def pull_both(self):
        for store in ("apple", "google"):
            code, text = self.push("pull", store, "--id", "com.example.samplerecipes")
            self.assertEqual(code, 0, text)

    def imp(self):
        code, out, err = self.listing("import", "--from", "live", "existing", "--out", self.config)
        self.assertEqual(code, 0, out + err)
        return out

    def test_a_draft_config_from_whats_live(self):
        self.pull_both()
        out = self.imp()
        d = self.data()
        self.assertEqual(d["app"]["name"], "Sample Recipes")
        self.assertEqual(d["app"]["ids"]["apple"], {"bundleId": "com.example.samplerecipes", "appId": "1234567890"})
        self.assertEqual(d["app"]["ids"]["google"]["package"], "com.example.samplerecipes")
        self.assertEqual(d["app"]["copyright"], "2026 Example Studio")
        self.assertEqual(d["app"]["urls"]["privacy"], "https://example.com/privacy")
        self.assertEqual(d["app"]["contact"]["email"], "support@example.com")
        self.assertIsNone(d["app"]["contact"]["phone"])  # Play's "" is nothing
        en, de = d["locales"]["en-US"], d["locales"]["de-DE"]
        self.assertEqual(en["apple"]["subtitle"], "Recipes and meal plans")
        self.assertEqual(en["apple"]["keywords"], ["recipes", "meal plan", "grocery"])
        self.assertTrue(en["description"].startswith("Plan a week of meals"))
        self.assertIn("Siri Remote", en["apple"]["platforms"]["TV_OS"]["description"])  # Apple TV's own words
        self.assertNotIn("keywords", en["apple"]["platforms"]["TV_OS"])  # the same: left to fall back
        self.assertEqual(de["apple"]["subtitle"], "Rezepte und Essenspläne")
        self.assertEqual(en["google"]["title"], "Sample Recipes")
        self.assertEqual(de["google"]["title"], "Sample Recipes: Essensplaner")
        A = d["stores"]["apple"]
        self.assertEqual(A["categories"]["primary"], "FOOD_AND_DRINK")
        self.assertEqual(A["categories"]["secondary"], "LIFESTYLE")
        self.assertEqual(A["ageRating"]["alcoholTobaccoOrDrugUseOrReferences"], "INFREQUENT_OR_MILD")
        self.assertNotIn("kidsAgeBand", A["ageRating"])
        self.assertEqual(A["review"]["notes"], "Sign in with the demo account; the pantry fills itself after a day.")
        self.assertEqual(A["review"]["demoAccount"], {"usernameEnv": "APPLE_REVIEW_DEMO_USER",
                                                      "passwordEnv": "APPLE_REVIEW_DEMO_PASSWORD"})
        self.assertEqual(sorted(A["locales"]), ["de-DE", "en-US"])
        self.assertEqual(d["stores"]["google"]["defaultLanguage"], "en-US")
        self.assertIn("What's live (as pulled):", out)
        self.assertIn("IOS en-US APP_IPHONE_67: 3", out)
        self.assertIn("listing.py diff", out)
        with open(self.config, encoding="utf-8") as f:
            text = f.read()
        for value in PERSONAL:
            self.assertNotIn(value, text)
        code, report = kit.check_json(self.config)
        self.assertFalse(kit.findings(report, "config.schema"), report["findings"])

    def test_screenshots_go_into_the_layout_with_ids_from_the_uploaded_names(self):
        self.pull_both()
        out = self.imp()
        d = self.data()
        shots = [s["id"] for s in d["screenshots"]["shots"]]
        for sid in ("week", "recipe", "grocery-list"):
            self.assertIn(sid, shots)
        for rel in ("screenshots/en-US/iphone/week.png", "screenshots/en-US/ipad/week.png",
                    "screenshots/de-DE/iphone/week.png", "screenshots/de-DE/iphone/recipe.png",
                    "screenshots/en-US/apple-tv/week.png"):
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, rel)), rel)  # de-DE takes en-US's ids by position
        self.assertEqual(d["stores"]["apple"]["platforms"]["IOS"]["screens"], ["iphone", "ipad"])
        self.assertEqual(d["stores"]["apple"]["platforms"]["TV_OS"]["screens"], ["apple-tv"])
        self.assertEqual(d["stores"]["google"]["slots"]["phone"], "android-phone")
        self.assertEqual(d["stores"]["google"]["slots"]["tablet7"], "android-tablet")
        self.assertEqual(d["stores"]["google"]["slots"]["tablet10"], "android-tablet")
        self.assertEqual(d["stores"]["google"]["graphics"]["icon"], "graphics/icon.png")
        self.assertIn("App Store Connect's own copies", out)  # a plan would replace the store's with them
        self.assertIn("the store has no TV_OS de-DE listing", out)

    def test_whats_empty_on_the_store_stays_empty(self):
        self.pull_both()
        out = self.imp()
        d = self.data()
        self.assertEqual(d["locales"]["de-DE"]["apple"]["promotionalText"], "")  # not en-US's, by fallback
        self.assertEqual(d["locales"]["de-DE"]["google"]["video"], "")
        self.assertNotIn("promotionalText", d["locales"]["en-US"]["apple"].get("platforms", {}).get("TV_OS", {}))
        self.assertIn('set to ""', out)

    def test_import_never_overwrites_the_users_config(self):
        self.pull_both()
        self.imp()

        def edit(d):
            d["locales"]["en-US"]["apple"]["subtitle"] = "Meals planned in minutes"
            d["locales"]["en-US"]["description"] = "Our new words."
        kit.edit_config(self.config, edit)
        out = self.imp()
        d = self.data()
        self.assertEqual(d["locales"]["en-US"]["apple"]["subtitle"], "Meals planned in minutes")
        self.assertEqual(d["locales"]["en-US"]["description"], "Our new words.")
        self.assertIn("Kept what the config already had", out)
        self.assertIn("locales.en-US.apple.subtitle", out)

    def test_public_pictures_stay_as_the_reference(self):
        self.net = FakeNet("itunes-lookup.json")
        with mock.patch.object(web, "TRANSPORT", self.net):
            code, text = self.push("pull", "apple", "--public", "--id", "com.example.samplerecipes")
        self.assertEqual(code, 0, text)
        out = self.imp()
        d = self.data()
        self.assertEqual(d["screenshots"]["shots"], [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "screenshots")))
        self.assertIn("the public page's smaller copies", out)
        self.assertIn("subtitle, keywords, promotionalText", out)
        self.assertEqual(d["locales"]["en-US"]["description"][:11], "Plan a week")
        self.assertEqual(d["app"]["name"], "Sample Recipes: Meal Planner")

    def test_nothing_pulled_is_usage(self):
        code, out, err = self.listing("import", "--from", "live", "existing", "--out", self.config)
        self.assertEqual(code, 3)
        self.assertIn("push.py pull", err)


class Diff(ImportLive):

    def diff(self, *extra):
        code, out, err = self.listing("diff", "--config", self.config, "--existing", "existing", *extra)
        self.assertEqual(code, 0, out + err)
        return out

    def entries(self, store="apple"):
        report = json.loads(self.diff("--json"))
        return report["stores"][store]["entries"]

    def find(self, entries, field, locale=None, platform=None):
        hits = [e for e in entries if e["field"] == field and (locale is None or e["locale"] == locale)
                and (platform is None or e["platform"] == platform)]
        self.assertEqual(len(hits), 1, (field, locale, platform, hits))
        return hits[0]

    def test_an_imported_config_matches_whats_live(self):
        self.pull_both()
        self.imp()
        apple = [(e["locale"], e["platform"], e["field"], e["status"]) for e in self.entries("apple")
                 if e["status"] != "unchanged" and e["kind"] != "pictures"]
        # What a plan would still change: the copyright's © (Apple adds it), and the de-DE listing Apple TV hasn't
        # (the config's App Store locales are every platform's), as the import's notes say.
        self.assertEqual(set((l, p, f, s) for l, p, f, s in apple), {
            ("de-DE", "TV_OS", "listing", "only-ours"), (None, "IOS", "copyright", "changed"),
            (None, "TV_OS", "copyright", "changed")})
        google = [e for e in self.entries("google") if e["status"] != "unchanged" and e["kind"] == "words"]
        self.assertEqual(google, [])
        out = self.diff()
        self.assertIn("= name", out)
        self.assertIn("Nothing was sent", out)

    def test_each_kind_of_difference(self):
        self.pull_both()
        self.imp()

        def edit(d):
            d["locales"]["en-US"]["apple"]["subtitle"] = "Plan meals in minutes"
            d["locales"]["en-US"]["apple"]["promotionalText"] = None
            d["locales"]["de-DE"]["apple"]["promotionalText"] = "Neu: die Vorratskammer."
        kit.edit_config(self.config, edit)
        entries = self.entries()
        sub = self.find(entries, "subtitle", "en-US")
        self.assertEqual((sub["status"], sub["live"], sub["ours"]),
                         ("changed", "Recipes and meal plans", "Plan meals in minutes"))
        # en-US's promotional text unset: it falls back to nothing, so the store keeps its own
        self.assertEqual(self.find(entries, "promotionalText", "en-US", "IOS")["status"], "only-live")
        self.assertEqual(self.find(entries, "promotionalText", "de-DE", "IOS")["status"], "only-ours")
        self.assertEqual(self.find(entries, "keywords", "en-US", "IOS")["status"], "unchanged")  # spaces don't count
        pics = self.find(entries, "APP_IPHONE_67", "en-US", "IOS")
        self.assertEqual((pics["kind"], pics["live"], pics["ours"]), ("pictures", 3, 3))
        out = self.diff()
        self.assertIn("~ subtitle: 'Recipes and meal plans' → 'Plan meals in minutes'", out)
        self.assertIn("- IOS promotionalText: only live", out)
        self.assertIn("+ IOS promotionalText: only ours", out)
        self.assertRegex(out, r"Summary: \d+ changed")
        self.assertIn("+ TV_OS listing: only ours: the store has no de-DE listing there", out)

    def test_long_texts_show_where_they_part(self):
        self.pull_both()
        self.imp()
        kit.edit_config(self.config, lambda d: d["locales"]["en-US"].update(
            {"description": "Plan a week of meals in minutes. Sample Recipes picks recipes you love."}))
        out = self.diff()
        self.assertIn("~ IOS description (110 → 71 characters), from character 66: '…cks recipes you'll like and writes the grocery li…' → '…cks recipes you love.'", out)

    def test_public_fields_arent_compared(self):
        self.net = FakeNet("itunes-lookup.json")
        with mock.patch.object(web, "TRANSPORT", self.net):
            self.push("pull", "apple", "--public", "--id", "com.example.samplerecipes")
        self.imp()
        kit.edit_config(self.config, lambda d: d["locales"]["en-US"].setdefault("apple", {}).update(
            {"subtitle": "Plan meals in minutes"}))
        report = json.loads(self.diff("--json"))
        fields = set(e["field"] for e in report["stores"]["apple"]["entries"])
        self.assertNotIn("subtitle", fields)
        self.assertIn("description", fields)
        self.assertTrue(any("aren't public" in n for n in report["notes"]))

    def test_no_pull_is_usage(self):
        kit.make_sample(self.tmp)
        code, out, err = self.listing("diff", "--config", self.config, "--existing", "existing")
        self.assertEqual(code, 3)
        self.assertIn("push.py pull", err)


if __name__ == "__main__":
    unittest.main()
