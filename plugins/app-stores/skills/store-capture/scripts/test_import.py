"""Tests for import_captures.py: each source's layout read into ``<out>/<locale>/<device>/<screen>.png`` through a
mapping, checked like capture.py's own pictures, and reported in ``capture-report.json``.

Every source folder is built here with invented pictures; the xcresult manifest is the synthetic one in
``evals/files/inapp-answers/``. Nothing runs a real tool.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture  # noqa: E402
import capture_testkit as kit  # noqa: E402
import import_captures as imp  # noqa: E402
from appstores_lib import jsonio  # noqa: E402

ANSWERS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals", "files", "inapp-answers")


class Case(unittest.TestCase):

    def setUp(self):
        self.hooks = kit.Hooks()
        self.tmp = tempfile.mkdtemp(prefix="appstores-import-test-")
        self.src = os.path.join(self.tmp, "src")
        self.out = os.path.join(self.tmp, "captures")
        self.flattened = []
        self.saved_flatten = capture.FLATTEN

        def fake_flatten(src, dest, width, height, colour):
            self.flattened.append((os.path.basename(src), colour))
            kit.write_png(dest, width, height)
        capture.FLATTEN = fake_flatten

    def tearDown(self):
        capture.FLATTEN = self.saved_flatten
        self.hooks.restore()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pic(self, rel, w=20, h=40, **kw):
        return kit.write_png(os.path.join(self.src, rel), w, h, **kw)

    def plan(self, devices):
        return kit.sample_plan([dict({"platform": "ios", "driver": "simctl"}, **d) for d in devices],
                               [{"id": "plan", "steps": []}], locales=["en-US", "de-DE"])

    def run_import(self, kind, mapping=None, plan=None, **kw):
        return imp.import_captures(kind, self.src, self.out, mapping or {}, plan, "capture-plan.json" if plan else None,
                                   **kw)

    def report(self):
        return jsonio.load(os.path.join(self.out, "capture-report.json"))

    def placed(self):
        out = []
        for dirpath, _, files in os.walk(self.out):
            for f in files:
                if f.endswith(".png"):
                    out.append(os.path.relpath(os.path.join(dirpath, f), self.out))
        return sorted(out)


class NameTests(unittest.TestCase):

    def test_snapshot_names_split_at_the_device(self):
        self.assertEqual(imp.split_snapshot_name("iPhone 17 Pro Max-01Plan"), ("iPhone 17 Pro Max", "01Plan"))
        self.assertEqual(imp.split_snapshot_name("iPad Pro 13-inch (M4)-01Plan"), ("iPad Pro 13-inch (M4)", "01Plan"))
        self.assertEqual(imp.split_snapshot_name("iPhone 17 Pro Max-01-plan"), ("iPhone 17 Pro Max", "01-plan"))
        self.assertEqual(imp.split_snapshot_name("Apple TV 4K (3rd generation)-home", ["Apple TV 4K (3rd generation)"]),
                         ("Apple TV 4K (3rd generation)", "home"))

    def test_ids_and_locales(self):
        self.assertEqual(imp.slug("01 Plan View!"), "01-plan-view")
        self.assertEqual(imp.slug("checkout/pay"), "checkout-pay")
        self.assertEqual(imp.normal_locale("de_DE"), "de-DE")
        self.assertEqual(imp.normal_locale("zh-hans"), "zh-Hans")
        self.assertEqual(imp.normal_locale("en-us"), "en-US")


class SnapshotTests(Case):

    def test_snapshot_into_the_layout_checked_against_the_plan(self):
        self.pic("en-US/iPhone 17 Pro Max-01Plan.png")
        self.pic("de-DE/iPhone 17 Pro Max-01Plan.png")
        self.pic("en-US/iPad Pro 13-inch (M4)-01Plan.png", 30, 40)
        mapping = {"devices": {"iPhone 17 Pro Max": "iphone-6.9", "iPad Pro 13-inch (M4)": "ipad-13"},
                   "screens": {"01Plan": "plan"}}
        plan = self.plan([{"id": "iphone-6.9", "width": 20, "height": 40}, {"id": "ipad-13", "width": 30, "height": 40}])
        report, entries, left = self.run_import("fastlane-snapshot", mapping, plan)
        self.assertEqual(left, [])
        self.assertEqual(self.placed(), ["de-DE/iphone-6.9/plan.png", "en-US/ipad-13/plan.png",
                                         "en-US/iphone-6.9/plan.png"])
        shot = [e for e in report["shots"] if e["locale"] == "de-DE"][0]
        self.assertEqual(shot["status"], "taken")
        self.assertEqual(shot["driver"], "import")
        self.assertEqual(shot["source"], {"from": "fastlane-snapshot", "file": "de-DE/iPhone 17 Pro Max-01Plan.png"})
        self.assertEqual((shot["width"], shot["height"]), (20, 40))
        self.assertEqual(len(shot["sha256"]), 64)
        self.assertEqual(shot["statusBar"], "unverified")
        self.assertEqual(report["plan"], "capture-plan.json")
        self.assertFalse([n for n in os.listdir(self.out) if n.startswith(".import-")])

    def test_wrong_size_fails_and_keeps_the_previous_picture(self):
        kit.write_png(os.path.join(self.out, "en-US", "iphone-6.9", "plan.png"), 20, 40)
        self.pic("en-US/iPhone 17 Pro Max-plan.png", 21, 40)
        plan = self.plan([{"id": "iphone-6.9", "width": 20, "height": 40}])
        _, entries, _ = self.run_import("fastlane-snapshot", {"devices": {"iPhone 17 Pro Max": "iphone-6.9"}}, plan)
        (e,) = entries
        self.assertEqual(e["status"], "failed")
        self.assertIn("came out 21x40, not 20x40", e["reason"])
        self.assertEqual(e["kept"], "previous")
        self.assertEqual(self.placed(), ["en-US/iphone-6.9/plan.png"])

    def test_alpha_is_flattened_and_listed(self):
        self.pic("en-US/iPhone 17 Pro Max-plan.png", color_type=6, alpha=255)
        plan = self.plan([{"id": "iphone-6.9", "width": 20, "height": 40, "flatten": "#ffffff"}])
        _, entries, _ = self.run_import("fastlane-snapshot", {"devices": {"iPhone 17 Pro Max": "iphone-6.9"}}, plan)
        self.assertEqual(entries[0]["status"], "taken")
        self.assertEqual(entries[0]["fixes"], ["alpha-flattened"])
        self.assertEqual(self.flattened, [("iPhone 17 Pro Max-plan.png", "#ffffff")])

    def test_without_a_plan_the_picture_keeps_its_size_with_a_warning(self):
        self.pic("en-US/iPhone 17 Pro Max-plan.png")
        _, entries, _ = self.run_import("fastlane-snapshot")
        self.assertEqual((entries[0]["device"], entries[0]["status"]), ("iphone-17-pro-max", "taken"))
        self.assertIn("no promised size", entries[0]["warnings"][0])

    def test_the_existing_report_is_merged(self):
        os.makedirs(self.out)
        jsonio.dump({"version": 1, "plan": "capture-plan.json", "devices": [{"id": "android-phone"}],
                     "shots": [{"locale": "en-US", "device": "android-phone", "screen": "plan", "status": "taken"},
                               {"locale": "en-US", "device": "iphone-6.9", "screen": "plan", "status": "missed"}]},
                    os.path.join(self.out, "capture-report.json"))
        self.pic("en-US/iPhone 17 Pro Max-plan.png")
        self.run_import("fastlane-snapshot", {"devices": {"iPhone 17 Pro Max": "iphone-6.9"}})
        shots = self.report()["shots"]
        self.assertEqual([(s["device"], s["status"]) for s in shots], [("android-phone", "taken"),
                                                                       ("iphone-6.9", "taken")])
        self.assertEqual(self.report()["devices"], [{"id": "android-phone"}])

    def test_only_mapped_screens(self):
        self.pic("en-US/iPhone 17 Pro Max-01Plan.png")
        self.pic("en-US/iPhone 17 Pro Max-99Debug.png")
        _, entries, left = self.run_import("fastlane-snapshot", {"screens": {"01Plan": "plan"}, "onlyMapped": True})
        self.assertEqual([e["screen"] for e in entries], ["plan"])
        self.assertEqual(left[0][1], "not in the mapping's screens")

    def test_dry_run_writes_nothing(self):
        self.pic("en-US/iPhone 17 Pro Max-plan.png")
        report, entries, _ = self.run_import("fastlane-snapshot", dry_run=True)
        self.assertIsNone(report)
        self.assertEqual(entries[0]["status"], "taken")
        self.assertFalse(os.path.exists(self.out))


class OtherSourceTests(Case):

    def test_screengrab_newest_wins_and_the_folder_is_the_device(self):
        self.pic("en-US/images/phoneScreenshots/plan_1794650531000.png")
        self.pic("en-US/images/phoneScreenshots/plan_1794650599000.png", 20, 41)
        self.pic("de-DE/images/tenInchScreenshots/plan_1794650531000.png")
        self.pic("en-US/images/featureGraphic.png")
        mapping = {"devices": {"phoneScreenshots": "android-phone", "tenInchScreenshots": "android-tablet"}}
        _, entries, left = self.run_import("fastlane-screengrab", mapping)
        got = sorted((e["locale"], e["device"], e["screen"], e["height"]) for e in entries)
        self.assertEqual(got, [("de-DE", "android-tablet", "plan", 40), ("en-US", "android-phone", "plan", 41)])
        self.assertEqual(len(left), 1)
        self.assertIn("an older picture", left[0][1])

    def write_exported(self, folder):
        os.makedirs(folder, exist_ok=True)
        shutil.copyfile(os.path.join(ANSWERS, "xcresult-manifest.json"), os.path.join(folder, "manifest.json"))
        for att in jsonio.load(os.path.join(ANSWERS, "xcresult-manifest.json"))[0]["attachments"]:
            kit.write_png(os.path.join(folder, att["exportedFileName"]), 20, 40)

    def test_xcresult_exported_folder(self):
        self.write_exported(self.src)
        mapping = {"locales": {"German": "de-DE"}, "devices": {"appstores-iphone-6.9": "iphone-6.9"}}
        _, entries, _ = self.run_import("xcresult", mapping)
        self.assertEqual(sorted((e["locale"], e["device"], e["screen"]) for e in entries),
                         [("de-DE", "iphone-6.9", "plan"), ("de-DE", "iphone-6.9", "recipe")])

    def test_xcresult_bundle_is_exported_first(self):
        bundle = os.path.join(self.tmp, "Shots.xcresult")
        os.makedirs(bundle)
        self.hooks.runner.on(r"xcresulttool export attachments",
                             then=lambda cmd: self.write_exported(cmd[cmd.index("--output-path") + 1]))
        _, entries, _ = imp.import_captures("xcresult", bundle, self.out,
                                            {"locales": {"German": "de-DE"},
                                             "devices": {"appstores-iphone-6.9": "iphone-6.9"}})
        self.assertEqual(len(entries), 2)
        self.assertTrue(self.hooks.runner.lines[0].startswith("xcrun xcresulttool export attachments --path "))

    def test_maestro_names_are_paths_under_take_screenshot(self):
        self.pic("2026-11-14_100211/onboarding/takeScreenshot/plan.png")
        self.pic("2026-11-14_100211/onboarding/takeScreenshot/checkout/pay.png")
        _, entries, _ = self.run_import("maestro", {"screens": {"checkout/pay": "pay"}}, default_locale="en-US",
                                        default_device="android-phone")
        self.assertEqual(sorted(e["screen"] for e in entries), ["pay", "plan"])

    def test_a_source_that_doesnt_say_needs_a_locale_and_device(self):
        self.pic("plan.png")
        _, entries, left = self.run_import("flutter")
        self.assertEqual(entries, [])
        self.assertIn("doesn't say its locale", left[0][1])
        _, entries, _ = self.run_import("flutter", {"locale": "en-US", "device": "iphone-6.9"})
        self.assertEqual((entries[0]["locale"], entries[0]["device"]), ("en-US", "iphone-6.9"))

    def test_detox_leaves_out_its_own_pictures_and_names_the_device_by_configuration(self):
        self.pic("ios.sim.release.2026-11-14 10:02:11Z/Plan screen shows the week/plan.png")
        self.pic("ios.sim.release.2026-11-14 10:02:11Z/Plan screen shows the week/testDone.png")
        _, entries, _ = self.run_import("detox", {"devices": {"ios.sim.release": "iphone-6.9"}, "locale": "en-US"})
        self.assertEqual([(e["device"], e["screen"]) for e in entries], [("iphone-6.9", "plan")])

    def test_playwright_leaves_out_comparison_files(self):
        self.pic("en-US/desktop/plan.png")
        self.pic("en-US/desktop/plan-diff.png")
        self.pic("en-US/desktop/plan-actual.png")
        _, entries, _ = self.run_import("playwright", {"devices": {"desktop": "web-desktop"}})
        self.assertEqual([(e["locale"], e["device"], e["screen"]) for e in entries],
                         [("en-US", "web-desktop", "plan")])

    def test_folder_layout_and_plan_ids(self):
        self.pic("de-DE/iphone-6.9/plan.png")
        plan = self.plan([{"id": "iphone-6.9", "width": 20, "height": 40}])
        _, entries, _ = self.run_import("folder", plan=plan)
        self.assertEqual([(e["locale"], e["device"], e["screen"], e["status"]) for e in entries],
                         [("de-DE", "iphone-6.9", "plan", "taken")])
        self.assertEqual(entries[0]["warnings"], [])

    def test_a_device_the_plan_doesnt_have_is_a_warning(self):
        self.pic("de-DE/watch/plan.png")
        plan = self.plan([{"id": "iphone-6.9", "width": 20, "height": 40}])
        _, entries, _ = self.run_import("folder", plan=plan)
        self.assertIn("the plan has no device watch", entries[0]["warnings"])


class MainTests(Case):

    def main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = imp.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes(self):
        code, _, err = self.main("--from", "folder", os.path.join(self.tmp, "nope"), "--out", self.out)
        self.assertEqual(code, 3)
        os.makedirs(self.src)
        code, _, err = self.main("--from", "folder", self.src, "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("nothing to import", err)
        self.pic("en-US/iphone-6.9/plan.png")
        code, out, _ = self.main("--from", "folder", self.src, "--out", self.out)
        self.assertEqual(code, 0)
        self.assertIn("taken   en-US/iphone-6.9/plan", out)
        self.assertIn("1 taken, 0 missed, 0 failed, 0 skipped", out)

    def test_plan_gives_out_and_sizes(self):
        self.pic("en-US/iphone-6.9/plan.png", 21, 40)
        plan_path = kit.write_plan(self.tmp, self.plan([{"id": "iphone-6.9", "width": 20, "height": 40}]))
        code, out, _ = self.main("--from", "folder", self.src, "--plan", plan_path)
        self.assertEqual(code, 1)
        self.assertIn("failed", out)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "captures", "capture-report.json")))

    def test_a_bad_mapping_is_usage(self):
        bad = os.path.join(self.tmp, "map.json")
        with open(bad, "w") as f:
            f.write("{nope")
        self.pic("en-US/iphone-6.9/plan.png")
        code, _, err = self.main("--from", "folder", self.src, "--map", bad, "--out", self.out)
        self.assertEqual(code, 3)
        self.assertIn("map.json", err)


if __name__ == "__main__":
    unittest.main()
