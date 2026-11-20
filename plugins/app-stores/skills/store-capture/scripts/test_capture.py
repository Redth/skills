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
    STEPS = ("launch", "deepLink", "wait", "settle", "script", "tap", "appFile", "posture")
    FINDERS = ("id", "text")
    behaviour = {}
    events = []
    prepare_error = None
    on_screen = None     # what find sees (None: everything)
    devices = []

    def prepare(self, device, plan):
        FakeDriver.events.append(("prepare", device["id"]))
        FakeDriver.devices.append(device)
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

    def apply_posture(self, device, posture, shot):
        FakeDriver.events.append(("posture", device["id"], posture))

    def step_appFile(self, ctx, value):
        FakeDriver.events.append(("appFile", json.dumps(value, sort_keys=True)))

    def step_script(self, ctx, value):
        FakeDriver.events.append(("script", json.dumps(value, sort_keys=True)))

    def find(self, ctx, query):
        if FakeDriver.on_screen is None or query[1] in FakeDriver.on_screen:
            return base.Element(id=str(query[1]))
        return None

    def inspect_tree(self, ctx):
        return "<hierarchy><node resource-id='plan-title'/></hierarchy>"

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
        FakeDriver.on_screen = None
        FakeDriver.devices = []
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
        # See-through pixels are worth a look; an opaque alpha channel isn't.
        self.assertTrue(any("see-through" in w for w in self.shot("en-US", "phone", "plan")["warnings"]))
        self.assertEqual(self.shot("en-US", "phone", "recipe")["fixes"], ["16-bit-to-8-bit", "converted-to-srgb"])
        meta = png.info(self.capture_path("en-US", "phone", "plan.png"))
        self.assertEqual((meta.color_type, meta.has_alpha, meta.width, meta.height), (2, False, 120, 260))

    def test_an_opaque_alpha_channel_is_quiet_and_noted_once(self):
        path = self.plan()
        for screen in ("plan", "recipe"):
            FakeDriver.behaviour[("en-US", screen)] = {"png": {"color_type": 6, "alpha": 255}}
        self.assertEqual(self.main("--plan", path), 0)
        for screen in ("plan", "recipe"):
            e = self.shot("en-US", "phone", screen)
            self.assertEqual(e["fixes"], ["alpha-flattened"])
            self.assertEqual(e["warnings"], [])
        self.assertFalse(any("alpha-flattened" in line for line in self.logged if line.startswith("taken")))
        (note,) = self.report()["notes"]
        self.assertIn("2 pictures came with an alpha channel whose every pixel is opaque", note)
        self.assertIn("note: 2 pictures", self.stdout)

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


class StagingTests(CaptureCase):
    """The plan's staging: agreed with the user, confirmed on one screen, then put into every screen."""

    def staged_plan(self, staging=None, screens=None, **extra):
        staging = {"account": {"kind": "bypass", "how": "a debug build's sign-in bypass"},
                   "seed": {"kind": "command", "run": "./seed-demo.sh"},
                   "launch": {"args": {"UITestMode": "1"}, "env": {"UITestMode": "1"}},
                   "skip": ["onboarding", {"what": "rating prompt", "how": "UITestMode"}],
                   "permissions": {"ios": ["photos"], "android": ["android.permission.POST_NOTIFICATIONS"]},
                   "confirmed": {"screen": "plan", "device": "phone", "on": "2026-11-14"}} if staging is None else staging
        screens = screens or [
            {"id": "plan", "state": "this week's plan with five invented recipes", "verify": {"id": "plan-title"},
             "steps": [{"launch": {"args": {"ScreenshotScreen": "plan"}}}]},
            {"id": "recipe", "state": "one recipe open", "steps": [{"launch": {}}, {"deepLink": "samplerecipes://r/1"}]}]
        return self.plan(screens=screens, staging=staging, **extra)

    def launches(self):
        return [json.loads(e[4]) for e in FakeDriver.events if e[0] == "launch"]

    def test_staging_goes_into_every_screen(self):
        path = self.staged_plan()
        capture.write_staging(path)
        self.assertEqual(self.main("--plan", path), 0)
        scripts = [e for e in FakeDriver.events if e[0] == "script"]
        self.assertEqual(len(scripts), 2)
        self.assertIn("./seed-demo.sh", scripts[0][1])
        # The seed runs before the screen's own steps.
        self.assertLess(FakeDriver.events.index(scripts[0]), [i for i, e in enumerate(FakeDriver.events)
                                                              if e[0] == "launch"][0])
        plan_launch, recipe_launch = self.launches()
        self.assertEqual(plan_launch["args"], {"UITestMode": "1", "ScreenshotScreen": "plan"})
        self.assertEqual(recipe_launch, {"args": {"UITestMode": "1"}, "env": {"UITestMode": "1"}})
        self.assertEqual(FakeDriver.devices[0]["permissions"], ["photos"])
        e = self.shot("en-US", "phone", "plan")
        self.assertEqual((e["state"], e["stateCheck"]), ("this week's plan with five invented recipes", "passed"))
        self.assertNotIn("stateCheck", self.shot("en-US", "phone", "recipe"))

    def test_a_file_seed_is_an_app_file_step_and_once_means_the_first_screen(self):
        path = self.staged_plan(staging={"seed": {"kind": "file", "file": "seed/app.db", "when": "once",
                                                  "into": {"ios": "Library/Caches/app.db", "android": "files/app.db"}},
                                         "confirmed": {"screen": "plan"}})
        self.assertEqual(self.main("--plan", path), 0)
        files = [e for e in FakeDriver.events if e[0] == "appFile"]
        self.assertEqual(len(files), 1)
        self.assertIn("Library/Caches/app.db", files[0][1])

    def test_a_screen_can_leave_the_staging_out(self):
        screens = [{"id": "onboarding", "staging": False, "steps": [{"launch": {"clean": True}}]},
                   {"id": "plan", "steps": [{"launch": {}}]}]
        path = self.staged_plan(screens=screens, staging={"seed": {"kind": "command", "run": "./seed.sh"},
                                                          "launch": {"args": {"UITestMode": "1"}},
                                                          "confirmed": {"screen": "plan"}})
        self.assertEqual(self.main("--plan", path), 0)
        self.assertEqual(self.launches(), [{"clean": True}, {"args": {"UITestMode": "1"}}])
        self.assertEqual(len([e for e in FakeDriver.events if e[0] == "script"]), 1)

    def test_until_confirmed_only_one_screen_is_captured(self):
        staging = {"seed": {"kind": "command", "run": "./seed.sh"}}
        path = self.staged_plan(staging=staging)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(self.main("--plan", path), 3)
        self.assertIn("staging isn't confirmed with the user yet", stderr.getvalue())
        self.assertIn("--screens plan", stderr.getvalue())
        self.assertEqual(FakeDriver.events, [])
        # One screen, to show the user, is fine; so is a dry run.
        self.assertEqual(self.main("--plan", path, "--screens", "plan"), 0)
        self.assertEqual(self.main("--plan", path, "--dry-run"), 0)

    def test_a_demo_account_is_named_by_variables_checked_before_the_run_and_never_logged(self):
        staging = {"account": {"kind": "demo", "env": ["SR_DEMO_USER", "SR_DEMO_PASSWORD"]},
                   "launch": {"env": {"DemoUser": "${SR_DEMO_USER}", "DemoPassword": "${SR_DEMO_PASSWORD}"}},
                   "confirmed": {"screen": "plan"}}
        path = self.staged_plan(staging=staging)
        for k in ("SR_DEMO_USER", "SR_DEMO_PASSWORD"):
            os.environ.pop(k, None)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("SR_DEMO_USER", "SR_DEMO_PASSWORD")])
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(self.main("--plan", path), 3)
        self.assertIn("SR_DEMO_USER, SR_DEMO_PASSWORD set in the environment", stderr.getvalue())
        os.environ["SR_DEMO_USER"] = "demo@example.com"
        os.environ["SR_DEMO_PASSWORD"] = "correct-horse-battery"
        FakeDriver.behaviour[("en-US", "recipe")] = {"raise": base.StepFailed(
            "launch failed with DemoPassword=correct-horse-battery")}
        self.assertEqual(self.main("--plan", path, "--keep-going"), 1)
        self.assertEqual(self.launches()[0]["env"]["DemoPassword"], "correct-horse-battery")
        text = json.dumps(self.report()) + "\n".join(self.logged) + "\n".join(self.hooks.log)
        self.assertNotIn("correct-horse-battery", text)
        self.assertIn("***", self.shot("en-US", "phone", "recipe")["reason"])
        self.assertEqual(base.SECRETS, [])

    def test_a_demo_account_written_into_the_plan_is_refused_or_warned(self):
        plan = kit.sample_plan([{"id": "phone", "platform": "ios", "driver": "fake", "width": 1, "height": 1}],
                               [{"id": "plan", "steps": [{"launch": {"env": {"Password": "${NOT_NAMED}"}}}]}],
                               staging={"account": {"kind": "demo"}})
        problems = capture.check_plan(plan)
        self.assertTrue(any("named by its environment variables" in p for p in problems))
        self.assertTrue(any("${NOT_NAMED} isn't one of staging.account.env's" in p for p in problems))
        plan["staging"] = {"account": {"kind": "bypass"}}
        plan["screens"][0]["steps"][0]["launch"]["env"]["Password"] = "hunter2hunter2"
        self.assertTrue(any("looks like a password" in w for w in capture.credential_warnings(plan)))

    def test_verify_catches_a_wrong_state(self):
        path = self.staged_plan()
        FakeDriver.on_screen = ["something-else"]
        self.assertEqual(self.main("--plan", path, "--keep-going"), 1)
        e = self.shot("en-US", "phone", "plan")
        self.assertEqual((e["status"], e["stateCheck"]), ("missed", "failed"))
        self.assertIn("wrong state: id 'plan-title' wasn't on screen", e["reason"])
        self.assertIn("this week's plan with five invented recipes", e["reason"])
        self.assertEqual(self.shot("en-US", "phone", "recipe")["status"], "taken")

    def test_verify_on_a_driver_that_cant_see_is_unchecked_not_passed(self):
        path = self.staged_plan()
        saved = FakeDriver.FINDERS
        FakeDriver.FINDERS = ()
        self.addCleanup(setattr, FakeDriver, "FINDERS", saved)
        self.assertEqual(self.main("--plan", path), 0)
        e = self.shot("en-US", "phone", "plan")
        self.assertEqual(e["stateCheck"], "unchecked")
        self.assertTrue(any("verify not checked" in w for w in e["warnings"]))

    def test_staging_md_is_written_from_the_plan_and_a_stale_one_is_warned_about(self):
        path = self.staged_plan()
        self.assertEqual(self.main("--plan", path, "--write-staging"), 0)
        with open(os.path.join(self.tmp, "staging.md"), encoding="utf-8") as f:
            text = f.read()
        for words in ("**Confirmed** on `plan` (phone), 2026-11-14", "A debug sign-in bypass", "`./seed-demo.sh`",
                      "before every screen", "rating prompt: UITestMode", "ios: photos",
                      "| `plan` | this week's plan with five invented recipes | launch {args: ",
                      "id `plan-title`", "(nothing: look at it)"):
            self.assertIn(words, text)
        self.assertEqual(self.main("--plan", path), 0)
        self.assertFalse(any("out of date" in l for l in self.logged))
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
        plan["screens"][1]["state"] = "the recipe, scrolled to its steps"
        kit.write_plan(self.tmp, plan)
        self.assertEqual(self.main("--plan", path), 0)
        self.assertTrue(any("staging.md is out of date: capture.py --write-staging" in l for l in self.logged))

    def test_a_plan_without_staging_is_warned_about(self):
        path = self.plan()
        self.assertEqual(self.main("--plan", path), 0)
        self.assertTrue(any("no staging section" in l for l in self.logged))

    def test_the_current_set_is_listed_to_start_the_screen_list_from(self):
        path = self.plan()
        kit.write_png(os.path.join(self.tmp, "existing", "apple", "screenshots", "en-US", "APP_IPHONE_67", "1.png"),
                      1320, 2868)
        kit.write_png(os.path.join(self.tmp, "existing", "google", "screenshots", "en-US", "phone", "1.png"), 1080, 1920)
        jsonio.dump({"shots": [{"id": "plan", "capture": "plan"}, {"id": "shop", "capture": "shopping"}]},
                    os.path.join(self.tmp, "store-screenshots.json"))
        self.assertEqual(self.main("--plan", path, "--current"), 0)
        for words in ("existing/apple/screenshots", "en-US/APP_IPHONE_67/1.png  1320x2868",
                      "existing/google/screenshots", "store-screenshots.json", "2. shop  capture: shopping"):
            self.assertIn(words, self.stdout)
        folder = os.path.join(self.tmp, "marketing", "now")
        kit.write_png(os.path.join(folder, "home.png"), 1206, 2622)
        self.assertEqual(self.main("--plan", path, "--current", folder), 0)
        self.assertIn("home.png  1206x2622", self.stdout)
        self.assertNotIn("existing/apple", self.stdout)

    def test_design_current_json_is_listed_by_group_with_what_each_shot_shows(self):
        # Friction #34: every shot printed "1. ?  capture: overview", iPad and iPhone interleaved.
        path = self.plan()
        os.makedirs(os.path.join(self.tmp, "design"))
        jsonio.dump({"version": 1, "source": "existing", "shots": [
            {"file": "apple/screenshots/en-US/ipad/01.png", "group": "apple/en-US/ipad", "order": 1,
             "screen": "the plan, five recipes", "capture": "plan", "caption": "Plan your week"},
            {"file": "apple/screenshots/en-US/iphone/02.png", "group": "apple/en-US/iphone", "order": 2,
             "screen": "a recipe's steps", "capture": None, "caption": "Cook along"},
            {"file": "apple/screenshots/en-US/iphone/01.png", "group": "apple/en-US/iphone", "order": 1,
             "screen": "the plan, five recipes", "capture": "plan", "caption": "Plan your week", "verdict": "keep"}]},
            os.path.join(self.tmp, "design", "current.json"))
        self.assertEqual(self.main("--plan", path, "--current"), 0)
        self.assertNotIn("?", self.stdout)
        iphone = self.stdout.index("design/current.json: apple/en-US/iphone")
        ipad = self.stdout.index("design/current.json: apple/en-US/ipad")
        self.assertLess(iphone, ipad, "phones first")
        first = self.stdout.index("1. apple/screenshots/en-US/iphone/01.png", iphone)
        second = self.stdout.index("2. apple/screenshots/en-US/iphone/02.png", iphone)
        self.assertLess(first, second)
        self.assertIn("shows: the plan, five recipes; capture: plan; caption: Plan your week; verdict: keep",
                      self.stdout)
        self.assertIn("capture: (not mapped yet)", self.stdout)

    def test_inspect_saves_each_screens_tree(self):
        path = self.plan()
        self.assertEqual(self.main("--plan", path, "--inspect"), 0)
        tree = os.path.join(self.tmp, "captures", ".inspect", "en-US", "phone", "plan.txt")
        with open(tree, encoding="utf-8") as f:
            self.assertIn("plan-title", f.read())
        self.assertTrue(any(l.startswith("tree    .inspect") for l in self.logged))


class StepVariantTests(CaptureCase):
    """Per-layout and per-device steps that follow the base steps (friction #53, #54, #61)."""

    def variant_plan(self):
        devices = [
            {"id": "phone", "platform": "ios", "driver": "fake", "width": 120, "height": 260},
            {"id": "duo-inner", "platform": "ios", "driver": "fake", "width": 260, "height": 180, "layout": "wide",
             "posture": "open"},
            {"id": "fold-inner", "platform": "android", "driver": "fake", "width": 260, "height": 180,
             "layout": "wide", "posture": "open"},
            {"id": "duo-outer", "platform": "ios", "driver": "fake", "width": 140, "height": 200, "posture": "folded"}]
        screens = [
            {"id": "overview", "steps": [{"launch": {}}, {"wait": {"id": "overview"}}]},
            {"id": "servings", "steps": [
                {"launch": {}},
                {"tap": {"xpath": "//XCUIElementTypeNavigationBar/XCUIElementTypeButton[not(@name)]"}, "name": "menu"},
                {"tap": {"text": "Scale servings"}},
                {"type": {"id": "servings-field", "text": "12"}},
                {"hideKeyboard": True, "name": "keyboard"},
                {"wait": {"ms": 500}}],
             "overrides": {
                 "android": {"stepsPatch": [{"replace": "menu", "with": [{"tap": {"label": "Open navigation drawer"}}]}]},
                 "duo-outer": {"stepsPatch": [{"replace": "menu", "with": [
                     {"tap": {"xpath": "//XCUIElementTypeButton[not(@name)]"}, "name": "menu"}]}]}}},
            {"id": "history", "steps": [{"launch": {}}, {"tap": {"id": "tab-history"}, "name": "open-tab"},
                                         {"wait": {"id": "history-list"}}],
             "overrides": {"wide": {"stepsPatch": [{"remove": "open-tab"}]},
                           "duo-inner": {"omit": "the open Duo shows the history beside the plan"}}}]
        return kit.sample_plan(devices, screens)

    def steps_of(self, plan, device_id, screen_id):
        device = capture.resolve_device(plan, [d for d in plan["devices"] if d["id"] == device_id][0])
        for s in capture.screens_for(plan, device):
            if s["id"] == screen_id:
                return [base.describe_step(st) for st in s["steps"]]
        return None

    def test_a_fix_to_the_base_steps_reaches_every_device_that_patches_them(self):
        plan = self.variant_plan()
        self.assertEqual(capture.check_plan(plan), [])
        # The base fix (the keyboard's hideKeyboard) is in every device's steps, patched or not.
        for device in ("phone", "duo-outer", "fold-inner"):
            self.assertIn("hideKeyboard", self.steps_of(plan, device, "servings"), device)
        self.assertEqual(self.steps_of(plan, "fold-inner", "servings")[1], "tap {label: Open navigation drawer}")
        self.assertEqual(self.steps_of(plan, "duo-outer", "servings")[1],
                         "tap {xpath: //XCUIElementTypeButton[not(@name)]}")
        # A second base fix, added after the overrides were written, still reaches them.
        plan["screens"][1]["steps"].insert(-1, {"settle": True})
        for device in ("phone", "duo-outer", "fold-inner"):
            self.assertIn("settle", self.steps_of(plan, device, "servings"), device)
        # A whole copy (steps) is what doesn't follow: that's why stepsPatch exists.
        plan["screens"][1]["overrides"]["duo-outer"] = {"steps": [{"launch": {}}]}
        self.assertNotIn("settle", self.steps_of(plan, "duo-outer", "servings"))

    def test_a_layout_override_applies_to_every_device_with_that_layout(self):
        plan = self.variant_plan()
        self.assertEqual(self.steps_of(plan, "fold-inner", "history"), ["launch", "wait {id: history-list}"])
        self.assertEqual(self.steps_of(plan, "phone", "history"),
                         ["launch", "tap {id: tab-history}", "wait {id: history-list}"])
        # duo-inner has the wide layout too, but its own override leaves the screen out.
        self.assertIsNone(self.steps_of(plan, "duo-inner", "history"))

    def test_a_patch_naming_a_step_that_is_gone_is_caught_when_the_plan_loads(self):
        plan = self.variant_plan()
        plan["screens"][2]["steps"][1]["name"] = "history-tab"
        problems = capture.check_plan(plan)
        self.assertEqual(problems, ["/screens/2/overrides/wide/stepsPatch/0: no step named open-tab (named here: "
                                    "history-tab)"])
        plan["screens"][2]["steps"][2]["name"] = "history-tab"
        self.assertTrue(any("the step name history-tab is used twice" in p for p in capture.check_plan(plan)))

    def test_an_override_key_may_be_a_layout(self):
        plan = self.variant_plan()
        plan["screens"][0]["overrides"] = {"tall": {"seed": "x"}}
        self.assertTrue(any("tall is neither a device id, a device's platform nor a device's layout" in p
                            for p in capture.check_plan(plan)))

    def test_every_patch_kind(self):
        steps = [{"launch": {}, "name": "a"}, {"wait": 1, "name": "b"}, {"back": True, "name": "c"}]
        out = capture.patch_steps(steps, [{"prepend": [{"settle": True}]}, {"append": [{"wait": 2}]},
                                          {"remove": "b"}, {"before": "c", "insert": [{"wait": 3}]},
                                          {"after": "a", "insert": [{"wait": 4}]},
                                          {"replace": 1, "with": [{"settle": False}]}])
        self.assertEqual([base.describe_step(s) for s in out],
                         ["settle False", "launch", "wait 4", "wait 3", "back", "wait 2"])
        self.assertEqual(out[0], {"settle": False})
        self.assertEqual(steps[1], {"wait": 1, "name": "b"}, "the base steps are never changed in place")
        with self.assertRaises(capture.PatchError):
            capture.patch_steps(steps, [{"remove": 9}])

    def test_an_omitted_screen_is_left_out_and_said_so_and_postures_are_shown(self):
        plan = self.variant_plan()
        # What the fake driver can do: it taps nothing.
        plan["screens"][1]["steps"] = [{"launch": {}, "name": "menu"}]
        plan["screens"][1]["overrides"]["android"]["stepsPatch"][0]["with"] = [{"wait": {"text": "Menu"}}]
        del plan["screens"][1]["overrides"]["duo-outer"]
        plan["screens"][2]["steps"][1] = {"wait": {"id": "tab-history"}, "name": "open-tab"}
        path = kit.write_plan(self.tmp, plan)
        self.assertEqual(self.main("--plan", path, "--keep-going"), 0)
        shots = set((e["device"], e["screen"]) for e in self.report()["shots"])
        self.assertNotIn(("duo-inner", "history"), shots)
        self.assertIn(("fold-inner", "history"), shots)
        self.assertTrue(any("history isn't captured on duo-inner: the open Duo shows the history beside the plan"
                            in l for l in self.logged))
        self.assertTrue(any(l.startswith("device duo-outer (fake, ios, 140x200, folded)") for l in self.logged))
        self.assertIn(("posture", "duo-outer", "folded"), FakeDriver.events)
        self.assertIn(("posture", "fold-inner", "open"), FakeDriver.events)
        self.assertFalse([e for e in FakeDriver.events if e[:2] == ("posture", "phone")])
        self.assertEqual(self.main("--plan", path, "--write-staging"), 0)
        with open(os.path.join(self.tmp, "staging.md"), encoding="utf-8") as f:
            text = f.read()
        for words in ("- `duo-inner`: open, the wide layout", "- `duo-outer`: folded",
                      "on wide: without step open-tab", "not on duo-inner (the open Duo shows",
                      "on android: step menu as wait {text: Menu}"):
            self.assertIn(words, text)


class SettleTests(unittest.TestCase):
    def test_settle_can_leave_an_animated_region_out(self):
        tmp = tempfile.mkdtemp(prefix="appstores-settle-test-")
        self.addCleanup(shutil.rmtree, tmp, True)
        a = kit.write_png(os.path.join(tmp, "a.png"), 40, 40)
        b = os.path.join(tmp, "b.png")
        # b: the same picture with a moving corner (rows 0-9, columns 30-39 differ).
        import struct
        import zlib
        rows = b"".join(b"\0" + bytes([40, 120, 200]) * 30 + (bytes([9, 9, 9]) if r < 10 else bytes([40, 120, 200])) * 10
                        for r in range(40))
        ihdr = struct.pack(">IIBBBBB", 40, 40, 8, 2, 0, 0, 0)
        with open(b, "wb") as f:
            f.write(kit.PNG_SIGNATURE + kit._chunk(b"IHDR", ihdr) + kit._chunk(b"IDAT", zlib.compress(rows))
                    + kit._chunk(b"IEND", b""))
        self.assertNotEqual(base.file_sha256(a), base.file_sha256(b))
        self.assertNotEqual(base.masked_sha256(a, [[0, 0, 10, 10]]), base.masked_sha256(b, [[0, 0, 10, 10]]))
        self.assertEqual(base.masked_sha256(a, [[30, 0, 10, 10]]), base.masked_sha256(b, [[30, 0, 10, 10]]))


class HygieneTests(unittest.TestCase):
    """The tests write only into temporary folders: nothing appears beside the scripts."""

    def test_nothing_is_left_beside_the_scripts(self):
        self.assertEqual(kit.stray_folders(), [], "folders written beside the scripts (tests must use temp folders)")


def tearDownModule():
    kit.assert_no_residue()


if __name__ == "__main__":
    unittest.main()
