"""Tests for check_captures.py: PNG headers against the plan (size, 8-bit RGB, no alpha, sRGB, not interlaced,
missing files, kept pictures) and, with --rules, the stores' accepted sizes.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here reaches a network.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture_testkit as kit  # noqa: E402
import check_captures  # noqa: E402
from appstores_lib import jsonio  # noqa: E402


class CheckCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="check-captures-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def plan(self, devices, screens=None, **extra):
        screens = screens or [{"id": "plan", "steps": [{"launch": {}}]}]
        return kit.write_plan(self.tmp, kit.sample_plan(devices, screens, **extra))

    def picture(self, locale, device, screen, w, h, **kw):
        return kit.write_png(os.path.join(self.tmp, "captures", locale, device, screen + ".png"), w, h, **kw)

    def run_check(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = check_captures.main(list(args))
        return code, out.getvalue()

    def findings(self, path, stores=None):
        found, _ = check_captures.check(path, stores)
        return found


def device(id, platform, w, h, **kw):
    d = {"id": id, "platform": platform, "driver": "simctl", "width": w, "height": h}
    d.update(kw)
    return d


class HeaderTests(CheckCase):
    def test_a_good_capture_passes(self):
        path = self.plan([device("iphone-6.9", "ios", 1320, 2868)])
        self.picture("en-US", "iphone-6.9", "plan", 1320, 2868)
        code, out = self.run_check("--plan", path)
        self.assertEqual(code, 0, out)
        self.assertIn("1 captures checked, 0 errors", out)

    def test_each_problem_is_named(self):
        path = self.plan([device("phone", "ios", 120, 260)],
                         [{"id": s, "steps": []} for s in ("size", "alpha", "trns", "deep", "laced", "p3", "gone")])
        self.picture("en-US", "phone", "size", 121, 260)
        self.picture("en-US", "phone", "alpha", 120, 260, color_type=6)
        self.picture("en-US", "phone", "trns", 120, 260, trns=True)
        self.picture("en-US", "phone", "deep", 120, 260, bit_depth=16)
        self.picture("en-US", "phone", "laced", 120, 260, interlace=1)
        self.picture("en-US", "phone", "p3", 120, 260, icc="Display P3")
        by = {}
        for f in self.findings(path):
            by.setdefault(f["where"].split("/")[-1], []).append(f["message"])
        self.assertIn("121x260, not the 120x260", by["size.png"][0])
        self.assertIn("alpha", by["alpha.png"][0])
        self.assertIn("alpha", by["trns.png"][0])
        self.assertIn("16-bit", by["deep.png"][0])
        self.assertIn("interlaced", by["laced.png"][0])
        self.assertIn("Display P3", by["p3.png"][0])
        self.assertIn("missing", by["gone.png"][0])
        code, _ = self.run_check("--plan", path)
        self.assertEqual(code, 1)

    def test_a_kept_picture_is_a_warning_and_a_missing_one_gives_the_reason(self):
        path = self.plan([device("phone", "ios", 120, 260)], [{"id": "plan", "steps": []}, {"id": "recipe", "steps": []}])
        self.picture("en-US", "phone", "plan", 120, 260)
        jsonio.dump({"version": 1, "shots": [
            {"locale": "en-US", "device": "phone", "screen": "plan", "status": "missed", "reason": "launch timed out",
             "kept": "previous"},
            {"locale": "en-US", "device": "phone", "screen": "recipe", "status": "failed",
             "reason": "came out 100x200, not 120x260", "kept": "none"}]},
            os.path.join(self.tmp, "captures", "capture-report.json"))
        found = self.findings(path)
        warn = [f for f in found if f["severity"] == "warning"]
        self.assertEqual(len(warn), 1)
        self.assertIn("launch timed out", warn[0]["message"])
        err = [f for f in found if f["severity"] == "error"]
        self.assertIn("came out 100x200", err[0]["message"])

    def test_json_output(self):
        path = self.plan([device("phone", "ios", 120, 260)])
        code, out = self.run_check("--plan", path, "--json")
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["errors"], 1)
        self.assertEqual(data["findings"][0]["where"], "en-US/phone/plan.png")

    def test_per_screen_locales_are_respected(self):
        path = self.plan([device("phone", "ios", 120, 260, locales=["en-US", "de-DE"])],
                         [{"id": "plan", "steps": [], "locales": ["de-DE"]}])
        self.picture("de-DE", "phone", "plan", 120, 260)
        self.assertEqual([f for f in self.findings(path) if f["severity"] == "error"], [])

    def test_an_unusable_plan_is_usage(self):
        code, _ = self.run_check("--plan", os.path.join(self.tmp, "nope.json"))
        self.assertEqual(code, 3)
        path = self.plan([device("phone", "ios", 120, 260)])
        code, _ = self.run_check("--plan", path, "--rules", "nostore")
        self.assertEqual(code, 3)


class StoreSizeTests(CheckCase):
    def errors(self, devices, stores):
        path = self.plan(devices)
        for d in devices:
            self.picture("en-US", d["id"], "plan", d["width"], d["height"])
        return [f for f in self.findings(path, stores) if f["severity"] == "error"], self.findings(path, stores)

    def test_apple_sizes_find_their_display_type(self):
        errors, found = self.errors([device("iphone-6.9", "ios", 1320, 2868), device("ipad", "ipados", 2752, 2064),
                                     device("tv", "tvos", 1920, 1080), device("mac", "macos", 2880, 1800)], ["apple"])
        self.assertEqual(errors, [])
        infos = [f["message"] for f in found if f["severity"] == "info"]
        self.assertIn("fills APP_IPHONE_67", infos)
        self.assertIn("fills APP_IPAD_PRO_3GEN_129", infos)
        self.assertIn("fills APP_APPLE_TV", infos)
        self.assertIn("fills APP_DESKTOP", infos)

    def test_a_size_apple_takes_nowhere_is_an_error(self):
        errors, _ = self.errors([device("iphone-11", "ios", 828, 1792), device("tv-portrait", "tvos", 1080, 1920)],
                                ["apple"])
        self.assertEqual(len(errors), 2)
        self.assertIn("no App Store display type for IOS takes 828x1792", errors[0]["message"])

    def test_a_kind_that_disagrees_is_a_warning(self):
        _, found = self.errors([device("tablet", "ios", 1320, 2868, kind="tablet")], ["apple"])
        self.assertTrue(any(f["severity"] == "warning" and "says it's a tablet" in f["message"] for f in found))

    def test_google_ranges_and_aspects(self):
        errors, found = self.errors([device("phone", "android", 1080, 1920, kind="phone"),
                                     device("tall", "android", 1080, 2400, kind="phone"),
                                     device("tab", "android", 2560, 1440, kind="tablet"),
                                     device("tab1610", "android", 2560, 1600, kind="tablet")], ["google"])
        where = sorted(f["where"].split(" ")[1] for f in errors)
        self.assertEqual(where, ["tab1610", "tall"])
        self.assertTrue(any("longer than 2:1" in f["message"] for f in errors))
        self.assertTrue(any("fits Play's tablet7, tablet10" in f["message"] for f in found))

    def test_only_a_stores_platforms_are_checked(self):
        errors, found = self.errors([device("web", "web", 1000, 1000), device("droid", "android", 1080, 1920)],
                                    ["apple"])
        self.assertEqual(errors, [])
        self.assertFalse(any("web" in f["where"] for f in found if f["severity"] != "error" and "device" in f["where"]))


class RequiredSlotTests(unittest.TestCase):
    def test_a_required_iphone_slot_nobody_fills_is_a_note(self):
        tmp = tempfile.mkdtemp(prefix="appstores-check-test-")
        self.addCleanup(shutil.rmtree, tmp, True)
        plan = kit.sample_plan([{"id": "iphone-6.9", "platform": "ios", "kind": "phone", "driver": "simctl",
                                 "width": 1320, "height": 2868}], [{"id": "plan", "steps": []}])
        path = kit.write_plan(tmp, plan)
        kit.write_png(os.path.join(tmp, "captures", "en-US", "iphone-6.9", "plan.png"), 1320, 2868)
        findings, _ = check_captures.check(path, ["apple"])
        notes = [f for f in findings if f["rule"] == "apple.screenshots.required"]
        self.assertEqual(len(notes), 1)
        self.assertIn("APP_IPHONE_61", notes[0]["message"])
        self.assertEqual(notes[0]["severity"], "note")
        self.assertNotIn("IPAD", notes[0]["message"])
        plan["devices"].append({"id": "iphone-6.3", "platform": "ios", "kind": "phone", "driver": "simctl",
                                "width": 1206, "height": 2622})
        path = kit.write_plan(tmp, plan)
        findings, _ = check_captures.check(path, ["apple"])
        self.assertEqual([f for f in findings if f["rule"] == "apple.screenshots.required"], [])


def tearDownModule():
    kit.assert_no_residue()


if __name__ == "__main__":
    unittest.main()
