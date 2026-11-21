"""Tests for ``capture.py --record``: a screen's steps recorded from its first launch (after the device is prepared
and any reboot a locale change needs) until after its last step, stopped before verify, the screenshot and the
reset; ``simctl io recordVideo`` on the display the screenshots take, flushed by a moment's status bar change whose
time the report gives; Android's ``screenrecord`` pulled after, within its time limit; drivers with no simulator or
Android device under them refused before anything runs; the dry run. Through a fake ``RUNNER`` and ``SPAWNER``.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here runs a real tool, reaches
a network or waits.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import signal
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture  # noqa: E402
import capture_testkit as kit  # noqa: E402
import drivers  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from drivers import adb as adb_driver  # noqa: E402
from drivers import base  # noqa: E402
from drivers import simctl as simctl_driver  # noqa: E402

UDID = "11111111-2222-3333-4444-555555555555"
TYPE_ID = "com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max"
DEVICETYPES = {"devicetypes": [{"name": "iPhone 17 Pro Max", "identifier": TYPE_ID, "productFamily": "iPhone"}]}
RUNTIMES = {"runtimes": [
    {"name": "iOS 27.2", "version": "27.2", "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-2",
     "platform": "iOS", "isAvailable": True, "supportedDeviceTypes": [{"identifier": TYPE_ID}]}]}
TWO_SCREENS = """Port:
    Class: DisplayAdapter
    Connected Screens:
    (1) LCD:
        Screen ID: 1
        Screen Type: Integrated
        Pixel Size: {1398, 2034}
    (2) LCD-1:
        Screen ID: 3
        Screen Type: Integrated
        Pixel Size: {2007, 2853}
"""
SERIAL = "emulator-5554"
REMOTE = "/sdcard/appstores-recording.mp4"


def write_movie(cmd):
    """What a recorder leaves when it's stopped: a file at its last argument."""
    os.makedirs(os.path.dirname(cmd[-1]), exist_ok=True)
    with open(cmd[-1], "wb") as f:
        f.write(b"\0\0\0\x18ftypqt  movie")


class RecordCase(unittest.TestCase):
    def setUp(self):
        self.hooks = kit.Hooks()
        self.addCleanup(self.hooks.restore)
        self.run_ = self.hooks.runner
        self.tmp = tempfile.mkdtemp(prefix="capture-record-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved_env = dict(os.environ)
        os.environ.pop("ANDROID_HOME", None)
        os.environ.pop("ANDROID_SDK_ROOT", None)
        self.addCleanup(self._env_back, saved_env)
        saved = capture.log
        self.logged = []
        capture.log = self.logged.append
        self.addCleanup(setattr, capture, "log", saved)

    def _env_back(self, saved):
        os.environ.clear()
        os.environ.update(saved)

    def simulator(self, enumerate_out="", width=1320, height=2868):
        self.run_.on(r"simctl list devices -j", out=json.dumps({"devices": {}}))
        self.run_.on(r"simctl list devicetypes -j", out=json.dumps(DEVICETYPES))
        self.run_.on(r"simctl list runtimes -j", out=json.dumps(RUNTIMES))
        self.run_.on(r"simctl create ", out=UDID + "\n")
        self.run_.on(r"simctl ui \S+ appearance$", out="light\n")
        self.run_.on(r"simctl status_bar \S+ list", out="Time: 9:41\n")
        self.run_.on(r"simctl io \S+ enumerate", out=enumerate_out)
        self.run_.on(r"io .* screenshot", write_png=(width, height, None))
        self.hooks.on_spawn(r"recordVideo", log="Recording started\n", on_signal=write_movie)

    def main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()) as err:
            code = capture.main(list(args))
        self.stdout = out.getvalue()
        self.stderr = err.getvalue()
        return code

    def at(self, pattern, start=0):
        i = self.run_.index(pattern, start)
        self.assertGreaterEqual(i, 0, "no command matching %r in:\n%s" % (pattern, "\n".join(self.run_.lines)))
        return i

    def report(self):
        return jsonio.load(os.path.join(self.tmp, "captures", "capture-report.json"))


IPHONE = {"id": "iphone-6.9", "platform": "ios", "driver": "simctl", "width": 1320, "height": 2868,
          "target": {"deviceType": "iPhone 17 Pro Max"}}
SCREEN = {"id": "plan", "steps": [{"launch": {"args": {"ScreenshotScreen": "plan"}}},
                                  {"deepLink": "samplerecipes://recipe/demo"}, {"wait": {"ms": 1500}}]}


class SimctlRecordTests(RecordCase):
    def test_the_steps_are_recorded_after_the_reboot_and_stopped_before_the_shot_and_the_reset(self):
        self.simulator()
        plan = kit.write_plan(self.tmp, kit.sample_plan([dict(IPHONE, locales=["de-DE"])], [SCREEN],
                                                         locales=["de-DE"]))
        self.assertEqual(self.main("--plan", plan, "--record"), 0, self.stderr)
        self.assertEqual(len(self.hooks.spawned), 1)
        cmd = self.hooks.spawned[0]
        self.assertRegex(cmd, r"^xcrun simctl io %s recordVideo --codec=h264 --mask=ignored --force "
                              r"\S+/de-DE/iphone-6.9/plan\.mov$" % UDID)
        started = self.hooks.spawned_at[0]
        # After the locale's reboot and the clean status bar, before the launch.
        reboot = max(i for i, l in enumerate(self.run_.lines) if " bootstatus " in l)
        self.assertGreater(started, reboot)
        self.assertGreater(started, self.at(r"status_bar \S+ override --time"))
        self.assertLessEqual(started, self.at(r"simctl launch "))
        # The flush after the last step, then SIGINT, then the battery back, then the shot and the reset.
        flush = self.at(r"status_bar %s override --batteryLevel 99$" % UDID)
        self.assertGreater(flush, self.at(r"simctl openurl "))
        self.assertEqual(len(self.hooks.signals), 1)
        line, sig, stopped = self.hooks.signals[0]
        self.assertEqual((line, sig), (cmd, signal.SIGINT))
        self.assertEqual(stopped, flush + 1)
        back = self.at(r"status_bar %s override --batteryLevel 100$" % UDID, flush)
        self.assertGreaterEqual(back, stopped)
        self.assertGreater(self.at(r"io %s screenshot" % UDID), back)
        self.assertGreater(self.at(r"status_bar %s clear" % UDID), back)
        self.assertGreater(self.at(r"simctl shutdown %s" % UDID, back), back)
        # In place beside the picture, and in the report: its length, where it started, the flush to trim at.
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "captures", "de-DE", "iphone-6.9", "plan.mov")))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "captures", "de-DE", "iphone-6.9", "plan.png")))
        rec = self.report()["shots"][0]["recording"]
        self.assertEqual(rec["path"], "de-DE/iphone-6.9/plan.mov")
        self.assertEqual(rec["by"], "simctl recordVideo")
        self.assertTrue(rec["from"].startswith("step 1 (launch"), rec["from"])
        self.assertEqual(rec["flush"]["by"], "status bar battery 99%")
        # The steps' wait (1.5 s) and the second after them, then the flush held a second.
        self.assertAlmostEqual(rec["flush"]["at"], 2.5, places=2)
        self.assertAlmostEqual(rec["seconds"], 3.5, places=1)
        self.assertNotIn("display", rec)
        self.assertTrue(any(l.startswith("recorded de-DE/iphone-6.9/plan.mov") and "--end 2.50" in l
                            for l in self.logged), self.logged)

    def test_a_seed_runs_before_the_recording_starts(self):
        self.simulator()
        plan = kit.sample_plan([IPHONE], [SCREEN], staging={
            "seed": {"kind": "command", "run": ["sh", "seed.sh"]}, "confirmed": {"screen": "plan"}})
        path = kit.write_plan(self.tmp, plan)
        self.assertEqual(self.main("--plan", path, "--record"), 0, self.stderr)
        self.assertGreater(self.hooks.spawned_at[0], self.at(r"^sh seed.sh"))
        self.assertIn("step 2 (launch", self.report()["shots"][0]["recording"]["from"])

    def test_the_display_the_screenshots_take_is_recorded(self):
        self.simulator(TWO_SCREENS, 2007, 2853)
        duo = dict(IPHONE, id="duo-inner", width=2007, height=2853)
        path = kit.write_plan(self.tmp, kit.sample_plan([duo], [SCREEN]))
        self.assertEqual(self.main("--plan", path, "--record"), 0, self.stderr)
        self.assertIn(" recordVideo --codec=h264 --mask=ignored --display=3 --force ", self.hooks.spawned[0])
        self.assertTrue(self.run_.matching(r"screenshot --type=png --mask=ignored --display=3 "))
        self.assertEqual(self.report()["shots"][0]["recording"]["display"], "3")

    def test_an_as_is_status_bar_is_cleared_after_the_flush(self):
        self.simulator()
        path = kit.write_plan(self.tmp, kit.sample_plan([IPHONE], [SCREEN], statusBar="as-is"))
        self.assertEqual(self.main("--plan", path, "--record"), 0, self.stderr)
        flush = self.at(r"override --batteryLevel 99$")
        self.at(r"status_bar %s clear$" % UDID, flush)
        self.assertEqual(self.run_.matching(r"override --batteryLevel 100$"), [])

    def test_a_failed_step_stops_the_recording_and_keeps_nothing(self):
        self.simulator()
        self.run_.on(r"simctl openurl", code=1, err="no handler for samplerecipes://")
        path = kit.write_plan(self.tmp, kit.sample_plan([IPHONE], [SCREEN]))
        self.assertEqual(self.main("--plan", path, "--record"), 1)
        self.assertEqual([s for _, s, _ in self.hooks.signals], [signal.SIGINT])
        self.assertEqual(self.run_.matching(r"batteryLevel 99"), [])
        entry = self.report()["shots"][0]
        self.assertEqual(entry["status"], "missed")
        self.assertNotIn("recording", entry)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "captures", "en-US", "iphone-6.9", "plan.mov")))

    def test_a_recorder_that_never_starts_misses_the_shot(self):
        self.simulator()
        self.hooks.on_spawn(r"recordVideo", log="")
        path = kit.write_plan(self.tmp, kit.sample_plan([IPHONE], [SCREEN]))
        self.assertEqual(self.main("--plan", path, "--record"), 1)
        entry = self.report()["shots"][0]
        self.assertEqual(entry["status"], "missed")
        self.assertIn("recordVideo's first frame", entry["reason"])
        self.assertEqual(self.run_.matching(r"simctl launch "), [])

    def test_a_tv_has_no_status_bar_to_flush_and_says_so(self):
        self.simulator(width=3840, height=2160)
        self.run_.on(r"simctl list devices -j", out=json.dumps({"devices": {
            "com.apple.CoreSimulator.SimRuntime.tvOS-27-2": [{"udid": UDID, "name": "Apple TV 4K", "state": "Booted",
                                                             "isAvailable": True}]}}))
        tv = {"id": "tv", "platform": "tvos", "driver": "simctl", "width": 3840, "height": 2160,
              "target": {"udid": UDID}}
        path = kit.write_plan(self.tmp, kit.sample_plan([tv], [SCREEN]))
        self.assertEqual(self.main("--plan", path, "--record"), 0, self.stderr)
        entry = self.report()["shots"][0]
        self.assertIsNone(entry["recording"]["flush"])
        self.assertTrue(any("nothing flushed" in w for w in entry["warnings"]), entry["warnings"])
        self.assertEqual(self.run_.matching(r"batteryLevel 99"), [])

    def test_without_record_nothing_is_recorded(self):
        self.simulator()
        path = kit.write_plan(self.tmp, kit.sample_plan([IPHONE], [SCREEN]))
        self.assertEqual(self.main("--plan", path), 0, self.stderr)
        self.assertEqual(self.hooks.spawned, [])
        self.assertNotIn("recording", self.report()["shots"][0])


class DryRunRecordTests(RecordCase):
    def test_the_dry_run_says_when_it_would_record_flush_and_stop(self):
        devices = [dict(IPHONE, target={"deviceType": "iPhone 17 Pro Max", "display": "3"}),
                   {"id": "android-phone", "platform": "android", "driver": "adb", "width": 1080, "height": 1920,
                    "target": {"serial": SERIAL}}]
        path = kit.write_plan(self.tmp, kit.sample_plan(devices, [SCREEN]))
        self.assertEqual(self.main("--plan", path, "--record", "--dry-run"), 0, self.stderr)
        self.assertEqual(self.run_.calls, [])
        self.assertEqual(self.hooks.spawned, [])
        out = self.stdout
        self.assertIn("record from step 1 (launch", out)
        self.assertRegex(out, r"\$ xcrun simctl io .+ recordVideo --codec=h264 --mask=ignored --display=3 --force "
                              r"\S+/plan\.mov &")
        self.assertRegex(out, r"status_bar .+ override --batteryLevel 99")
        self.assertIn("stop the recording (SIGINT)", out)
        self.assertIn("-> would record en-US/iphone-6.9/plan.mov", out)
        self.assertIn("$ adb -s %s shell 'screenrecord --bit-rate 20000000 --time-limit 180 %s' &" % (SERIAL, REMOTE),
                      out)
        self.assertIn("adb -s %s shell 'pkill -INT screenrecord'" % SERIAL, out)
        self.assertRegex(out, r"adb -s %s pull %s \S+/plan\.mp4" % (SERIAL, REMOTE))
        self.assertIn("-> would record en-US/android-phone/plan.mp4", out)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "captures")))


class RefusalTests(RecordCase):
    def test_a_device_with_no_simulator_or_android_device_under_it_is_refused_before_anything_runs(self):
        devices = [IPHONE,
                   {"id": "web", "platform": "web", "driver": "chrome", "width": 1280, "height": 800},
                   {"id": "mac", "platform": "macos", "driver": "appium", "width": 2880, "height": 1800}]
        path = kit.write_plan(self.tmp, kit.sample_plan(devices, [SCREEN]))
        for extra in ([], ["--dry-run"]):
            self.assertEqual(self.main("--plan", path, "--record", *extra), 3)
            self.assertIn("--record can't record on web (chrome): the chrome driver can't record a screen",
                          self.stderr)
            self.assertIn("mac (appium): appium records a screen through its host (simctl or adb), and mac has none",
                          self.stderr)
            self.assertNotIn("iphone-6.9 (simctl)", self.stderr)
            self.assertEqual(self.run_.calls, [])
        # Leaving them out, the rest records.
        self.simulator()
        self.assertEqual(self.main("--plan", path, "--record", "--devices", "iphone-6.9"), 0, self.stderr)

    def test_drivers_record_through_their_host(self):
        options = base.Options(plan_dir=self.tmp, workdir=os.path.join(self.tmp, "work"))
        ios = {"id": "p", "platform": "ios", "target": {}}
        android = {"id": "a", "platform": "android", "target": {}}
        for name in ("simctl", "appium", "xcuitest", "devflow", "ailoha", "maestro"):
            self.assertIsNone(drivers.get(name)(options).record_support(ios), name)
        for name in ("adb", "uiautomator", "appium", "devflow", "maestro"):
            self.assertIsNone(drivers.get(name)(options).record_support(android), name)
        self.assertEqual(drivers.get("appium")(options).recording_ext(ios), ".mov")
        self.assertEqual(drivers.get("appium")(options).recording_ext(android), ".mp4")
        self.assertIn("has none", drivers.get("devflow")(options).record_support(
            {"id": "p", "platform": "ios", "target": {"host": "none"}}))
        for name in ("chrome", "macos"):
            self.assertIn("can't record a screen", drivers.get(name)(options).record_support(ios))


class AdbRecordTests(RecordCase):
    def android(self):
        self.run_.on(r"^adb devices$", out="List of devices attached\n%s\tdevice\n" % SERIAL)
        self.run_.on(r"shell 'getprop sys.boot_completed'", out="1\n")
        self.run_.on(r"shell 'getprop ro.build.version.sdk'", out="36\n")
        self.run_.on(r"shell 'wm size'$", out="Physical size: 1080x2400\n")
        self.run_.on(r"shell 'wm density'$", out="Physical density: 420\n")
        self.run_.on(r"shell 'cmd uimode night'$", out="Night mode: no\n")
        self.run_.on(r"shell 'settings get global sysui_demo_allowed'", out="null\n")
        self.run_.on(r"exec-out screencap -p", out=kit.png_bytes(1080, 1920))
        self.run_.on(r"shell 'am start", out="Status: ok\nLaunchState: COLD\n")
        self.run_.on(r" pull %s " % REMOTE, then=write_movie)
        self.drv = adb_driver.AdbDriver(base.Options(plan_dir=self.tmp, workdir=os.path.join(self.tmp, "work"),
                                                     record=True))
        self.device = {"id": "android-phone", "platform": "android", "driver": "adb", "width": 1080, "height": 1920,
                       "locales": ["en-US"], "appearance": "light", "clock": "09:41", "statusBar": "clean",
                       "seed": "demo", "flatten": "#000000",
                       "app": {"package": "com.example.samplerecipes", "activity": ".MainActivity"},
                       "target": {"serial": SERIAL}}
        self.drv.prepare(self.device, {})

    def screen(self, steps):
        return {"id": "plan", "steps": steps, "locales": ["en-US"], "appearance": None, "clock": None,
                "statusBar": None, "seed": None, "flatten": None}

    def test_screenrecord_runs_on_the_device_through_the_steps_and_is_pulled_before_the_shot(self):
        self.android()
        start = len(self.run_.lines)
        shot = self.drv.run_screen(self.device, self.screen([{"launch": {}}, {"deepLink": "samplerecipes://x"}]),
                                   "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(self.hooks.spawned[-1], "adb -s %s shell 'screenrecord --bit-rate 20000000 --time-limit 180 "
                                                 "%s'" % (SERIAL, REMOTE))
        self.assertGreater(self.hooks.spawned_at[-1], self.at(r"command clock", start))
        self.assertLessEqual(self.hooks.spawned_at[-1], self.at(r"shell 'am start", start))
        kill = self.at(r"shell 'pkill -INT screenrecord'$", start)
        self.assertGreater(kill, self.at(r"android.intent.action.VIEW", start))
        pull = self.at(r"pull %s \S+/work/en-US/android-phone/plan\.mp4$" % REMOTE, kill)
        rm = self.at(r"shell 'rm -f %s'$" % REMOTE, pull)
        self.assertGreater(self.at(r"exec-out screencap -p$", rm), rm)
        self.assertEqual(self.run_.matching(r"batteryLevel|demo -e command battery -e level 99"), [])
        rec = shot.recording
        self.assertEqual((rec["by"], rec["flush"], rec["display"]), ("adb screenrecord", None, None))
        self.assertTrue(os.path.isfile(rec["file"]) and rec["file"].endswith("plan.mp4"))
        self.assertAlmostEqual(rec["seconds"], 2.0, places=1)   # screenrecord's start, and a second after the steps

    def test_steps_longer_than_screenrecords_limit_are_said_so(self):
        self.android()
        shot = self.drv.run_screen(self.device, self.screen([{"launch": {}}, {"wait": {"ms": 200000}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(shot.recording["seconds"], 180.0)
        self.assertTrue(any("screenrecord stops at 180 s" in w for w in shot.warnings), shot.warnings)

    def test_the_display_in_use_is_recorded(self):
        self.android()
        self.device["target"]["display"] = "4619827259835644672"
        self.drv.run_screen(self.device, self.screen([{"launch": {}}]), "en-US")
        self.assertIn("--display-id 4619827259835644672 %s" % REMOTE, self.hooks.spawned[-1])
        self.assertTrue(self.run_.matching(r"screencap -p -d 4619827259835644672"))


class RecordedRunTests(RecordCase):
    def test_a_tool_run_once_for_several_screens_is_recorded_once(self):
        class Recorder(base.Driver):
            NAME = "recorder"
            started = []

            def record_support(self, device):
                return None

            def start_recording(self, device, path):
                Recorder.started.append(path)
                return {}

            def stop_recording(self, device, rec, shot):
                return {"seconds": 1.0, "by": "test", "flush": None}

        drv = Recorder(base.Options(plan_dir=self.tmp, workdir=os.path.join(self.tmp, "work"), record=True))
        device = {"id": "p", "platform": "ios"}
        for screen, cached in (("plan", False), ("recipe", True)):
            shot = base.Shot()
            ctx = base.StepContext(device, {"id": screen}, "en-US", shot, 1, {"flow": "StoreShots"})
            self.assertEqual(drv.recorded(ctx, lambda: "ran", cached=cached), "ran")
        self.assertEqual(len(Recorder.started), 1)
        self.assertTrue(Recorder.started[0].endswith("plan.mp4"))
        self.assertTrue(any("ran once for several screens" in w for w in shot.warnings), shot.warnings)


def tearDownModule():
    kit.assert_no_residue()


if __name__ == "__main__":
    unittest.main()
