"""Tests for capture.py: the plan (schema, checks, per-device and per-screen resolution), the run (prepare,
shots, reset in finally), checking each picture (exact size or failed, alpha flattened and listed in fixes, never
resized), keeping previous pictures for missed shots, the report, --keep-going, --dry-run, the lock and the exit
codes. A fake driver stands in for the real ones; flattening goes through a fake unless Chrome is installed.

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
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture  # noqa: E402
import capture_testkit as kit  # noqa: E402
import drivers  # noqa: E402
from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
from drivers import base  # noqa: E402

try:
    CHROME = chrome.find_chrome()
except chrome.ChromeNotFound:
    CHROME = None


class FakeDriver(base.Driver):
    """Writes a PNG per screen: ``behaviour[(locale, screen)]`` picks its size and shape, or a failure."""

    NAME = "fake"
    PLATFORMS = ()
    STEPS = ("launch", "deepLink", "wait", "settle", "script", "tap")
    FINDERS = ("id", "text")
    behaviour = {}
    events = []
    prepare_error = None

    def prepare(self, device, plan):
        FakeDriver.events.append(("prepare", device["id"]))
        if FakeDriver.prepare_error:
            raise FakeDriver.prepare_error

    def source(self, device):
        return {"deviceType": "Fake Phone"}

    def apply_status_bar(self, device, mode, clock, shot):
        return "verified" if mode == "clean" else "none"

    def step_launch(self, ctx, value):
        FakeDriver.events.append(("launch", ctx.device["id"], ctx.locale, ctx.screen["id"], json.dumps(value)))
        how = FakeDriver.behaviour.get((ctx.locale, ctx.screen["id"])) or {}
        if how.get("raise"):
            raise how["raise"]

    def step_deepLink(self, ctx, value):
        FakeDriver.events.append(("deepLink", value))

    def step_tap(self, ctx, value):
        raise base.StepFailed("step %d: id %r didn't appear" % (ctx.index, value.get("id")))

    def screenshot(self, device, path):
        how = FakeDriver.behaviour.get((self.state.get("locale"), os.path.splitext(os.path.basename(path))[0])) or {}
        if how.get("bug"):
            raise RuntimeError("driver bug")
        size = how.get("size") or (device["width"], device["height"])
        kit.write_png(path, size[0], size[1], **(how.get("png") or {}))

    def reset(self, device):
        FakeDriver.events.append(("reset", device["id"]))
        return []


def install_fake():
    mod = types.ModuleType("drivers.fake")
    mod.DRIVER = FakeDriver
    sys.modules["drivers.fake"] = mod
    drivers.REGISTRY["fake"] = "fake"


def fake_flatten(src, dest, width, height, colour):
    """Stand-in for Chrome: writes an opaque 8-bit RGB picture of the same size."""
    kit.write_png(dest, width, height)


class CaptureCase(unittest.TestCase):
    def setUp(self):
        install_fake()
        FakeDriver.behaviour = {}
        FakeDriver.events = []
        FakeDriver.prepare_error = None
        self.tmp = tempfile.mkdtemp(prefix="capture-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.hooks = kit.Hooks()
        self.addCleanup(self.hooks.restore)
        saved = (capture.FLATTEN, capture.log)
        capture.FLATTEN = fake_flatten
        self.logged = []
        capture.log = self.logged.append
        self.addCleanup(self._restore, saved)

    def _restore(self, saved):
        capture.FLATTEN, capture.log = saved

    def plan(self, devices=None, screens=None, **extra):
        devices = devices or [{"id": "phone", "platform": "ios", "driver": "fake", "width": 120, "height": 260}]
        screens = screens or [{"id": "plan", "steps": [{"launch": {"args": {"ScreenshotScreen": "plan"}}}]},
                              {"id": "recipe", "steps": [{"launch": {}}, {"deepLink": "samplerecipes://recipe/demo"}]}]
        return kit.write_plan(self.tmp, kit.sample_plan(devices, screens, **extra))

    def main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = capture.main(list(args))
        self.stdout = out.getvalue()
        return code

    def report(self):
        return jsonio.load(os.path.join(self.tmp, "captures", "capture-report.json"))

    def shot(self, locale, device, screen):
        for e in self.report()["shots"]:
            if (e["locale"], e["device"], e["screen"]) == (locale, device, screen):
                return e
        self.fail("no shot %s/%s/%s in the report" % (locale, device, screen))

    def capture_path(self, *parts):
        return os.path.join(self.tmp, "captures", *parts)


class PlanTests(CaptureCase):
    def test_a_missing_or_invalid_plan_is_usage(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(self.main("--plan", os.path.join(self.tmp, "none.json")), 3)
            path = kit.write_plan(self.tmp, {"version": 1, "devices": [], "screens": []})
            self.assertEqual(self.main("--plan", path), 3)
        self.assertIn("/devices", stderr.getvalue())

    def test_duplicate_ids_and_unknown_devices_are_named(self):
        plan = kit.sample_plan(
            [{"id": "phone", "platform": "ios", "driver": "fake", "width": 1, "height": 1},
             {"id": "phone", "platform": "ios", "driver": "fake", "width": 1, "height": 1}],
            [{"id": "plan", "steps": [], "devices": ["tablet"], "overrides": {"windows-phone": {"seed": 1}}}])
        problems = capture.check_plan(plan)
        self.assertTrue(any("used twice" in p for p in problems))
        self.assertTrue(any("no device tablet" in p for p in problems))
        self.assertTrue(any("windows-phone" in p for p in problems))

    def test_unknown_filters_are_usage(self):
        path = self.plan()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.main("--plan", path, "--devices", "tablet"), 3)
            self.assertEqual(self.main("--plan", path, "--locales", "fr-FR"), 3)

    def test_device_and_screen_settings_resolve_in_order(self):
        plan = kit.sample_plan(
            [{"id": "phone", "platform": "ipados", "driver": "fake", "width": 1, "height": 1, "appearance": "dark",
              "locales": ["en-US", "de-DE", "ja-JP"], "app": {"app": "build/Tablet.app"}},
             {"id": "droid", "platform": "android", "driver": "fake", "width": 1, "height": 1}],
            [{"id": "plan", "steps": [{"launch": {}}], "clock": "10:10", "locales": ["de-DE", "en-US"],
              "overrides": {"ipados": {"seed": "tablet", "steps": [{"deepLink": "samplerecipes://plan"}]},
                            "phone": {"statusBar": "as-is"}}},
             {"id": "android-only", "steps": [], "platforms": ["android"]}],
            locales=["en-US", "fr-FR"])
        phone = capture.resolve_device(plan, plan["devices"][0])
        self.assertEqual(phone["locales"], ["en-US", "de-DE", "ja-JP"])
        self.assertEqual(phone["appearance"], "dark")
        self.assertEqual(phone["clock"], "09:41")
        self.assertEqual(phone["app"], {"bundleId": "com.example.samplerecipes", "app": "build/Tablet.app"})
        screens = capture.screens_for(plan, phone)
        self.assertEqual([s["id"] for s in screens], ["plan"])
        s = screens[0]
        self.assertEqual((s["clock"], s["seed"], s["statusBar"], s["appearance"]), ("10:10", "tablet", "as-is", "dark"))
        self.assertEqual(s["steps"], [{"deepLink": "samplerecipes://plan"}])
        self.assertEqual(s["locales"], ["en-US", "de-DE"])
        droid = capture.resolve_device(plan, plan["devices"][1])
        self.assertEqual(droid["locales"], ["en-US", "fr-FR"])
        self.assertEqual(droid["app"]["package"], "com.example.samplerecipes")
        self.assertEqual([x["id"] for x in capture.screens_for(plan, droid)], ["plan", "android-only"])
        self.assertEqual(capture.screens_for(plan, droid)[0]["steps"], [{"launch": {}}])

    def test_the_schema_uses_only_what_the_validator_checks(self):
        from appstores_lib import schema
        self.assertEqual(schema.unsupported(capture.load_schema()), [])


class RunTests(CaptureCase):
    def test_taken_shots_land_in_place_with_a_report(self):
        path = self.plan(locales=["en-US", "de-DE"])
        self.assertEqual(self.main("--plan", path), 0)
        for loc in ("en-US", "de-DE"):
            for scr in ("plan", "recipe"):
                meta = png.info(self.capture_path(loc, "phone", scr + ".png"))
                self.assertEqual((meta.width, meta.height, meta.color_type, meta.has_alpha), (120, 260, 2, False))
        e = self.shot("de-DE", "phone", "plan")
        self.assertEqual(e["status"], "taken")
        self.assertEqual(e["path"], "de-DE/phone/plan.png")
        self.assertEqual((e["width"], e["height"]), (120, 260))
        self.assertEqual(e["sha256"], png.sha256(self.capture_path("de-DE", "phone", "plan.png")))
        self.assertEqual(e["statusBar"], "verified")
        self.assertEqual(e["driver"], "fake")
        self.assertEqual(e["source"], {"deviceType": "Fake Phone"})
        self.assertEqual(e["fixes"], [])
        report = self.report()
        self.assertEqual(report["plan"], "capture-plan.json")
        self.assertEqual(report["devices"][0]["id"], "phone")
        leftovers = [n for n in os.listdir(self.capture_path()) if n.startswith(".")]
        self.assertEqual(leftovers, [])
        self.assertEqual(FakeDriver.events[0], ("prepare", "phone"))
        self.assertEqual(FakeDriver.events[-1], ("reset", "phone"))
        launches = [e for e in FakeDriver.events if e[0] == "launch"]
        self.assertEqual([(l[2], l[3]) for l in launches],
                         [("en-US", "plan"), ("en-US", "recipe"), ("de-DE", "plan"), ("de-DE", "recipe")])

    def test_wrong_size_is_failed_never_resized_and_the_previous_picture_stays(self):
        path = self.plan()
        old = kit.write_png(self.capture_path("en-US", "phone", "plan.png"), 120, 260, colour=(1, 2, 3))
        before = png.sha256(old)
        FakeDriver.behaviour[("en-US", "plan")] = {"size": (100, 200)}
        self.assertEqual(self.main("--plan", path, "--keep-going"), 1)
        e = self.shot("en-US", "phone", "plan")
        self.assertEqual(e["status"], "failed")
        self.assertIn("came out 100x200, not 120x260", e["reason"])
        self.assertEqual(e["kept"], "previous")
        self.assertEqual(png.sha256(old), before)
        self.assertEqual(self.shot("en-US", "phone", "recipe")["status"], "taken")

    def test_rotated_is_called_rotated(self):
        path = self.plan()
        FakeDriver.behaviour[("en-US", "plan")] = {"size": (260, 120)}
        self.main("--plan", path)
        self.assertIn("rotated", self.shot("en-US", "phone", "plan")["reason"])

    def test_alpha_is_flattened_and_listed_in_fixes(self):
        path = self.plan()
        FakeDriver.behaviour[("en-US", "plan")] = {"png": {"color_type": 6, "alpha": 0}}
        FakeDriver.behaviour[("en-US", "recipe")] = {"png": {"bit_depth": 16, "icc": "Display P3"}}
        self.assertEqual(self.main("--plan", path), 0)
        self.assertEqual(self.shot("en-US", "phone", "plan")["fixes"], ["alpha-flattened"])
        self.assertEqual(self.shot("en-US", "phone", "recipe")["fixes"], ["16-bit-to-8-bit", "converted-to-srgb"])
        meta = png.info(self.capture_path("en-US", "phone", "plan.png"))
        self.assertEqual((meta.color_type, meta.has_alpha, meta.width, meta.height), (2, False, 120, 260))

    def test_flattening_without_chrome_fails_plainly(self):
        def no_chrome(*a):
            raise chrome.ChromeNotFound("no Chrome here")
        capture.FLATTEN = no_chrome
        path = self.plan()
        FakeDriver.behaviour[("en-US", "plan")] = {"png": {"color_type": 6}}
        self.assertEqual(self.main("--plan", path, "--keep-going"), 1)
        e = self.shot("en-US", "phone", "plan")
        self.assertEqual(e["status"], "failed")
        self.assertIn("alpha-flattened", e["reason"])

    def test_a_missed_shot_keeps_the_previous_picture_and_exits_0(self):
        path = self.plan()
        kit.write_png(self.capture_path("en-US", "phone", "recipe.png"), 120, 260)
        FakeDriver.behaviour[("en-US", "recipe")] = {"raise": base.StepFailed("launch timed out")}
        self.assertEqual(self.main("--plan", path), 0)
        e = self.shot("en-US", "phone", "recipe")
        self.assertEqual((e["status"], e["kept"], e["reason"]), ("missed", "previous", "launch timed out"))
        self.assertTrue(os.path.isfile(self.capture_path("en-US", "phone", "recipe.png")))

    def test_a_missed_shot_with_nothing_kept_exits_1(self):
        path = self.plan()
        FakeDriver.behaviour[("en-US", "recipe")] = {"raise": base.StepFailed("launch timed out")}
        self.assertEqual(self.main("--plan", path), 1)
        self.assertEqual(self.shot("en-US", "phone", "recipe")["kept"], "none")

    def test_without_keep_going_the_run_stops_and_says_so(self):
        devices = [{"id": "phone", "platform": "ios", "driver": "fake", "width": 120, "height": 260},
                   {"id": "tablet", "platform": "ipados", "driver": "fake", "width": 200, "height": 300}]
        path = self.plan(devices)
        FakeDriver.behaviour[("en-US", "plan")] = {"raise": base.StepFailed("boom")}
        self.assertEqual(self.main("--plan", path), 1)
        self.assertIn("not attempted", self.shot("en-US", "phone", "recipe")["reason"])
        self.assertIn("not attempted", self.shot("en-US", "tablet", "plan")["reason"])
        self.assertEqual([e for e in FakeDriver.events if e[0] == "prepare"], [("prepare", "phone")])
        self.assertIn(("reset", "phone"), FakeDriver.events)
        FakeDriver.events = []
        self.assertEqual(self.main("--plan", path, "--keep-going"), 1)
        self.assertEqual(self.shot("en-US", "tablet", "recipe")["status"], "taken")

    def test_reset_is_called_even_when_prepare_or_the_driver_fails(self):
        path = self.plan()
        FakeDriver.prepare_error = base.DriverError("no simulator")
        self.assertEqual(self.main("--plan", path), 1)
        self.assertEqual(FakeDriver.events, [("prepare", "phone"), ("reset", "phone")])
        self.assertIn("couldn't prepare phone: no simulator", self.shot("en-US", "phone", "plan")["reason"])
        FakeDriver.prepare_error = None
        FakeDriver.events = []
        FakeDriver.behaviour[("en-US", "plan")] = {"bug": True}
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.main("--plan", path, "--keep-going"), 1)
        self.assertEqual(FakeDriver.events[-1], ("reset", "phone"))
        self.assertIn("driver bug", self.shot("en-US", "phone", "plan")["reason"])

    def test_a_missing_tool_exits_3_after_reporting(self):
        path = self.plan()
        FakeDriver.prepare_error = base.ToolMissing("xcrun isn't installed")
        self.assertEqual(self.main("--plan", path), 3)
        self.assertIn("xcrun", self.shot("en-US", "phone", "plan")["reason"])

    def test_a_step_the_driver_cannot_do_is_skipped(self):
        path = self.plan(screens=[{"id": "plan", "steps": [{"launch": {}}, {"swipe": {"direction": "up"}}]}])
        self.assertEqual(self.main("--plan", path), 1)
        e = self.shot("en-US", "phone", "plan")
        self.assertEqual(e["status"], "skipped")
        self.assertIn("can't do swipe", e["reason"])
        self.assertEqual([x for x in FakeDriver.events if x[0] == "launch"], [])

    def test_a_failed_step_is_missed(self):
        path = self.plan(screens=[{"id": "plan", "steps": [{"tap": {"id": "search"}}]}])
        self.main("--plan", path)
        e = self.shot("en-US", "phone", "plan")
        self.assertEqual(e["status"], "missed")
        self.assertIn("search", e["reason"])

    def test_an_unknown_driver_is_skipped(self):
        path = self.plan([{"id": "phone", "platform": "ios", "driver": "teleport", "width": 1, "height": 1}])
        self.assertEqual(self.main("--plan", path), 1)
        self.assertIn("no 'teleport' driver", self.shot("en-US", "phone", "plan")["reason"])

    def test_a_partial_run_keeps_the_other_entries(self):
        devices = [{"id": "phone", "platform": "ios", "driver": "fake", "width": 120, "height": 260},
                   {"id": "tablet", "platform": "ipados", "driver": "fake", "width": 200, "height": 300}]
        path = self.plan(devices)
        self.assertEqual(self.main("--plan", path), 0)
        self.assertEqual(self.main("--plan", path, "--devices", "tablet", "--screens", "plan"), 0)
        shots = self.report()["shots"]
        self.assertEqual(len(shots), 4)
        self.assertEqual(sorted((e["device"], e["screen"]) for e in shots),
                         [("phone", "plan"), ("phone", "recipe"), ("tablet", "plan"), ("tablet", "recipe")])

    def test_another_capture_holding_the_folder_is_refused(self):
        path = self.plan()
        os.makedirs(self.capture_path())
        with open(self.capture_path(capture.LOCK_NAME), "w") as f:
            f.write(str(os.getppid()))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.main("--plan", path), 2)
        self.assertEqual(FakeDriver.events, [])
        with open(self.capture_path(capture.LOCK_NAME), "w") as f:
            f.write("999999999")  # gone: a stale lock is taken over
        self.assertEqual(self.main("--plan", path), 0)
        self.assertFalse(os.path.exists(self.capture_path(capture.LOCK_NAME)))


class DryRunTests(CaptureCase):
    def test_dry_run_runs_nothing_and_writes_nothing(self):
        devices = [{"id": "iphone-6.9", "platform": "ios", "driver": "simctl", "width": 1320, "height": 2868,
                    "target": {"deviceType": "iPhone 17 Pro Max"}},
                   {"id": "android-phone", "platform": "android", "driver": "adb", "width": 1080, "height": 1920,
                    "target": {"serial": "emulator-5554"}}]
        screens = [{"id": "plan", "steps": [{"launch": {"args": {"ScreenshotScreen": "plan"}}}, {"settle": {}}]},
                   {"id": "search", "steps": [{"launch": {}}, {"tap": {"id": "search"}}], "devices": ["android-phone"]}]
        path = self.plan(devices, screens)
        self.assertEqual(self.main("--plan", path, "--dry-run"), 0)
        self.assertEqual(self.hooks.runner.calls, [])
        self.assertEqual(self.hooks.spawned, [])
        self.assertFalse(os.path.exists(self.capture_path()))
        out = self.stdout
        self.assertIn("$ xcrun simctl create appstores-iphone-6.9 'iPhone 17 Pro Max' latest", out)
        self.assertIn("xcrun simctl launch --terminate-running-process", out)
        self.assertIn("-ScreenshotSeed demo -ScreenshotScreen plan", out)
        self.assertIn("status_bar", out)
        self.assertIn("adb -s emulator-5554 shell 'input tap 540 960'", out)
        self.assertIn("-> would save en-US/android-phone/search.png", out)
        self.assertIn("  reset", out)
        self.assertFalse(base.DRY_RUN)


@unittest.skipUnless(CHROME, "Chrome isn't installed")
class RealFlattenTests(CaptureCase):
    def test_chrome_flattens_onto_the_colour_and_keeps_opaque_pixels(self):
        capture.FLATTEN = capture.flatten_with_chrome
        src = kit.write_png(os.path.join(self.tmp, "in.png"), 30, 20, color_type=6, colour=(10, 200, 30), alpha=255)
        clear = kit.write_png(os.path.join(self.tmp, "clear.png"), 30, 20, color_type=6, alpha=0)
        try:
            status, fixes, reason = capture.verify_picture(src, os.path.join(self.tmp, "out.png"), 30, 20, "#000000")
            self.assertEqual((status, fixes), ("taken", ["alpha-flattened"]), reason)
            w, h, rgb = png.decode_rgb(os.path.join(self.tmp, "out.png"))
            self.assertEqual(rgb[:3], bytes([10, 200, 30]))
            status, fixes, reason = capture.verify_picture(clear, os.path.join(self.tmp, "out2.png"), 30, 20,
                                                           "#FF0000")
            w, h, rgb = png.decode_rgb(os.path.join(self.tmp, "out2.png"))
            self.assertEqual(rgb[:3], bytes([255, 0, 0]))
            self.assertEqual(png.info(os.path.join(self.tmp, "out2.png")).color_type, 2)
        finally:
            capture.close_browser()


if __name__ == "__main__":
    unittest.main()
