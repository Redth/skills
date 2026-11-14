"""Tests for push.py against App Store Connect's recorded answers (evals/files/push/apple-store.json).

No test reaches a network: ``web.TRANSPORT`` is a fake that serves recorded answers and records every request,
and ``web.SLEEP`` doesn't wait. Keys are throwaway ones made with openssl in a temporary folder (signing is faked
when openssl isn't there, and the key-format tests are skipped).
"""

from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import push  # noqa: E402
from appstores_lib import jwt, web  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(HERE), "evals", "files", "push")
OPENSSL = shutil.which("openssl")
KEYS = {}


def setUpModule():
    """Make throwaway keys once: an EC P-256 key (App Store Connect's) and an RSA key (a service account's)."""
    folder = tempfile.mkdtemp(prefix="push-test-keys-")
    KEYS["folder"] = folder
    if not OPENSSL:
        return
    ec = os.path.join(folder, "ec.pem")
    p8 = os.path.join(folder, "AuthKey_TEST.p8")
    rsa = os.path.join(folder, "rsa.pem")
    run = lambda *args: subprocess.run([OPENSSL] + list(args), check=True, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
    run("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", ec)
    run("pkcs8", "-topk8", "-nocrypt", "-in", ec, "-out", p8)
    run("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", rsa)
    run("pkey", "-in", p8, "-pubout", "-out", os.path.join(folder, "ec.pub"))
    run("pkey", "-in", rsa, "-pubout", "-out", os.path.join(folder, "rsa.pub"))
    KEYS["p8"] = p8
    KEYS["rsa"] = rsa
    with open(rsa) as f:
        account = {"type": "service_account", "project_id": "example-project", "private_key_id": "0123abcd",
                   "private_key": f.read(), "client_email": "store-listings@example-project.iam.gserviceaccount.com",
                   "token_uri": "https://oauth2.googleapis.com/token"}
    KEYS["account"] = os.path.join(folder, "service-account.json")
    with open(KEYS["account"], "w") as f:
        json.dump(account, f)


def tearDownModule():
    shutil.rmtree(KEYS.get("folder", ""), ignore_errors=True)


FAKE_PEM = "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"


def fake_account_path():
    path = os.path.join(KEYS["folder"], "fake-account.json")
    with open(path, "w") as f:
        json.dump({"client_email": "store-listings@example-project.iam.gserviceaccount.com",
                   "private_key": FAKE_PEM, "private_key_id": "0123abcd"}, f)
    return path


class Request(object):
    def __init__(self, method, url, key, headers, body):
        self.method = method
        self.url = url
        self.key = key
        self.headers = headers
        self.body = body

    def json(self):
        return json.loads(self.body.decode("utf-8")) if self.body else None

    def __repr__(self):
        return self.key


class FakeStore(object):
    """Serves recorded answers keyed by 'METHOD /path?query', and records every request.

    ``queue[key]`` answers are served first, in order. Google's images are kept as Play would (a DELETE empties a
    type, an upload adds one), so a plan's read and an apply's verification agree.
    """

    IMAGE = re.compile(r"^(GET|DELETE) /androidpublisher/v3/applications/[^/]+/edits/[^/]+/listings/([^/]+)/"
                       r"(\w+Screenshots|icon|featureGraphic|tvBanner)$")
    UPLOAD = re.compile(r"^POST /upload/androidpublisher/v3/applications/[^/]+/edits/[^/]+/listings/([^/]+)/"
                        r"(\w+Screenshots|icon|featureGraphic|tvBanner)\?uploadType=media$")

    def __init__(self, fixture, out_dir):
        with open(os.path.join(FIXTURES, fixture), encoding="utf-8") as f:
            doc = json.load(f)
        self.out = out_dir
        self.routes = self._subst(doc["routes"])
        self.alternates = self._subst(doc.get("alternates") or {})
        self.images = {}
        for key, shas in self._subst(doc.get("images") or {}).items():
            self.images[key] = [{"id": "img-%d" % i, "sha256": s} for i, s in enumerate(shas, 1)]
        self.queue = {}
        self.requests = []
        self.unknown = []
        self.made = 0
        self.duplicate_next_upload = False

    def _subst(self, value):
        if isinstance(value, dict):
            return dict((k, self._subst(v)) for k, v in value.items())
        if isinstance(value, list):
            return [self._subst(v) for v in value]
        if isinstance(value, str):
            for prefix, algo in (("$md5:", "md5"), ("$sha256:", "sha256")):
                if value.startswith(prefix):
                    with open(os.path.join(self.out, value[len(prefix):]), "rb") as f:
                        return hashlib.new(algo, f.read()).hexdigest()
        return value

    @staticmethod
    def key_of(method, url):
        parts = urllib.parse.urlsplit(url)
        key = method + " " + urllib.parse.unquote(parts.path)
        if parts.query:
            key += "?" + urllib.parse.unquote(parts.query)
        return key

    def since(self, n):
        return self.requests[n:]

    def writes(self, start=0):
        return [r for r in self.requests[start:] if r.method != "GET"]

    def keys(self, start=0):
        return [r.key for r in self.requests[start:]]

    def __call__(self, method, url, headers, body, timeout):
        key = self.key_of(method, url)
        req = Request(method, url, key, dict(headers or {}), body)
        self.requests.append(req)
        if self.queue.get(key):
            return self._answer(self.queue[key].pop(0), req)
        m = self.IMAGE.match(key)
        if m:
            state = self.images.setdefault("%s/%s" % (m.group(2), m.group(3)), [])
            if m.group(1) == "GET":
                return web.Response(200, {}, json.dumps({"images": state}).encode())
            deleted = list(state)
            del state[:]
            return web.Response(200, {}, json.dumps({"deleted": deleted}).encode())
        m = self.UPLOAD.match(key)
        if m:
            state = self.images.setdefault("%s/%s" % (m.group(1), m.group(2)), [])
            image = {"id": "img-up-%d" % (len(self.requests)), "sha256": hashlib.sha256(body).hexdigest()}
            state.append(image)
            if self.duplicate_next_upload:
                self.duplicate_next_upload = False
                state.append(dict(image, id=image["id"] + "-again"))
            return web.Response(200, {}, json.dumps({"image": image}).encode())
        answer = self.routes.get(key)
        if answer is None:
            for k, v in self.routes.items():
                if k.endswith("*") and key.startswith(k[:-1]):
                    answer = v
                    break
        if answer is None:
            self.unknown.append(key)
            return web.Response(404, {}, json.dumps({"errors": [{"status": "404", "code": "NOT_FOUND",
                                                                 "detail": "unrecorded: " + key}]}).encode())
        return self._answer(answer, req)

    def _answer(self, answer, req):
        if "$reserve" in answer:
            items = answer["$reserve"]
            self.made += 1
            new_id = "%s-new-%d" % (items, self.made)
            a = req.json()["data"]["attributes"]
            size = a["fileSize"]
            half = size // 2
            ops = []
            for i, (offset, length) in enumerate([(0, half), (half, size - half)]):
                ops.append({"method": "PUT", "url": "https://store-uploads.example.com/upload/%s/%d" % (new_id, i),
                            "offset": offset, "length": length,
                            "requestHeaders": [{"name": "Content-Type", "value": "application/octet-stream"}]})
            body = {"data": {"type": items, "id": new_id, "attributes": dict(a, uploadOperations=ops,
                                                                              assetDeliveryState={"state": "AWAITING_UPLOAD"})}}
            return web.Response(201, {}, json.dumps(body).encode())
        if "$echo" in answer:
            return web.Response(200, {}, req.body or b"{}")
        if "$delivery" in answer:
            item_id = req.key.rsplit("/", 1)[1]
            body = {"data": {"type": "x", "id": item_id, "attributes": {
                "fileName": item_id + ".png", "assetDeliveryState": {"state": answer["$delivery"], "errors": []}}}}
            return web.Response(200, {}, json.dumps(body).encode())
        body = answer.get("body")
        data = json.dumps(body).encode() if body is not None else b""
        return web.Response(answer.get("status", 200), answer.get("headers") or {}, data)


class PushCase(unittest.TestCase):
    """A temporary project folder holding a copy of the fixture's out/, with the fake store installed."""

    fixture = "apple-store.json"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="push-test-")
        self.out = os.path.join(self.tmp, "out")
        shutil.copytree(os.path.join(FIXTURES, "out"), self.out)
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.cwd)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = FakeStore(self.fixture, self.out)
        for name, value in (("TRANSPORT", self.store), ("SLEEP", lambda s: None)):
            p = mock.patch.object(web, name, value)
            p.start()
            self.addCleanup(p.stop)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("ASC_", "APPLE_", "GOOGLE_PLAY", "OTHER_"))}
        env.update({
            "ASC_KEY_ID": "TESTKEY123", "ASC_ISSUER_ID": "00000000-0000-4000-8000-000000000000",
            "APPLE_REVIEW_FIRST_NAME": "Alex", "APPLE_REVIEW_LAST_NAME": "Example",
            "APPLE_REVIEW_PHONE": "+1 555 555 0199", "APPLE_REVIEW_EMAIL": "review@example.com",
        })
        if OPENSSL:
            env["ASC_PRIVATE_KEY"] = KEYS["p8"]
            env["GOOGLE_PLAY_SERVICE_ACCOUNT"] = KEYS["account"]
        else:
            env["ASC_PRIVATE_KEY"] = FAKE_PEM
            env["GOOGLE_PLAY_SERVICE_ACCOUNT"] = fake_account_path()
            for name in ("es256", "rs256"):
                p = mock.patch.object(jwt, name, lambda pem, header, claims: "e30.e30.c2ln")
                p.start()
                self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def run_push(self, *argv):
        """Run push.py's main; returns (exit code, everything printed, stdout and stderr interleaved)."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = push.main(list(argv))
        return code, buf.getvalue()

    def plan(self, store, *extra):
        code, text = self.run_push("plan", store, "--plan", "plan-%s.json" % store, *extra)
        self.assertEqual(code, 0, text)
        with open(os.path.join(self.tmp, "plan-%s.json" % store), encoding="utf-8") as f:
            return json.load(f), text

    def listing(self):
        with open(os.path.join(self.out, "listing.json"), encoding="utf-8") as f:
            return json.load(f)

    def write_listing(self, data):
        with open(os.path.join(self.out, "listing.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def actions(plan, kind=None, **match):
        found = [a for a in plan["actions"] if kind is None or a["kind"] == kind]
        return [a for a in found if all(a.get(k) == v for k, v in match.items())]


class ApplePlanTests(PushCase):

    def test_plan_only_reads(self):
        plan, text = self.plan("apple")
        self.assertTrue(self.store.requests)
        self.assertEqual([r.key for r in self.store.requests if r.method != "GET"], [])
        self.assertEqual(self.store.unknown, [])
        self.assertIn("Nothing was sent", text)
        for r in self.store.requests:
            self.assertTrue(r.url.startswith("https://api.appstoreconnect.apple.com/"), r.url)
            self.assertTrue(r.headers["Authorization"].startswith("Bearer "))

    def test_plan_file_shape(self):
        plan, _ = self.plan("apple")
        self.assertEqual(plan["version"], 1)
        self.assertEqual(plan["store"], "apple")
        self.assertEqual(plan["listing"], os.path.join("out", "listing.json"))
        with open(os.path.join(self.out, "listing.json"), "rb") as f:
            self.assertEqual(plan["listingSha256"], hashlib.sha256(f.read()).hexdigest())
        self.assertRegex(plan["fingerprint"], r"^[0-9a-f]{64}$")
        self.assertEqual(plan["options"], {"ageRating": False, "newVersion": None})
        self.assertEqual([a["id"] for a in plan["actions"]], list(range(1, len(plan["actions"]) + 1)))
        for a in plan["actions"]:
            self.assertTrue(a["summary"])

    def test_words_and_app_info(self):
        plan, _ = self.plan("apple")
        cats = self.actions(plan, "apple.categories.update")
        self.assertEqual(len(cats), 1)
        self.assertEqual(cats[0]["set"], {"secondaryCategory": "LIFESTYLE"})
        upd = self.actions(plan, "apple.appInfo.localization.update", locale="en-US")
        self.assertEqual(upd[0]["set"], {"subtitle": "Plan meals in minutes"})
        self.assertIn("'Recipes and meal plans' → 'Plan meals in minutes'", upd[0]["summary"])
        self.assertEqual(len(self.actions(plan, "apple.appInfo.localization.create", locale="de-DE")), 1)
        self.assertEqual(self.actions(plan, "apple.version.update")[0]["set"], {"copyright": "2026 Example Studio"})
        en = self.actions(plan, "apple.version.localization.update", platform="IOS", locale="en-US")
        # Keywords differ only by spaces after commas: not a change.
        self.assertEqual(list(en[0]["set"]), ["description"])
        de = self.actions(plan, "apple.version.localization.create", platform="IOS", locale="de-DE")
        self.assertEqual(de[0]["set"]["keywords"], "rezepte,essensplan,einkauf")
        self.assertNotIn("promotionalText", de[0]["set"])  # null: not set
        self.assertEqual(self.actions(plan, "apple.ageRating.update"), [])
        self.assertTrue(any("--age-rating" in n for n in plan["notes"]))

    def test_screenshot_sets_unchanged_reorder_replace(self):
        plan, _ = self.plan("apple")
        self.assertIn("IOS en-US APP_IPHONE_67: 3 screenshots, as they are", plan["unchanged"])
        self.assertEqual(self.actions(plan, displayType="APP_IPHONE_67", locale="en-US"), [])
        reorder = self.actions(plan, "apple.screenshots.reorder")
        self.assertEqual(len(reorder), 1)
        self.assertEqual(reorder[0]["displayType"], "APP_IPAD_PRO_3GEN_129")
        self.assertEqual(reorder[0]["order"], ["shot-129-p", "shot-129-r", "shot-129-s"])
        replace = self.actions(plan, "apple.screenshots.replace", locale="en-US")
        self.assertEqual(len(replace), 1)
        r = replace[0]
        self.assertEqual(r["displayType"], "APP_IPHONE_61")
        self.assertEqual(r["setId"], "set-61")
        self.assertEqual(r["items"][0], {"reuse": "shot-61-p"})
        self.assertEqual(r["items"][1]["upload"]["file"], "apple/IOS/screenshots/en-US/02_APP_IPHONE_61_recipe.png")
        self.assertEqual(r["delete"], ["shot-61-old"])
        self.assertIn("1 kept, 1 new, 1 removed", r["summary"])

    def test_sets_not_listed_are_never_read_or_touched(self):
        self.plan("apple")
        self.assertFalse([k for k in self.store.keys() if "set-55" in k])

    def test_pagination_followed(self):
        plan, _ = self.plan("apple")
        self.assertIn("GET /v1/appScreenshotSets/set-129/appScreenshots?cursor=Mg&limit=200", self.store.keys())
        # The third picture is only on the second page: without it this would be a replace, not a reorder.
        self.assertIn("shot-129-s", self.actions(plan, "apple.screenshots.reorder")[0]["order"])

    def test_new_localization_gets_its_sets_by_reference(self):
        plan, _ = self.plan("apple")
        create = self.actions(plan, "apple.version.localization.create", locale="de-DE")[0]
        shots = self.actions(plan, "apple.screenshots.replace", locale="de-DE")
        self.assertEqual(len(shots), 1)
        self.assertIsNone(shots[0]["setId"])
        self.assertEqual(shots[0]["localizationFrom"], create["id"])
        self.assertLess(create["id"], shots[0]["id"])

    def test_previews_mime_and_poster_frame(self):
        plan, _ = self.plan("apple")
        p = self.actions(plan, "apple.previews.replace")
        self.assertEqual(len(p), 1)
        up = p[0]["items"][0]["upload"]
        self.assertEqual(up["mime"], "video/mp4")
        self.assertEqual(up["posterFrame"], "00:00:05:00")
        self.assertEqual(p[0]["previewType"], "IPHONE_67")

    def test_whats_new_left_out_on_a_first_version(self):
        versions = self.store.routes["GET /v1/apps/1234567890/appStoreVersions?filter[platform]=IOS&limit=200"]
        del versions["body"]["data"][1]
        plan, _ = self.plan("apple")
        de = self.actions(plan, "apple.version.localization.create", locale="de-DE")[0]
        self.assertNotIn("whatsNew", de["set"])
        self.assertTrue(any("What's New is left out on a first version" in n for n in plan["notes"]))

    def test_empty_whats_new_clears_it_and_null_leaves_it(self):
        data = self.listing()
        data["apple"]["platforms"]["IOS"]["localizations"]["en-US"]["whatsNew"] = ""
        self.write_listing(data)
        plan, _ = self.plan("apple")
        en = self.actions(plan, "apple.version.localization.update", locale="en-US", platform="IOS")[0]
        self.assertEqual(en["set"]["whatsNew"], "")
        data["apple"]["platforms"]["IOS"]["localizations"]["en-US"]["whatsNew"] = None
        self.write_listing(data)
        plan, _ = self.plan("apple")
        en = self.actions(plan, "apple.version.localization.update", locale="en-US", platform="IOS")[0]
        self.assertNotIn("whatsNew", en["set"])

    def test_preview_mime_from_extension(self):
        data = self.listing()
        entry = data["apple"]["platforms"]["IOS"]["previews"]["en-US"]["IPHONE_67"][0]
        os.rename(os.path.join(self.out, entry["file"]), os.path.join(self.out, entry["file"][:-4] + ".mov"))
        entry["file"] = entry["file"][:-4] + ".mov"
        del entry["mime"]
        self.write_listing(data)
        plan, _ = self.plan("apple")
        self.assertEqual(self.actions(plan, "apple.previews.replace")[0]["items"][0]["upload"]["mime"],
                         "video/quicktime")

    def test_no_version_in_preparation(self):
        plan, _ = self.plan("apple")
        self.assertTrue(any(n.startswith("TV_OS: no version in preparation") and "--new-version" in n
                            for n in plan["notes"]))
        tv = self.actions(plan, platform="TV_OS")
        # Only promotional text, on the version on sale: it changes any time, without review.
        self.assertEqual([(a["kind"], a["set"]) for a in tv],
                         [("apple.version.localization.update", {"promotionalText": "New: weekly plans."})])
        self.assertEqual(tv[0]["localizationId"], "loc-tv-en")
        self.assertFalse([k for k in self.store.keys() if "ver-tv-10/appStoreReviewDetail" in k])
        # App-level information still goes.
        self.assertTrue(self.actions(plan, "apple.appInfo.localization.update"))

    def test_new_version(self):
        plan, _ = self.plan("apple", "--new-version", "1.2.0")
        made = self.actions(plan, "apple.version.create")
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0]["platform"], "TV_OS")
        self.assertEqual(made[0]["set"], {"platform": "TV_OS", "versionString": "1.2.0",
                                          "copyright": "2026 Example Studio"})
        self.assertEqual([a["kind"] for a in self.actions(plan, platform="TV_OS")], ["apple.version.create"])
        self.assertTrue(any("run plan apple again" in n for n in plan["notes"]))
        self.assertTrue(any(n.startswith("IOS already has version 1.1") for n in plan["notes"]))
        self.assertEqual(plan["options"]["newVersion"], "1.2.0")

    def test_age_rating_only_when_asked(self):
        plan, _ = self.plan("apple", "--age-rating")
        rating = self.actions(plan, "apple.ageRating.update")
        self.assertEqual(rating[0]["set"], {"contests": "NONE"})
        self.assertEqual(rating[0]["declarationId"], "age-1")

    def test_phone_masked_and_contact_never_written(self):
        plan, text = self.plan("apple")
        review = self.actions(plan, "apple.review.update")
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["env"], {"contactPhone": "APPLE_REVIEW_PHONE"})
        self.assertIn("'…0100' → '…0199'", review[0]["summary"])
        with open(os.path.join(self.tmp, "plan-apple.json"), encoding="utf-8") as f:
            written = f.read()
        for shown in (text, written):
            for secret in ("555 0199", "5550199", "555 0100", "Alex", "review@example.com"):
                self.assertNotIn(secret, shown)
        self.assertIn("…0199", text)

    def test_missing_review_contact_is_a_note(self):
        del os.environ["APPLE_REVIEW_PHONE"]
        plan, _ = self.plan("apple")
        self.assertEqual(self.actions(plan, "apple.review.update"), [])
        self.assertIn("App Review's contact: APPLE_REVIEW_PHONE isn't set, so it's left as App Store Connect has it.",
                      plan["notes"])

    def test_demo_account_from_env(self):
        data = self.listing()
        data["apple"]["review"]["demoAccount"] = {"usernameEnv": "APPLE_DEMO_USER", "passwordEnv": "APPLE_DEMO_PASSWORD"}
        self.write_listing(data)
        os.environ["APPLE_DEMO_USER"] = "demo@example.com"
        os.environ["APPLE_DEMO_PASSWORD"] = "synthetic-password-1"
        plan, text = self.plan("apple")
        review = self.actions(plan, "apple.review.update")[0]
        self.assertEqual(review["set"], {"demoAccountRequired": True})
        self.assertEqual(review["env"]["demoAccountPassword"], "APPLE_DEMO_PASSWORD")
        self.assertNotIn("synthetic-password-1", text)

    def test_primary_locale_mismatch_is_a_note(self):
        data = self.listing()
        data["apple"]["primaryLocale"] = "en-GB"
        self.write_listing(data)
        plan, _ = self.plan("apple")
        self.assertTrue(any("primary language in App Store Connect is en-US" in n for n in plan["notes"]))

    def test_missing_key_exits_3(self):
        del os.environ["ASC_KEY_ID"]
        code, text = self.run_push("plan", "apple")
        self.assertEqual(code, 3)
        self.assertIn("ASC_KEY_ID isn't set", text)
        self.assertEqual(self.store.requests, [])

    def test_auth_names_other_variables(self):
        data = self.listing()
        data["apple"]["auth"] = {"keyIdEnv": "OTHER_KEY_ID"}
        self.write_listing(data)
        code, text = self.run_push("plan", "apple")
        self.assertEqual(code, 3)
        self.assertIn("OTHER_KEY_ID isn't set", text)

    def test_stale_build_stops(self):
        with open(os.path.join(self.out, "apple/IOS/screenshots/en-US/02_APP_IPHONE_61_recipe.png"), "ab") as f:
            f.write(b"changed")
        code, text = self.run_push("plan", "apple")
        self.assertEqual(code, 1)
        self.assertIn("run listing.py build again", text)

    def test_no_listing_exits_3(self):
        code, text = self.run_push("plan", "apple", "--out", "elsewhere")
        self.assertEqual(code, 3)
        self.assertIn("listing.py build", text)

    def test_bad_usage_exits_3(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), self.assertRaises(SystemExit) as raised:
            push.main(["plan", "amazon"])
        self.assertEqual(raised.exception.code, 3)

    def test_store_error_as_it_came(self):
        self.store.queue["GET /v1/apps/1234567890/appInfos?limit=200"] = [{"status": 403, "body": {"errors": [
            {"status": "403", "code": "FORBIDDEN_ERROR", "title": "This request is forbidden for security reasons",
             "detail": "The API key in use does not allow this request"}]}}]
        code, text = self.run_push("plan", "apple")
        self.assertEqual(code, 1)
        self.assertIn("App Store Connect answered 403", text)
        self.assertIn('"code": "FORBIDDEN_ERROR"', text)
        self.assertIn("App Manager or Admin", text)


class AppleApplyTests(PushCase):

    def test_apply_does_the_plan_in_order(self):
        plan, _ = self.plan("apple", "--age-rating")
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.store.unknown, [])
        self.assertIn("The store matches the plan. Applying %d actions." % len(plan["actions"]), text)
        for a in plan["actions"]:
            self.assertRegex(text, r"\n  %d %s[^\n]*: done" % (a["id"], re.escape(a["kind"])))
        writes = [r.key for r in self.store.writes(start)]
        # The plan's actions, in the plan's order.
        firsts = ["PATCH /v1/appInfos/info-next", "POST /v1/appInfoLocalizations",
                  "PATCH /v1/appInfoLocalizations/ail-en", "PATCH /v1/ageRatingDeclarations/age-1",
                  "PATCH /v1/appStoreVersions/ver-ios-11"]
        self.assertEqual(writes[:len(firsts)], firsts)
        printed = [int(m) for m in re.findall(r"\n  (\d+) apple\.", text)]
        self.assertEqual(printed, [a["id"] for a in plan["actions"]])
        self.assertNotIn("DELETE /v1/appScreenshots/shot-129-r", writes)

    def test_replace_uploads_new_before_deleting_old(self):
        self.plan("apple")
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 0, text)
        reqs = self.store.since(0)[start:]
        keys = [r.key for r in reqs]
        reserve = [i for i, r in enumerate(reqs) if r.key == "POST /v1/appScreenshots"
                   and r.json()["data"]["relationships"]["appScreenshotSet"]["data"]["id"] == "set-61"]
        self.assertEqual(len(reserve), 1)
        order = keys.index("PATCH /v1/appScreenshotSets/set-61/relationships/appScreenshots")
        delete = keys.index("DELETE /v1/appScreenshots/shot-61-old")
        self.assertLess(reserve[0], order)
        self.assertLess(order, delete)
        new_id = json.loads(self.store.requests[start + reserve[0]].body)["data"]["attributes"]["fileName"]
        self.assertEqual(new_id, "02_APP_IPHONE_61_recipe.png")
        ids = [d["id"] for d in reqs[order].json()["data"]]
        self.assertEqual(ids[0], "shot-61-p")
        self.assertEqual(ids[-1], "shot-61-old")  # still there until after the new ones are in order
        # Processing was awaited before the order was set.
        polled = [i for i, k in enumerate(keys) if k.startswith("GET /v1/appScreenshots/appScreenshots-new-")]
        self.assertTrue(polled and min(polled) < order)

    def test_upload_parts_and_commit(self):
        self.plan("apple")
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 0, text)
        reqs = self.store.requests[start:]
        rel = "apple/IOS/screenshots/en-US/02_APP_IPHONE_61_recipe.png"
        with open(os.path.join(self.out, rel), "rb") as f:
            content = f.read()
        reserve = [r for r in reqs if r.key == "POST /v1/appScreenshots"
                   and r.json()["data"]["attributes"]["fileName"] == os.path.basename(rel)][0]
        self.assertEqual(reserve.json()["data"]["attributes"]["fileSize"], len(content))
        resp_id = [r for r in reqs if r.key.startswith("PUT /upload/")]
        parts = [r for r in resp_id if r.url.startswith("https://store-uploads.example.com/upload/")]
        by_id = {}
        for r in parts:
            by_id.setdefault(r.key.split("/")[2], []).append(r)
        sent = [b"".join(p.body for p in ps) for ps in by_id.values()]
        self.assertIn(content, sent)
        for p in parts:
            self.assertNotIn("Authorization", p.headers)  # the upload host gets no API token
        commits = [r for r in reqs if r.method == "PATCH" and r.key.startswith("PATCH /v1/appScreenshots/")]
        self.assertIn(hashlib.md5(content).hexdigest(),
                      [c.json()["data"]["attributes"]["sourceFileChecksum"] for c in commits])
        for c in commits:
            self.assertIs(c.json()["data"]["attributes"]["uploaded"], True)
        preview = [r for r in reqs if r.key == "POST /v1/appPreviews"][0].json()["data"]["attributes"]
        self.assertEqual(preview["mimeType"], "video/mp4")
        self.assertEqual(preview["previewFrameTimeCode"], "00:00:05:00")
        review = [r for r in reqs if r.key == "PATCH /v1/appStoreReviewDetails/rev-1"][0].json()
        self.assertEqual(review["data"]["attributes"], {"contactPhone": "+1 555 555 0199"})
        self.assertNotIn("555 0199", text)

    def test_upload_part_504_is_retried(self):
        self.plan("apple")
        key = "PUT /upload/appScreenshots-new-1/0"
        self.store.queue[key] = [{"status": 504, "body": {"error": "Gateway Timeout"}}]
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.store.keys().count(key), 2)

    def test_upload_part_failing_every_try_stops_with_apples_answer(self):
        self.plan("apple")
        key = "PUT /upload/appScreenshots-new-1/0"
        self.store.queue[key] = [{"status": 504, "body": {"error": "Gateway Timeout"}}] * 4
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 1)
        self.assertEqual(self.store.keys().count(key), 4)
        self.assertIn("answered 504", text)
        self.assertIn("Gateway Timeout", text)
        self.assertIn("the rest weren't tried", text)
        self.assertFalse([k for k in self.store.keys() if k.startswith("DELETE ")])

    def test_reservation_post_is_not_retried(self):
        self.plan("apple")
        self.store.queue["POST /v1/appScreenshots"] = [{"status": 500, "body": {"errors": [{"status": "500"}]}}]
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 1)
        self.assertEqual(self.store.keys().count("POST /v1/appScreenshots"), 1)

    def test_processing_failure_keeps_the_old_pictures(self):
        self.plan("apple")
        self.store.routes["GET /v1/appScreenshots/*"] = {"$delivery": "FAILED"}
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 1)
        self.assertIn("refused a screenshot", text)
        self.assertIn("The old ones are still there", text)
        self.assertFalse([k for k in self.store.keys() if k.startswith("DELETE ")])

    def test_processing_is_polled_until_complete(self):
        self.plan("apple")
        self.store.queue["GET /v1/appScreenshots/appScreenshots-new-1"] = [{"$delivery": "UPLOAD_COMPLETE"},
                                                                           {"$delivery": "UPLOAD_COMPLETE"}]
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.store.keys().count("GET /v1/appScreenshots/appScreenshots-new-1"), 3)

    def test_new_version_action(self):
        self.plan("apple", "--new-version", "1.2.0")
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 0, text)
        made = [r for r in self.store.requests[start:] if r.key == "POST /v1/appStoreVersions"]
        self.assertEqual(len(made), 1)
        body = made[0].json()["data"]
        self.assertEqual(body["attributes"], {"platform": "TV_OS", "versionString": "1.2.0",
                                              "copyright": "2026 Example Studio"})
        self.assertEqual(body["relationships"]["app"]["data"]["id"], "1234567890")

    def test_refuses_when_the_store_changed(self):
        self.plan("apple")
        loc = self.store.routes["GET /v1/appStoreVersions/ver-ios-11/appStoreVersionLocalizations?limit=200"]
        loc["body"]["data"][0]["attributes"]["description"] = "Someone changed this in the console."
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 2)
        self.assertIn("the store changed since you planned: plan again", text)
        self.assertIn("IOS en-US listing differs from when the plan was made", text)
        self.assertEqual(self.store.writes(start), [])

    def test_refuses_when_a_screenshot_set_changed(self):
        self.plan("apple")
        items = self.store.routes["GET /v1/appScreenshotSets/set-67/appScreenshots?limit=200"]["body"]["data"]
        items.append(copy.deepcopy(items[0]))
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 2)
        self.assertIn("IOS en-US APP_IPHONE_67: 3 pictures then, 4 now", text)

    def test_refuses_when_the_listing_changed(self):
        self.plan("apple")
        with open(os.path.join(self.out, "listing.json"), "a", encoding="utf-8") as f:
            f.write("\n")
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 2)
        self.assertIn("changed since you planned", text)
        self.assertEqual(self.store.requests[start:], [])

    def test_refuses_when_a_picture_changed(self):
        self.plan("apple")
        with open(os.path.join(self.out, "apple/IOS/screenshots/en-US/02_APP_IPHONE_61_recipe.png"), "ab") as f:
            f.write(b"changed")
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 2)
        self.assertIn("02_APP_IPHONE_61_recipe.png", text)
        self.assertEqual(self.store.requests[start:], [])

    def test_refuses_when_the_review_contact_changed(self):
        self.plan("apple")
        os.environ["APPLE_REVIEW_PHONE"] = "+1 555 555 0123"
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 2)
        self.assertIn("APPLE_REVIEW_PHONE", text)
        self.assertNotIn("0123", text)
        self.assertEqual(self.store.writes(start), [])

    def test_a_second_plan_after_apply_reads_the_same(self):
        plan1, _ = self.plan("apple")
        code, _ = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 0)
        plan2, _ = self.plan("apple")
        self.assertEqual(plan1["fingerprint"], plan2["fingerprint"])  # (the recorded store doesn't change)

    def test_not_a_plan_exits_3(self):
        with open("plan-apple.json", "w") as f:
            f.write("{}")
        code, text = self.run_push("apply", "plan-apple.json")
        self.assertEqual(code, 3)
        code, text = self.run_push("apply", "missing.json")
        self.assertEqual(code, 3)


class HelperTests(unittest.TestCase):

    def test_masked_phone(self):
        self.assertEqual(push.masked_phone("+1 555 555 0100"), "'…0100'")
        self.assertEqual(push.masked_phone(None), "(none)")

    def test_differs(self):
        self.assertFalse(push.differs("a\r\nb ", "a\nb"))
        self.assertFalse(push.differs(None, ""))
        self.assertTrue(push.differs("a", "b"))
        self.assertFalse(push.differs("a, b,c", "a,b, c", "keywords"))

    def test_explain_difference(self):
        then = {"a": {"sha256": "1"}, "b": {"sha256": "1", "count": 3}, "c": {"sha256": "1"}}
        now = {"a": {"sha256": "2"}, "b": {"sha256": "2", "count": 5}, "d": {"sha256": "1"}}
        self.assertEqual(push.explain_difference(then, now), [
            "a differs from when the plan was made", "b: 3 pictures then, 5 now",
            "c is gone since the plan was made", "d is there now and wasn't when the plan was made"])


@unittest.skipUnless(OPENSSL, "openssl isn't on PATH")
class AppleKeyTests(unittest.TestCase):
    """The .p8 key as a path, its text, or base64; the token verifies with the key's public half."""

    def _token(self, value):
        listing = mock.Mock()
        listing.auth.return_value = dict(push.APPLE_ENV)
        env = {"ASC_KEY_ID": "TESTKEY123", "ASC_ISSUER_ID": "00000000-0000-4000-8000-000000000000",
               "ASC_PRIVATE_KEY": value}
        with mock.patch.dict(os.environ, env):
            return push.AppleClient.from_env(listing).token()

    def _verify(self, token):
        head, claims, sig = token.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)
        header = json.loads(base64.urlsafe_b64decode(pad(head)))
        self.assertEqual(header["alg"], "ES256")
        self.assertEqual(header["kid"], "TESTKEY123")
        body = json.loads(base64.urlsafe_b64decode(pad(claims)))
        self.assertEqual(body["aud"], "appstoreconnect-v1")
        self.assertEqual(body["exp"] - body["iat"], 1200)
        raw = base64.urlsafe_b64decode(pad(sig))
        self.assertEqual(len(raw), 64)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)

        def integer(b):
            b = b.lstrip(b"\0") or b"\0"
            if b[0] & 0x80:
                b = b"\0" + b
            return b"\x02" + bytes([len(b)]) + b
        seq = integer(raw[:32]) + integer(raw[32:])
        der = b"\x30" + bytes([len(seq)]) + seq
        with open(os.path.join(folder, "sig"), "wb") as f:
            f.write(der)
        with open(os.path.join(folder, "data"), "wb") as f:
            f.write((head + "." + claims).encode())
        proc = subprocess.run([OPENSSL, "dgst", "-sha256", "-verify", os.path.join(KEYS["folder"], "ec.pub"),
                               "-signature", os.path.join(folder, "sig"), os.path.join(folder, "data")],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_path(self):
        self._verify(self._token(KEYS["p8"]))

    def test_text(self):
        with open(KEYS["p8"]) as f:
            self._verify(self._token(f.read()))

    def test_text_with_escaped_newlines(self):
        with open(KEYS["p8"]) as f:
            self._verify(self._token(f.read().replace("\n", "\\n")))

    def test_base64(self):
        with open(KEYS["p8"], "rb") as f:
            self._verify(self._token(base64.b64encode(f.read()).decode()))

    def test_not_a_key_exits_3_without_showing_it(self):
        listing = mock.Mock()
        listing.auth.return_value = dict(push.APPLE_ENV)
        env = {"ASC_KEY_ID": "TESTKEY123", "ASC_ISSUER_ID": "x", "ASC_PRIVATE_KEY": "not-a-key-value-xyz"}
        with mock.patch.dict(os.environ, env), self.assertRaises(push.Usage) as raised:
            push.AppleClient.from_env(listing)
        self.assertNotIn("not-a-key-value-xyz", raised.exception.message)
        self.assertIn("ASC_PRIVATE_KEY", raised.exception.message)


if __name__ == "__main__":
    unittest.main()
