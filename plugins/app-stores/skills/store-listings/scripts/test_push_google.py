"""Tests for push.py against Google Play's recorded answers (evals/files/push/google-store.json).

The fake store (test_push.FakeStore) keeps each image type as Play would, so a plan's read and an apply's
verification agree. No test reaches a network.
"""

from __future__ import annotations

import base64
import json
import os
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
import test_push  # noqa: E402
from test_push import KEYS, OPENSSL, PushCase  # noqa: E402

APP = "/androidpublisher/v3/applications/com.example.samplerecipes"
EDIT = APP + "/edits/edit-1"
COMMIT = "POST " + EDIT + ":commit?changesInReviewBehavior=ERROR_IF_IN_REVIEW"
DELETE_EDIT = "DELETE " + EDIT


def setUpModule():
    test_push.setUpModule()


def tearDownModule():
    test_push.tearDownModule()


class GooglePlanTests(PushCase):

    fixture = "google-store.json"

    def test_plan_writes_nothing_but_the_edit_it_deletes(self):
        plan, text = self.plan("google")
        writes = [r.key for r in self.store.requests if r.method != "GET"]
        self.assertEqual(writes, ["POST /token", "POST " + APP + "/edits", DELETE_EDIT])
        self.assertEqual(self.store.unknown, [])
        self.assertFalse([k for k in self.store.keys() if ":commit" in k or ":validate" in k])
        self.assertTrue(any("opened a Play edit and deleted it" in n and "nothing was committed" in n
                            for n in plan["notes"]))
        for r in self.store.requests:
            host = urllib.parse.urlsplit(r.url).netloc
            self.assertIn(host, ("oauth2.googleapis.com", "androidpublisher.googleapis.com"))

    def test_plan_matches_the_eval_fixture(self):
        plan, _ = self.plan("google")
        self.assertEqual([(a["kind"], a.get("locale"), a.get("imageType")) for a in plan["actions"]], [
            ("google.listing.update", "de-DE", None),
            ("google.listing.update", "en-US", None),
            ("google.images.replace", "en-US", "phoneScreenshots"),
        ])
        de, en, images = plan["actions"]
        self.assertEqual(en["set"], {"title": "Sample Recipes: Meal Planner",
                                     "shortDescription": "Plan a week of meals in minutes."})
        self.assertEqual(en["summary"], "change title: 'Sample Recipes' → 'Sample Recipes: Meal Planner'; change "
                                        "short description: 'Recipes and meal plans.' → 'Plan a week of meals in "
                                        "minutes.'")
        self.assertEqual(de["summary"], "add the de-DE listing (title 'Sample Recipes: Essensplaner')")
        self.assertEqual(images["summary"], "replace 3 phone screenshots with 4")
        self.assertEqual(len(images["files"]), 4)
        self.assertIn("en-US featureGraphic: 1 picture, as it is", plan["unchanged"])
        self.assertIn("en-US icon: 1 picture, as it is", plan["unchanged"])
        self.assertIn("details: contact details, as they are", plan["unchanged"])
        self.assertEqual(plan["compared"]["en-US phoneScreenshots"]["count"], 3)

    def test_token_request(self):
        self.plan("google")
        token = self.store.requests[0]
        self.assertEqual(token.url, "https://oauth2.googleapis.com/token")
        form = urllib.parse.parse_qs(token.body.decode())
        self.assertEqual(form["grant_type"], ["urn:ietf:params:oauth:grant-type:jwt-bearer"])
        for r in self.store.requests[1:]:
            self.assertEqual(r.headers["Authorization"], "Bearer synthetic-access-token")

    def test_default_language_mismatch_is_a_note(self):
        data = self.listing()
        data["google"]["defaultLanguage"] = "en-GB"
        self.write_listing(data)
        plan, _ = self.plan("google")
        self.assertTrue(any(n.startswith("Play's default language is en-US") for n in plan["notes"]))
        self.assertFalse(self.actions(plan, "google.details.update"))

    def test_details_update(self):
        data = self.listing()
        data["google"]["details"]["contactWebsite"] = "https://example.com/recipes"
        self.write_listing(data)
        plan, _ = self.plan("google")
        self.assertEqual(self.actions(plan, "google.details.update")[0]["set"],
                         {"contactWebsite": "https://example.com/recipes"})

    def test_data_safety_becomes_an_action(self):
        data = self.listing()
        data["google"]["dataSafetyCsv"] = "google/data-safety.csv"
        self.write_listing(data)
        plan, _ = self.plan("google")
        last = plan["actions"][-1]
        self.assertEqual(last["kind"], "google.dataSafety.update")
        self.assertEqual(last["file"], "google/data-safety.csv")

    def test_edit_deleted_even_when_a_read_fails(self):
        self.store.queue["GET " + EDIT + "/listings"] = [{"status": 403, "body": {"error": {
            "code": 403, "message": "The caller does not have permission", "status": "PERMISSION_DENIED"}}}]
        code, text = self.run_push("plan", "google")
        self.assertEqual(code, 1)
        self.assertIn(DELETE_EDIT, self.store.keys())
        self.assertIn("Google Play answered 403 PERMISSION_DENIED", text)
        self.assertIn("Manage store presence", text)

    def test_missing_service_account_exits_3(self):
        del os.environ["GOOGLE_PLAY_SERVICE_ACCOUNT"]
        code, text = self.run_push("plan", "google")
        self.assertEqual(code, 3)
        self.assertIn("GOOGLE_PLAY_SERVICE_ACCOUNT isn't set", text)
        self.assertEqual(self.store.requests, [])

    def test_unreadable_service_account_exits_3_without_showing_it(self):
        os.environ["GOOGLE_PLAY_SERVICE_ACCOUNT"] = "{not json: secret-ish-value}"
        code, text = self.run_push("plan", "google")
        self.assertEqual(code, 3)
        self.assertNotIn("secret-ish-value", text)

    def test_apple_options_refused_for_google(self):
        code, text = self.run_push("plan", "google", "--new-version", "1.2.0")
        self.assertEqual(code, 3)


class GoogleApplyTests(PushCase):

    fixture = "google-store.json"

    def test_apply_commits_with_error_if_in_review(self):
        plan, _ = self.plan("google")
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-google.json")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.store.unknown, [])
        keys = self.store.keys(start)
        self.assertIn(COMMIT, keys)
        self.assertLess(keys.index("POST " + EDIT + ":validate"), keys.index(COMMIT))
        self.assertEqual(keys.count(COMMIT), 1)
        self.assertNotIn(DELETE_EDIT, keys)  # committed: nothing to delete
        self.assertIn("  1 google.listing.update de-DE: done", text)
        self.assertIn("  3 google.images.replace en-US phoneScreenshots: done (4 uploaded)", text)
        self.assertIn("Committing the edit (changesInReviewBehavior=ERROR_IF_IN_REVIEW)...", text)
        # The listing is PUT whole: the fields not changing kept as Play had them.
        put = [r for r in self.store.requests[start:] if r.key == "PUT " + EDIT + "/listings/en-US"][0].json()
        self.assertEqual(put["title"], "Sample Recipes: Meal Planner")
        self.assertEqual(put["fullDescription"], "Plan a week of meals in minutes. Pick recipes, and the shopping "
                                                 "list writes itself.")
        self.assertEqual(put["language"], "en-US")
        # The pictures Play has now are ours, in order.
        self.assertEqual([i["sha256"] for i in self.store.images["en-US/phoneScreenshots"]],
                         plan["actions"][2]["sha256"])
        uploads = [r for r in self.store.requests[start:] if r.key.startswith("POST /upload/")]
        self.assertEqual([u.headers["Content-Type"] for u in uploads], ["image/png"] * 4)

    def test_cancel_review(self):
        self.plan("google")
        code, text = self.run_push("apply", "plan-google.json", "--cancel-review")
        self.assertEqual(code, 0, text)
        self.assertIn("POST " + EDIT + ":commit?changesInReviewBehavior=CANCEL_IN_REVIEW_AND_SUBMIT",
                      self.store.keys())
        self.assertNotIn(COMMIT, self.store.keys())

    def test_changes_already_in_review(self):
        self.plan("google")
        self.store.queue[COMMIT] = [self.store.alternates["commit-in-review"]]
        code, text = self.run_push("apply", "plan-google.json")
        self.assertEqual(code, 1)
        self.assertEqual(self.store.keys().count(COMMIT), 1)  # a commit is never sent twice
        self.assertIn("Google Play answered 400 FAILED_PRECONDITION:", text)
        self.assertIn("CHANGES_ALREADY_IN_REVIEW", text)
        self.assertIn("The edit was not committed; nothing is public.", text)
        self.assertIn("--cancel-review", text)
        self.assertIn("wait for the review to finish", text)

    def test_a_failed_cleanup_never_replaces_the_error(self):
        self.plan("google")
        self.store.queue[COMMIT] = [self.store.alternates["commit-in-review"]]
        self.store.queue[DELETE_EDIT] = [self.store.alternates["service-unavailable"]] * 4
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-google.json")
        self.assertEqual(code, 1)
        self.assertEqual(self.store.keys(start).count(DELETE_EDIT), 4)  # retried, then given up
        warning = text.index("Warning: the edit edit-1 wasn't committed, and deleting it failed too")
        error = text.index("Google Play answered 400 FAILED_PRECONDITION:")
        self.assertLess(warning, error)
        self.assertIn("answered 503", text[warning:error])
        self.assertNotIn("Google Play answered 503", text)
        self.assertNotIn("The edit was deleted", text)

    def test_refuses_when_the_store_changed(self):
        self.plan("google")
        listings = self.store.routes["GET " + EDIT + "/listings"]["body"]["listings"]
        listings[0]["shortDescription"] = "Edited in the console."
        self.store.images["en-US/phoneScreenshots"] += [{"id": "x1", "sha256": "1" * 64},
                                                        {"id": "x2", "sha256": "2" * 64}]
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-google.json")
        self.assertEqual(code, 2)
        self.assertIn("Refused: the store changed since you planned: plan again.", text)
        self.assertIn("en-US listing: shortDescription differs from when the plan was made", text)
        self.assertIn("en-US phoneScreenshots: 3 pictures then, 5 now", text)
        self.assertIn("Nothing was sent. The edit opened to read was deleted.", text)
        writes = [r.key for r in self.store.writes(start)]
        self.assertEqual([w for w in writes if w != "POST /token"], ["POST " + APP + "/edits", DELETE_EDIT])

    def test_refuses_when_the_listing_changed(self):
        self.plan("google")
        with open(os.path.join(self.out, "listing.json"), "a", encoding="utf-8") as f:
            f.write(" ")
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-google.json")
        self.assertEqual(code, 2)
        self.assertIn("listing.json changed since you planned", text)
        self.assertEqual(self.store.requests[start:], [])

    def test_images_sent_again_once_when_play_has_them_wrong(self):
        self.plan("google")
        self.store.duplicate_next_upload = True  # an upload retried after a lost answer, landing twice
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-google.json")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.store.keys(start).count("DELETE " + EDIT + "/listings/en-US/phoneScreenshots"), 2)
        self.assertIn("Play has 5 pictures, not our 4 in order: sending them again", text)
        self.assertEqual(len(self.store.images["en-US/phoneScreenshots"]), 4)

    def test_upload_503_is_retried(self):
        plan, _ = self.plan("google")
        key = "POST /upload" + EDIT + "/listings/en-US/phoneScreenshots?uploadType=media"
        self.store.queue[key] = [self.store.alternates["service-unavailable"]]
        code, text = self.run_push("apply", "plan-google.json")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.store.keys().count(key), 5)  # 4 pictures, the first sent twice

    def test_failure_before_commit_deletes_the_edit(self):
        self.plan("google")
        self.store.queue["PUT " + EDIT + "/listings/de-DE"] = [{"status": 400, "body": {"error": {
            "code": 400, "message": "Invalid value", "status": "INVALID_ARGUMENT"}}}]
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-google.json")
        self.assertEqual(code, 1)
        keys = self.store.keys(start)
        self.assertIn(DELETE_EDIT, keys)
        self.assertNotIn(COMMIT, keys)
        self.assertIn("  1 google.listing.update de-DE: failed", text)
        self.assertIn("The edit was not committed; nothing is public. The edit was deleted.", text)

    def test_data_safety_sent_after_the_commit(self):
        data = self.listing()
        data["google"]["dataSafetyCsv"] = "google/data-safety.csv"
        self.write_listing(data)
        self.plan("google")
        start = len(self.store.requests)
        code, text = self.run_push("apply", "plan-google.json")
        self.assertEqual(code, 0, text)
        keys = self.store.keys(start)
        sent = "POST " + APP + "/dataSafety"
        self.assertLess(keys.index(COMMIT), keys.index(sent))
        body = [r for r in self.store.requests[start:] if r.key == sent][0].json()
        with open(os.path.join(self.out, "google", "data-safety.csv"), encoding="utf-8") as f:
            self.assertEqual(body, {"safetyLabels": f.read()})


@unittest.skipUnless(OPENSSL, "openssl isn't on PATH")
class GoogleKeyTests(unittest.TestCase):
    """The service account's JSON key as a path, its text, or base64; the assertion verifies with its key."""

    def _assertion(self, value):
        listing = mock.Mock()
        listing.auth.return_value = dict(push.GOOGLE_ENV)
        sent = []

        def transport(method, url, headers, body, timeout):
            sent.append(body)
            return push.web.Response(200, {}, b'{"access_token": "synthetic-access-token"}')
        with mock.patch.dict(os.environ, {"GOOGLE_PLAY_SERVICE_ACCOUNT": value}), \
                mock.patch.object(push.web, "TRANSPORT", transport):
            client = push.GoogleClient.from_env(listing, "com.example.samplerecipes")
            self.assertEqual(client.token(), "synthetic-access-token")
        return urllib.parse.parse_qs(sent[0].decode())["assertion"][0]

    def _verify(self, assertion):
        head, claims, sig = assertion.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)
        header = json.loads(base64.urlsafe_b64decode(pad(head)))
        self.assertEqual((header["alg"], header["kid"]), ("RS256", "0123abcd"))
        body = json.loads(base64.urlsafe_b64decode(pad(claims)))
        self.assertEqual(body["aud"], "https://oauth2.googleapis.com/token")
        self.assertEqual(body["scope"], "https://www.googleapis.com/auth/androidpublisher")
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "sig"), "wb") as f:
            f.write(base64.urlsafe_b64decode(pad(sig)))
        with open(os.path.join(folder, "data"), "wb") as f:
            f.write((head + "." + claims).encode())
        proc = subprocess.run([OPENSSL, "dgst", "-sha256", "-verify", os.path.join(KEYS["folder"], "rsa.pub"),
                               "-signature", os.path.join(folder, "sig"), os.path.join(folder, "data")],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_path(self):
        self._verify(self._assertion(KEYS["account"]))

    def test_text(self):
        with open(KEYS["account"]) as f:
            self._verify(self._assertion(f.read()))

    def test_base64(self):
        with open(KEYS["account"], "rb") as f:
            self._verify(self._assertion(base64.b64encode(f.read()).decode()))

    def test_sign_in_refused(self):
        listing = mock.Mock()
        listing.auth.return_value = dict(push.GOOGLE_ENV)

        def transport(method, url, headers, body, timeout):
            return push.web.Response(400, {}, b'{"error": "invalid_grant", "error_description": "Invalid JWT"}')
        with mock.patch.dict(os.environ, {"GOOGLE_PLAY_SERVICE_ACCOUNT": KEYS["account"]}), \
                mock.patch.object(push.web, "TRANSPORT", transport), self.assertRaises(push.StoreError) as raised:
            push.GoogleClient.from_env(listing, "com.example.samplerecipes").token()
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("invalid_grant", raised.exception.report())


if __name__ == "__main__":
    unittest.main()
