"""Tests for drivers/base.py and the command-line drivers (simctl, adb, uiautomator, chrome, macos): the exact
commands each issues to prepare, run steps, capture and reset, through a fake ``RUNNER`` (and a fake Chrome).

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here runs a real tool, reaches
a network or waits.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture  # noqa: E402
import capture_testkit as kit  # noqa: E402
import drivers  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import web  # noqa: E402
from drivers import adb as adb_driver  # noqa: E402
from drivers import base  # noqa: E402
from drivers import chrome as chrome_driver  # noqa: E402
from drivers import macos as macos_driver  # noqa: E402
from drivers import simctl as simctl_driver  # noqa: E402
from drivers import uiautomator as uia_driver  # noqa: E402

UDID = "11111111-2222-3333-4444-555555555555"
TYPE_ID = "com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max"
DEVICETYPES = {"devicetypes": [{"name": "iPhone 17 Pro Max", "identifier": TYPE_ID, "productFamily": "iPhone"},
                               {"name": "iPhone 17 Pro", "identifier": TYPE_ID.replace("-Max", "")}]}
RUNTIMES = {"runtimes": [
    {"name": "iOS 27.1", "version": "27.1", "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-1",
     "platform": "iOS", "isAvailable": True, "supportedDeviceTypes": [{"identifier": TYPE_ID}]},
    {"name": "iOS 27.2", "version": "27.2", "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-2-iPhone19-4",
     "platform": "iOS", "isAvailable": True, "supportedDeviceTypes": [{"identifier": "other"}]},
    {"name": "iOS 27.2", "version": "27.2", "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-2",
     "platform": "iOS", "isAvailable": True, "supportedDeviceTypes": [{"identifier": TYPE_ID}, {"identifier": "x"}]},
    {"name": "watchOS 27.2", "version": "27.2", "identifier": "com.apple.CoreSimulator.SimRuntime.watchOS-27-2",
     "platform": "watchOS", "isAvailable": True, "supportedDeviceTypes": []}]}
UI_XML = ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
          '<node index="0" text="" resource-id="" class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">'
          '<node index="0" text="This week" resource-id="com.example.samplerecipes:id/title" content-desc="" '
          'class="android.widget.TextView" bounds="[40,200][600,260]"/>'
          '<node index="1" text="" resource-id="com.example.samplerecipes:id/search" content-desc="Search recipes" '
          'class="android.widget.ImageButton" bounds="[900,100][1040,240]"/>'
          '</node></hierarchy>')


class DriverCase(unittest.TestCase):
    def setUp(self):
        self.hooks = kit.Hooks()
        self.addCleanup(self.hooks.restore)
        self.run_ = self.hooks.runner
        self.tmp = tempfile.mkdtemp(prefix="capture-drivers-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.options = base.Options(plan_dir=self.tmp, workdir=os.path.join(self.tmp, "work"))

    def device(self, **kw):
        d = {"id": "iphone-6.9", "platform": "ios", "driver": "simctl", "width": 1320, "height": 2868,
             "locales": ["en-US"], "appearance": "light", "clock": "09:41", "statusBar": "clean", "seed": "demo",
             "flatten": "#000000", "app": {"bundleId": "com.example.samplerecipes"},
             "target": {"deviceType": "iPhone 17 Pro Max", "runtime": "latest"}}
        d.update(kw)
        return d

    def screen(self, steps, **kw):
        s = {"id": "plan", "steps": steps, "locales": ["en-US"], "appearance": None, "clock": None,
             "statusBar": None, "seed": None, "flatten": None}
        s.update(kw)
        return s

    def assertInOrder(self, patterns):
        at = 0
        for p in patterns:
            i = self.run_.index(p, at)
            self.assertGreaterEqual(i, 0, "no command matching %r after #%d in:\n%s" % (p, at, "\n".join(self.run_.lines)))
            at = i + 1


# -- base ------------------------------------------------------------------------------------------------------

class BaseRunTests(DriverCase):
    def test_run_logs_and_returns_text(self):
        self.run_.on(r"^echo hi$", out="hi\n")
        res = base.run(["echo", "hi"])
        self.assertTrue(res.ok)
        self.assertEqual(res.out, "hi\n")
        self.assertIn("  $ echo hi", self.hooks.log)

    def test_env_is_passed_alone_and_logged(self):
        base.run(["tool"], env={"SIMCTL_CHILD_A": "1"})
        self.assertEqual(self.run_.calls[-1][1], {"SIMCTL_CHILD_A": "1"})
        self.assertIn("  $ SIMCTL_CHILD_A=1 tool", self.hooks.log)

    def test_nonzero_exit_raises_command_error(self):
        self.run_.on(r"^false", code=3, err="broken\n")
        with self.assertRaises(base.CommandError) as c:
            base.run(["false"])
        self.assertEqual(c.exception.code, 3)
        self.assertIn("broken", str(c.exception))
        self.assertEqual(base.run(["false"], check=False).code, 3)

    def test_missing_tool_is_tool_missing_with_a_hint(self):
        self.run_.on(r"^adb", raises=FileNotFoundError())
        with self.assertRaises(base.ToolMissing) as c:
            base.run(["adb", "devices"])
        self.assertIn("platform-tools", str(c.exception))

    def test_timeout(self):
        import subprocess
        self.run_.on(r"^slow", raises=subprocess.TimeoutExpired("slow", 1))
        with self.assertRaises(base.CommandTimeout):
            base.run(["slow"], timeout=1)

    def test_dry_run_runs_nothing_and_answers_dry_output(self):
        base.DRY_RUN = True
        res = base.run(["xcrun", "simctl", "create", "x"], dry_output="<udid>")
        self.assertEqual(res.out, "<udid>")
        self.assertTrue(res.dry)
        self.assertEqual(self.run_.calls, [])
        self.assertIsNone(base.spawn(["emulator", "-avd", "x"]))
        self.assertEqual(self.hooks.spawned, [])

    def test_binary_output(self):
        self.run_.on(r"screencap", out=b"\x89PNG\x00\xff")
        self.assertEqual(base.run(["adb", "exec-out", "screencap", "-p"], binary=True).out, b"\x89PNG\x00\xff")

    def test_poll_times_out_on_the_fake_clock(self):
        with self.assertRaises(base.StepFailed):
            base.poll(lambda: False, 5, interval=1, what="nothing")
        self.assertGreaterEqual(self.hooks.time.now, 5)
        self.assertEqual(base.poll(lambda: "yes", 5), "yes")


class RealRunnerTests(unittest.TestCase):
    def test_a_command_without_input_never_reads_the_callers_stdin(self):
        import subprocess
        child = ("import sys; sys.path.insert(0, %r); from drivers import base; "
                 "code, out, err = base.subprocess_runner([sys.executable, '-c', 'import sys; print(repr(sys.stdin.read()))']); "
                 "print(out.decode().strip()); print(sys.stdin.read().strip())" % os.path.dirname(os.path.abspath(__file__)))
        res = subprocess.run([sys.executable, "-c", child], input=b".next/path\n", stdout=subprocess.PIPE, timeout=60)
        self.assertEqual(res.stdout.decode().split(), ["''", ".next/path"])

    def test_input_still_reaches_the_command(self):
        code, out, _ = base.subprocess_runner([sys.executable, "-c", "import sys; print(sys.stdin.read())"], input=b"no")
        self.assertEqual((code, out.strip()), (0, b"no"))


class BaseHttpTests(DriverCase):
    def setUp(self):
        DriverCase.setUp(self)
        self.sent = []
        saved = web.TRANSPORT

        def transport(method, url, headers, body, timeout):
            self.sent.append((method, url))
            return web.Response(200, {"Content-Type": "application/json"}, b'{"ok": true}')

        web.TRANSPORT = transport
        self.addCleanup(setattr, web, "TRANSPORT", saved)

    def test_localhost_and_loopback_are_allowed(self):
        for url in ("http://localhost:4723/status", "http://127.0.0.1:9223/api", "http://[::1]:8080/x"):
            self.assertEqual(base.http_json("GET", url), {"ok": True})
        self.assertEqual(len(self.sent), 3)

    def test_anything_else_is_refused_before_sending(self):
        for url in ("https://example.com/", "http://10.0.0.2:4723/", "http://localhost.example.com/",
                    "file:///etc/hosts", "ftp://127.0.0.1/"):
            with self.assertRaises(base.NotLocal, msg=url):
                base.http("GET", url)
        self.assertEqual(self.sent, [])

    def test_errors_become_driver_errors(self):
        web.TRANSPORT = lambda *a: web.Response(500, {}, b"nope")
        with self.assertRaises(base.DriverError):
            base.http_json("GET", "http://127.0.0.1:1/")


class BaseElementTests(unittest.TestCase):
    def test_uiautomator_parse_and_find(self):
        root, els = base.parse_uiautomator("UI hierchary dumped to: /dev/tty\n" + UI_XML)
        self.assertEqual(len(els), 3)
        self.assertEqual(base.find_element(els, "id", "search").center, (970, 170))
        self.assertEqual(base.find_element(els, "text", "this week").center, (320, 230))
        self.assertEqual(base.find_element(els, "label", "Search").id, "com.example.samplerecipes:id/search")
        self.assertIsNone(base.find_element(els, "id", "missing"))
        el = base.find_xpath(root, "//node[@text='This week']")
        self.assertEqual(el.bounds, (40, 200, 600, 260))

    def test_element_query(self):
        self.assertEqual(base.element_query({"id": "a", "timeout": 3}), ("id", "a"))
        self.assertIsNone(base.element_query({"ms": 3}))
        with self.assertRaises(ValueError):
            base.element_query({"id": "a", "text": "b"})

    def test_step_of_and_describe(self):
        self.assertEqual(base.step_of({"tap": {"id": "x"}, "$comment": "c"}), ("tap", {"id": "x"}))
        self.assertEqual(base.describe_step({"launch": {"args": {"A": "b"}}}), 'launch {args: {"A": "b"}}')
        with self.assertRaises(ValueError):
            base.step_of({"tap": {}, "wait": 1})

    def test_a_type_steps_text_is_the_words_not_a_finder(self):
        self.assertIsNone(base.step_element("type", {"text": "pasta"}))
        self.assertEqual(base.step_element("type", {"text": "pasta", "id": "search"}), ("id", "search"))
        self.assertEqual(base.step_element("type", {"text": "pasta", "into": "Search recipes"}),
                         ("text", "Search recipes"))
        self.assertEqual(base.step_element("scroll", {"to": {"id": "more"}, "direction": "down"}), ("id", "more"))
        self.assertEqual(base.step_element("tap", {"label": "Search"}), ("label", "Search"))

    def test_type_steps_are_checked_by_their_target(self):
        class IdOnly(base.Driver):
            NAME = "idonly"
            STEPS = ("type", "wait")
            FINDERS = ("id",)

        drv = IdOnly(base.Options())
        ok = {"id": "s", "steps": [{"type": {"text": "pasta"}}, {"type": {"text": "pasta", "id": "search"}}]}
        self.assertIsNone(drv.unsupported(ok))
        why = drv.unsupported({"id": "s", "steps": [{"type": {"text": "pasta", "into": "Search recipes"}}]})
        self.assertIn("can't find elements by text", why)
        why = drv.unsupported({"id": "s", "steps": [{"type": {"text": "pasta", "id": "a", "label": "b"}}]})
        self.assertIn("one way", why)

    def test_shot_rejects_unknown_states(self):
        with self.assertRaises(ValueError):
            base.Shot(status="done")
        with self.assertRaises(ValueError):
            base.Shot(status_bar="clean")


class BaseDriverTests(DriverCase):
    def test_unsupported_step_is_skipped_without_running_anything(self):
        drv = simctl_driver.SimctlDriver(self.options)
        drv.udid = UDID
        shot = drv.run_screen(self.device(), self.screen([{"launch": {}}, {"tap": {"id": "search"}}]), "en-US")
        self.assertEqual(shot.status, "skipped")
        self.assertIn("can't do tap steps", shot.reason)
        self.assertEqual(self.run_.calls, [])

    def test_wait_for_an_element_on_a_blind_driver_waits_and_warns(self):
        drv = simctl_driver.SimctlDriver(self.options)
        drv.udid = UDID
        drv.state = {"locale": "en-US", "appearance": "light", "statusBar": ("clean", "09:41")}
        self.run_.on(r"io .* screenshot", write_png=(1320, 2868, None))
        shot = drv.run_screen(self.device(), self.screen([{"wait": {"text": "This week", "timeout": 2}}]), "en-US")
        self.assertEqual(shot.status, "taken")
        self.assertIn(2.0, self.hooks.time.slept)
        self.assertTrue(any("can't see elements" in w for w in shot.warnings))

    def test_settle_waits_for_two_identical_frames(self):
        drv = simctl_driver.SimctlDriver(self.options)
        drv.udid = UDID
        drv.state = {"locale": "en-US", "appearance": "light", "statusBar": ("clean", "09:41")}
        frames = iter([(10, 20, 30), (11, 20, 30), (11, 20, 30), (99, 0, 0)])
        self.run_.on(r"io .* screenshot", then=lambda cmd: kit.write_png(cmd[-1], 8, 8, colour=next(frames)))
        shot = drv.run_screen(self.device(), self.screen([{"settle": {}}]), "en-US")
        self.assertEqual(shot.status, "taken")
        self.assertEqual(len(self.run_.matching(r"screenshot")), 4)  # three to settle, then the shot

    def test_script_step_runs_from_the_plan_folder_with_context(self):
        drv = simctl_driver.SimctlDriver(self.options)
        drv.udid = UDID
        drv.state = {"locale": "en-US", "appearance": "light", "statusBar": ("clean", "09:41")}
        self.run_.on(r"io .* screenshot", write_png=(1320, 2868, None))
        drv.run_screen(self.device(), self.screen([{"script": "tools/seed.sh --fast"}]), "en-US")
        line, env = self.run_.calls[0]
        self.assertEqual(line, "tools/seed.sh --fast")
        self.assertEqual(env["APPSTORES_SCREEN"], "plan")
        self.assertEqual(env["APPSTORES_UDID"], UDID)

    def test_registry(self):
        self.assertIs(drivers.get("simctl"), simctl_driver.SimctlDriver)
        self.assertIs(drivers.get("uiautomator"), uia_driver.UiAutomatorDriver)
        with self.assertRaises(drivers.UnknownDriver):
            drivers.get("nope")
        with self.assertRaises(drivers.UnknownDriver):
            drivers.get("import")
        caps = drivers.get("adb")().capabilities()
        self.assertIn("tap", caps["steps"])
        self.assertIn("xpath", caps["finders"])


# -- simctl --------------------------------------------------------------------------------------------------

class SimctlTests(DriverCase):
    def answers(self, devices=None):
        self.run_.on(r"simctl list devices -j", out=json.dumps({"devices": devices or {}}))
        self.run_.on(r"simctl list devicetypes -j", out=json.dumps(DEVICETYPES))
        self.run_.on(r"simctl list runtimes -j", out=json.dumps(RUNTIMES))
        self.run_.on(r"simctl create ", out=UDID + "\n")
        self.run_.on(r"simctl ui \S+ appearance$", out="dark\n")
        self.run_.on(r"simctl status_bar \S+ list", out="Current Status Bar Overrides:\nTime: 9:41\n")
        self.run_.on(r"io .* screenshot", write_png=(1320, 2868, None))

    def test_prepare_creates_a_dedicated_simulator_and_boots_it(self):
        self.answers()
        drv = simctl_driver.SimctlDriver(self.options)
        app = os.path.join(self.tmp, "build", "SampleRecipes.app")
        os.makedirs(app)
        drv.prepare(self.device(app={"bundleId": "com.example.samplerecipes", "app": "build/SampleRecipes.app"}), {})
        self.assertInOrder([
            r"^xcrun simctl list devices -j$",
            r"^xcrun simctl list devicetypes -j$",
            r"^xcrun simctl list runtimes -j$",
            r"^xcrun simctl create appstores-iphone-6.9 %s com.apple.CoreSimulator.SimRuntime.iOS-27-2$" % TYPE_ID,
            r"^xcrun simctl boot %s$" % UDID,
            r"^xcrun simctl bootstatus %s -b$" % UDID,
            r"^xcrun simctl install %s .*/build/SampleRecipes.app$" % UDID,
        ])
        self.assertEqual(drv.source({}), {"deviceType": "iPhone 17 Pro Max", "runtime": "iOS 27.2",
                                           "simulator": "appstores-iphone-6.9"})

    def test_an_existing_own_simulator_is_reused_and_a_booted_one_left_booted(self):
        self.answers({"com.apple.CoreSimulator.SimRuntime.iOS-27-2": [
            {"udid": UDID, "name": "appstores-iphone-6.9", "state": "Booted", "isAvailable": True,
             "deviceTypeIdentifier": TYPE_ID}]})
        drv = simctl_driver.SimctlDriver(self.options)
        drv.prepare(self.device(), {})
        self.assertEqual(self.run_.matching(r"simctl (create|boot )"), [])
        self.assertEqual(drv.source({})["runtime"], "iOS 27.2")
        drv.reset(self.device())
        self.assertEqual(self.run_.matching(r"shutdown|delete"), [])

    def test_a_screen_sets_locale_appearance_status_bar_then_launches_and_captures(self):
        self.answers()
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device(appearance="dark")
        drv.prepare(device, {})
        start = len(self.run_.lines)
        shot = drv.run_screen(device, self.screen([
            {"launch": {"args": {"ScreenshotScreen": "plan", "Fast": True}, "env": {"DEMO": "1"}}},
            {"deepLink": "samplerecipes://recipe/demo"}]), "de-DE")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(shot.status_bar, "verified")
        self.assertTrue(os.path.isfile(shot.path))
        lines = self.run_.lines[start:]
        expected = [
            "xcrun simctl spawn %s defaults read -g AppleLanguages" % UDID,
            "xcrun simctl spawn %s defaults write -g AppleLanguages -array de-DE" % UDID,
            "xcrun simctl spawn %s defaults write -g AppleLocale -string de_DE" % UDID,
            "xcrun simctl shutdown %s" % UDID,
            "xcrun simctl boot %s" % UDID,
            "xcrun simctl bootstatus %s -b" % UDID,
            "xcrun simctl ui %s appearance" % UDID,
            "xcrun simctl ui %s appearance dark" % UDID,
            "xcrun simctl status_bar %s override --time 9:41 --dataNetwork wifi --wifiMode active --wifiBars 3 "
            "--cellularMode active --cellularBars 4 --operatorName '' --batteryState charged --batteryLevel 100" % UDID,
            "xcrun simctl status_bar %s list" % UDID,
            "xcrun simctl launch --terminate-running-process %s com.example.samplerecipes -ScreenshotSeed demo "
            "-ScreenshotScreen plan -Fast YES -AppleLanguages '(de-DE)' -AppleLocale de_DE" % UDID,
            "xcrun simctl openurl %s samplerecipes://recipe/demo" % UDID,
            # Which screens it has, read once: one (the fake answers none), so no --display.
            "xcrun simctl io %s enumerate" % UDID,
        ]
        self.assertEqual(lines[:len(expected)], expected)
        self.assertRegex(lines[len(expected)], r"^xcrun simctl io %s screenshot --type=png --mask=ignored .*/de-DE/"
                                               r"iphone-6.9/plan.png$" % UDID)
        launch_env = [env for line, env in self.run_.calls if " launch " in line][0]
        self.assertEqual(launch_env, {"SIMCTL_CHILD_DEMO": "1"})

    def test_reset_clears_and_shuts_down_but_never_deletes_without_cleanup(self):
        self.answers()
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        drv.run_screen(device, self.screen([{"launch": {}}]), "en-US")
        start = len(self.run_.lines)
        self.assertEqual(drv.reset(device), [])
        self.assertEqual(self.run_.lines[start:], [
            "xcrun simctl status_bar %s clear" % UDID,
            "xcrun simctl ui %s appearance dark" % UDID,
            "xcrun simctl terminate %s com.example.samplerecipes" % UDID,
            "xcrun simctl shutdown %s" % UDID,
        ])

    def test_cleanup_deletes_only_its_own_simulator(self):
        self.answers()
        self.options.cleanup = True
        drv = simctl_driver.SimctlDriver(self.options)
        drv.prepare(self.device(), {})
        drv.reset(self.device())
        self.assertEqual(self.run_.matching(r"simctl delete"), ["xcrun simctl delete %s" % UDID])

    def test_a_named_simulator_is_never_deleted_nor_its_language_changed(self):
        other = "99999999-8888-7777-6666-555555555555"
        self.answers({"com.apple.CoreSimulator.SimRuntime.iOS-27-2": [
            {"udid": other, "name": "My iPhone", "state": "Shutdown", "isAvailable": True,
             "deviceTypeIdentifier": TYPE_ID}]})
        self.options.cleanup = True
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device(target={"udid": other})
        drv.prepare(device, {})
        drv.run_screen(device, self.screen([{"launch": {}}]), "fr-FR")
        drv.reset(device)
        self.assertEqual(self.run_.matching(r"delete|create|defaults write"), [])
        self.assertTrue(self.run_.matching(r"launch .* -AppleLanguages '\(fr-FR\)' -AppleLocale fr_FR"))
        self.assertTrue(self.run_.matching(r"shutdown %s" % other))  # it was off: put back off

    def test_status_bar_not_read_back_or_failed_is_unverified(self):
        self.answers()
        self.run_.on(r"status_bar \S+ list", out="")
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([]), "en-US")
        self.assertEqual(shot.status_bar, "unverified")
        self.assertTrue(any("may not have taken" in w for w in shot.warnings))
        drv2 = simctl_driver.SimctlDriver(self.options)
        self.run_.on(r"status_bar \S+ override", code=1, err="Not supported")
        drv2.prepare(device, {})
        shot = drv2.run_screen(device, self.screen([]), "en-US")
        self.assertEqual(shot.status_bar, "unverified")
        self.assertTrue(any("override failed" in w for w in shot.warnings))

    def test_an_app_file_is_copied_into_the_data_container_replacing_the_old_one(self):
        self.answers()
        container = os.path.join(self.tmp, "container")
        old = kit.write_png(os.path.join(container, "Library", "Caches", "app.db"), 1, 1)
        with open(old + "-wal", "w") as f:
            f.write("stale")
        self.run_.on(r"get_app_container \S+ com.example.samplerecipes data", out=container + "\n")
        seed = kit.write_png(os.path.join(self.tmp, "seed", "app.db"), 2, 2)
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([{"appFile": {"file": "seed/app.db",
                                                                "into": {"ios": "Library/Caches/app.db"}}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        with open(old, "rb") as a, open(seed, "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertFalse(os.path.exists(old + "-wal"))
        self.assertTrue(self.run_.index(r"simctl terminate") < self.run_.index(r"get_app_container"))
        shot = drv.run_screen(device, self.screen([{"appFile": {"file": "seed/app.db", "into": "../../escape.db"}}],
                                                  sid="recipe"), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("stays inside the app's data", shot.reason)

    def test_permissions_are_granted_after_install_and_revoked_in_reset(self):
        self.answers()
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device(permissions=["photos", "location"])
        drv.prepare(device, {})
        self.assertEqual(self.run_.matching(r"simctl privacy"), [
            "xcrun simctl privacy %s grant photos com.example.samplerecipes" % UDID,
            "xcrun simctl privacy %s grant location com.example.samplerecipes" % UDID])
        drv.reset(device)
        self.assertTrue(self.run_.matching(r"privacy %s revoke photos com.example.samplerecipes" % UDID))

    def test_a_simulator_shut_down_under_it_is_booted_again_before_the_locale(self):
        self.answers({"com.apple.CoreSimulator.SimRuntime.iOS-27-2": [
            {"udid": UDID, "name": "appstores-iphone-6.9", "state": "Shutdown", "isAvailable": True,
             "deviceTypeIdentifier": TYPE_ID}]})
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        # Something (a failed UI-test session) shut it down after prepare booted it.
        self.run_.on(r"defaults write -g AppleLanguages", code=149,
                     err="Unable to lookup in current state: Shutdown\nProcess spawn via launchd failed because "
                         "device is not booted")
        writes = []

        def booted(cmd):
            # Once booted again, the next write works.
            self.run_.on(r"defaults write -g AppleLanguages", then=lambda c: writes.append(c))
        self.run_.on(r"simctl boot ", then=booted)
        start = len(self.run_.lines)
        shot = drv.run_screen(device, self.screen([]), "de-DE")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(len(writes), 1)
        self.assertEqual(len([l for l in self.run_.lines[start:] if "simctl boot " in l]), 2)  # again, then the reboot

    def test_tv_has_no_status_bar_and_a_display_is_passed(self):
        self.answers({"com.apple.CoreSimulator.SimRuntime.tvOS-27-2": [
            {"udid": UDID, "name": "Apple TV 4K", "state": "Booted", "isAvailable": True}]})
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device(id="tv", platform="tvos", width=3840, height=2160,
                             target={"udid": UDID, "display": "internal"})
        self.run_.on(r"io .* screenshot", write_png=(3840, 2160, None))
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([]), "en-US")
        self.assertEqual(shot.status_bar, "none")
        self.assertEqual(self.run_.matching(r"status_bar"), [])
        self.assertTrue(self.run_.matching(r"screenshot --type=png --mask=ignored --display=internal "))

    def test_a_failed_launch_is_a_missed_shot(self):
        self.answers()
        self.run_.on(r"simctl launch", code=4, err="The request to open com.example.samplerecipes failed.")
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([{"launch": {}}]), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("failed", shot.reason)

    def test_helpers(self):
        self.assertEqual(simctl_driver.apple_locale("de-DE"), "de_DE")
        self.assertEqual(simctl_driver.apple_locale("zh-Hans-CN"), "zh-Hans_CN")
        self.assertEqual(simctl_driver.apple_locale("fr"), "fr")
        self.assertEqual(simctl_driver.status_bar_time("09:41"), "9:41")
        self.assertEqual(simctl_driver.status_bar_time("2026-06-01T09:41:00"), "2026-06-01T09:41:00")
        self.assertEqual(simctl_driver.first_language('(\n    "de-DE",\n    "en-US"\n)'), "de-DE")


# -- adb -----------------------------------------------------------------------------------------------------

ADB = r"^adb -s \S+ "


class AdbCase(DriverCase):
    def setUp(self):
        DriverCase.setUp(self)
        self.saved_env = dict(os.environ)
        os.environ.pop("ANDROID_HOME", None)
        os.environ.pop("ANDROID_SDK_ROOT", None)
        self.addCleanup(self._env_back)

    def _env_back(self):
        os.environ.clear()
        os.environ.update(self.saved_env)

    def device(self, **kw):
        d = DriverCase.device(self, id="android-phone", platform="android", driver="adb", width=1080, height=1920,
                              app={"package": "com.example.samplerecipes", "activity": ".MainActivity"},
                              target={"avd": "Medium_Phone", "density": 420})
        d.update(kw)
        return d

    def answers(self, connected=""):
        self.run_.on(r"^adb devices$", out="List of devices attached\n" + connected)
        self.run_.on(ADB + r"shell 'getprop sys.boot_completed'", out="1\n")
        self.run_.on(ADB + r"shell 'getprop ro.build.version.sdk'", out="36\n")
        self.run_.on(ADB + r"shell 'wm size'$", out="Physical size: 1080x2400\n")
        self.run_.on(ADB + r"shell 'wm density'$", out="Physical density: 420\n")
        self.run_.on(ADB + r"shell 'settings get global (window|transition|animator)", out="1.0\n")
        self.run_.on(ADB + r"shell 'cmd uimode night'$", out="Night mode: no\n")
        self.run_.on(ADB + r"shell 'settings get global sysui_demo_allowed'", out="null\n")
        self.run_.on(ADB + r"exec-out cat /sdcard/appstores-ui.xml", out=UI_XML)
        self.run_.on(ADB + r"exec-out screencap -p", out=kit.png_bytes(1080, 1920))
        self.run_.on(ADB + r"shell 'am start", out="Status: ok\nLaunchState: COLD\n")


class AdbTests(AdbCase):
    def test_prepare_starts_the_avd_headless_and_lays_out_at_the_device_size(self):
        self.answers()
        drv = adb_driver.AdbDriver(self.options)
        drv.prepare(self.device(), {})
        self.assertEqual(self.hooks.spawned, ["emulator -avd Medium_Phone -port 5580 -no-audio -no-boot-anim "
                                              "-no-snapshot-save -no-window"])
        self.assertInOrder([
            r"^adb start-server$",
            ADB + r"shell 'getprop sys.boot_completed'$",
            ADB + r"shell 'wm size'$",
            ADB + r"shell 'wm size 1080x1920'$",
            ADB + r"shell 'wm density 420'$",
            ADB + r"shell 'settings put global window_animation_scale 0'$",
            ADB + r"shell 'settings put global animator_duration_scale 0'$",
        ])

    def test_a_screen_sets_language_dark_demo_mode_and_finds_elements(self):
        self.answers()
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(appearance="dark")
        drv.prepare(device, {})
        start = len(self.run_.lines)
        shot = drv.run_screen(device, self.screen([
            {"launch": {"args": {"ScreenshotScreen": "plan", "Fast": True, "Count": 3}, "clean": True}},
            {"wait": {"text": "This week"}},
            {"tap": {"id": "search"}},
            {"type": {"text": "pasta bake", "label": "Search recipes"}},
            {"back": True},
            {"swipe": {"from": [540, 1500], "to": [540, 500], "ms": 250}},
            {"deepLink": "samplerecipes://recipe/demo"}]), "de-DE")
        self.assertEqual(shot.status, "taken", shot.reason)
        # The fake device's picture never changes, so demo mode's clock didn't show: not confirmed.
        self.assertEqual(shot.status_bar, "unverified")
        self.assertTrue(any("didn't change when demo mode's clock did" in w for w in shot.warnings))
        with open(shot.path, "rb") as f:
            self.assertTrue(f.read().startswith(b"\x89PNG"))
        lines = [l for l in self.run_.lines[start:] if "uiautomator dump" not in l and "exec-out cat" not in l]
        p = "adb -s emulator-5580 shell "
        self.assertEqual(lines, [
            p + "'cmd locale set-app-locales com.example.samplerecipes --locales de-DE'",
            p + "'cmd uimode night'",
            p + "'cmd uimode night yes'",
            p + "'settings get global sysui_demo_allowed'",
            p + "'settings put global sysui_demo_allowed 1'",
            p + "'am broadcast -a com.android.systemui.demo -e command enter'",
            p + "'am broadcast -a com.android.systemui.demo -e command clock -e hhmm 0941'",
            p + "'am broadcast -a com.android.systemui.demo -e command battery -e level 100 -e plugged false'",
            p + "'am broadcast -a com.android.systemui.demo -e command network -e wifi show -e level 4 -e fully true'",
            p + "'am broadcast -a com.android.systemui.demo -e command network -e mobile hide'",
            p + "'am broadcast -a com.android.systemui.demo -e command notifications -e visible false'",
            p + "'am broadcast -a com.android.systemui.demo -e command status -e bluetooth hide -e volume hide -e alarm "
                "hide -e location hide -e sync hide -e mute hide -e speakerphone hide -e zen hide -e eri hide -e tty "
                "hide -e cast hide -e hotspot hide'",
            # The first time after a boot: leave demo mode and enter it again (a second Wi-Fi icon otherwise).
            p + "'am broadcast -a com.android.systemui.demo -e command exit'",
            p + "'am broadcast -a com.android.systemui.demo -e command enter'",
            p + "'am broadcast -a com.android.systemui.demo -e command clock -e hhmm 0941'",
            p + "'am broadcast -a com.android.systemui.demo -e command battery -e level 100 -e plugged false'",
            p + "'am broadcast -a com.android.systemui.demo -e command network -e wifi show -e level 4 -e fully true'",
            p + "'am broadcast -a com.android.systemui.demo -e command network -e mobile hide'",
            p + "'am broadcast -a com.android.systemui.demo -e command notifications -e visible false'",
            p + "'am broadcast -a com.android.systemui.demo -e command status -e bluetooth hide -e volume hide -e alarm "
                "hide -e location hide -e sync hide -e mute hide -e speakerphone hide -e zen hide -e eri hide -e tty "
                "hide -e cast hide -e hotspot hide'",
            # The pixels: the status bar's strip (read until two reads agree), with demo mode's clock moved and back.
            "adb -s emulator-5580 exec-out screencap -p",
            "adb -s emulator-5580 exec-out screencap -p",
            p + "'am broadcast -a com.android.systemui.demo -e command clock -e hhmm 1208'",
            "adb -s emulator-5580 exec-out screencap -p",
            "adb -s emulator-5580 exec-out screencap -p",
            p + "'am broadcast -a com.android.systemui.demo -e command clock -e hhmm 0941'",
            "adb -s emulator-5580 exec-out screencap -p",
            "adb -s emulator-5580 exec-out screencap -p",
            p + "'pm clear com.example.samplerecipes'",
            p + "'am start -W -S -n com.example.samplerecipes/.MainActivity --es ScreenshotSeed demo --es "
                "ScreenshotScreen plan --ez Fast true --ei Count 3'",
            # Each tap looks at the keyboard first: one up full screen (landscape) would take the tap.
            p + "'dumpsys input_method'",
            p + "'input tap 970 170'",
            p + "'dumpsys input_method'",
            p + "'input tap 970 170'",
            p + "'input text pasta%sbake'",
            p + "'input keyevent KEYCODE_BACK'",
            p + "'input swipe 540 1500 540 500 250'",
            p + "'am start -W -a android.intent.action.VIEW -d samplerecipes://recipe/demo com.example.samplerecipes'",
            # The keyboard looked at (the screen types, so a keyboard left up would only be a warning).
            p + "'dumpsys input_method'",
            "adb -s emulator-5580 exec-out screencap -p",
        ])
        self.assertTrue(self.run_.matching(r"shell 'uiautomator dump /sdcard/appstores-ui.xml'"))

    def status_bar_device(self, clocks):
        """screencap answers whose top rows follow demo mode's clock (``clocks``: hhmm -> a colour)."""
        current = {"hhmm": "0000"}

        def broadcast(cmd):
            m = re.search(r"-e hhmm (\d{4})", cmd[-1])
            if m:
                current["hhmm"] = m.group(1)
        self.run_.on(ADB + r"shell 'am broadcast", then=broadcast)
        self.run_.on(ADB + r"exec-out screencap -p",
                     out=lambda cmd: kit.png_bytes(1080, 1920, colour=clocks.get(current["hhmm"], (9, 9, 9))))

    def test_a_status_bar_that_follows_demo_modes_clock_is_verified(self):
        self.answers()
        self.status_bar_device({"0941": (10, 10, 10), "1208": (200, 200, 200)})
        drv = adb_driver.AdbDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([]), "en-US")
        self.assertEqual(shot.status_bar, "verified")
        self.assertEqual(shot.warnings, [])

    def test_a_status_bar_that_keeps_changing_is_unverified(self):
        self.answers()
        frames = iter([(1, 1, 1), (1, 1, 1), (2, 2, 2), (2, 2, 2), (3, 3, 3), (3, 3, 3), (4, 4, 4)])
        self.run_.on(ADB + r"exec-out screencap -p",
                     out=lambda cmd: kit.png_bytes(1080, 1920, colour=next(frames, (5, 5, 5))))
        drv = adb_driver.AdbDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([]), "en-US")
        self.assertEqual(shot.status_bar, "unverified")
        self.assertTrue(any("kept changing" in w for w in shot.warnings))

    def test_status_bar_mobile_and_check_off(self):
        self.answers()
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(target={"avd": "Medium_Phone", "statusBarMobile": True, "statusBarCheck": False})
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([]), "en-US")
        self.assertEqual(shot.status_bar, "overridden")
        self.assertTrue(self.run_.matching(r"-e mobile show -e datatype none -e level 4 -e fully true"))
        self.assertEqual(self.run_.matching(r"hhmm 1208"), [])

    def test_android_env_isnt_warned_about_when_args_carry_the_same_keys(self):
        self.answers()
        drv = adb_driver.AdbDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([{"launch": {"env": {"DEMO": "1", "ONLY_ENV": "x"},
                                                               "args": {"DEMO": "1"}}}]), "en-US")
        env_warnings = [w for w in shot.warnings if "environment variables" in w]
        self.assertEqual(len(env_warnings), 1)
        self.assertIn("ONLY_ENV", env_warnings[0])
        self.assertNotIn("DEMO", env_warnings[0])

    def test_avdmanager_is_found_in_a_versioned_cmdline_tools_folder(self):
        sdk = os.path.join(self.tmp, "sdk")
        for v in ("19.0", "23.0", "9.0"):
            kit.write_png(os.path.join(sdk, "cmdline-tools", v, "bin", "avdmanager"), 1, 1)
        saved = dict((k, os.environ.get(k)) for k in ("ANDROID_HOME", "ANDROID_SDK_ROOT"))
        os.environ["ANDROID_HOME"] = sdk
        os.environ.pop("ANDROID_SDK_ROOT", None)
        try:
            drv = adb_driver.AdbDriver(self.options)
            self.assertEqual(drv.avdmanager({}), os.path.join(sdk, "cmdline-tools", "23.0", "bin", "avdmanager"))
            kit.write_png(os.path.join(sdk, "cmdline-tools", "latest", "bin", "avdmanager"), 1, 1)
            self.assertEqual(drv.avdmanager({}), os.path.join(sdk, "cmdline-tools", "latest", "bin", "avdmanager"))
            self.assertEqual(drv.avdmanager({"avdmanager": "/opt/avdmanager"}), "/opt/avdmanager")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_a_dotnet_fast_deployment_apk_is_warned_about(self):
        import zipfile
        fast = os.path.join(self.tmp, "fast.apk")
        with zipfile.ZipFile(fast, "w") as z:
            z.writestr("lib/arm64-v8a/libmonodroid.so", b"x")
            z.writestr("classes.dex", b"x")
        full = os.path.join(self.tmp, "full.apk")
        with zipfile.ZipFile(full, "w") as z:
            z.writestr("lib/arm64-v8a/libmonodroid.so", b"x")
            z.writestr("lib/arm64-v8a/libassemblies.arm64-v8a.blob.so", b"x")
        native = os.path.join(self.tmp, "native.apk")
        with zipfile.ZipFile(native, "w") as z:
            z.writestr("classes.dex", b"x")
        self.assertTrue(adb_driver.fast_deployment_apk(fast))
        self.assertFalse(adb_driver.fast_deployment_apk(full))
        self.assertFalse(adb_driver.fast_deployment_apk(native))
        self.answers()
        drv = adb_driver.AdbDriver(self.options)
        drv.prepare(self.device(app={"package": "com.example.samplerecipes", "activity": ".MainActivity",
                                     "apk": "fast.apk"}), {})
        self.assertTrue(any("EmbedAssembliesIntoApk=true" in w for w in drv.warnings))

    def test_permissions_are_granted_before_launch_and_revoked_after(self):
        self.answers()
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(permissions=["POST_NOTIFICATIONS", "android.permission.CAMERA"])
        drv.prepare(device, {})
        self.assertTrue(self.run_.matching(r"'pm grant com.example.samplerecipes android.permission.POST_NOTIFICATIONS'"))
        drv.reset(device)
        self.assertTrue(self.run_.matching(r"'pm revoke com.example.samplerecipes android.permission.CAMERA'"))

    def test_navigation_mode_is_switched_and_put_back(self):
        self.answers()
        self.run_.on(ADB + r"shell 'cmd overlay list'", out="com.android.internal.systemui.navbar\n"
                     "[x] com.android.internal.systemui.navbar.threebutton\n"
                     "[ ] com.android.internal.systemui.navbar.gestural\n")
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(target={"avd": "Medium_Phone", "navigation": "gesture"})
        drv.prepare(device, {})
        self.assertTrue(self.run_.matching(r"enable-exclusive --category com.android.internal.systemui.navbar.gestural'"))
        drv.reset(device)
        self.assertTrue(self.run_.matching(r"enable-exclusive --category com.android.internal.systemui.navbar.threebutton'"))

    def test_an_app_file_goes_into_the_apps_data_through_run_as(self):
        self.answers()
        seed = kit.write_png(os.path.join(self.tmp, "seed", "app.db"), 1, 1)
        drv = adb_driver.AdbDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([{"appFile": {"file": "seed/app.db",
                                                                "into": {"ios": "Library/x.db", "android": "cache/data/app.db"}}}]),
                              "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertTrue(self.run_.matching(r"push .*/seed/app.db /data/local/tmp/appstores-app.db"))
        (copy,) = self.run_.matching(r"run-as com.example.samplerecipes")
        self.assertIn("cp /data/local/tmp/appstores-app.db cache/data/app.db", copy)
        self.assertIn("rm -f cache/data/app.db cache/data/app.db-wal", copy)
        self.run_.on(r"run-as", out="run-as: package not debuggable: com.example.samplerecipes", code=1)
        shot = drv.run_screen(device, self.screen([{"appFile": {"file": "seed/app.db", "into": "files/app.db"}}],
                                                  sid="recipe"), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("debuggable", shot.reason)

    def test_the_dry_run_shows_the_display_size_a_real_run_sets(self):
        self.answers()
        base.DRY_RUN = True
        drv = adb_driver.AdbDriver(self.options)
        drv.prepare(self.device(target={"serial": "emulator-5580"}), {})
        self.assertTrue(any("wm size 1080x1920" in l for l in self.hooks.log))

    def test_a_missing_log_folder_isnt_taken_for_a_missing_emulator(self):
        log = os.path.join(self.tmp, "not-yet", "emulator.log")
        proc = base.subprocess_spawner([sys.executable, "-c", "print('booted')"], log_path=log)
        proc.wait(timeout=30)
        with open(log) as f:
            self.assertIn("booted", f.read())

    def test_an_element_that_never_appears_is_a_missed_shot(self):
        self.answers()
        drv = adb_driver.AdbDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([{"tap": {"text": "Nowhere", "timeout": 3}}]), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("Nowhere", shot.reason)
        self.assertEqual(self.run_.matching(r"input tap"), [])

    def test_reset_puts_everything_back_and_stops_the_emulator_it_started(self):
        self.answers()
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(appearance="dark")
        drv.prepare(device, {})
        drv.run_screen(device, self.screen([{"launch": {}}]), "de-DE")
        start = len(self.run_.lines)
        self.assertEqual(drv.reset(device), [])
        p = "adb -s emulator-5580 shell "
        self.assertEqual(self.run_.lines[start:], [
            p + "'am broadcast -a com.android.systemui.demo -e command exit'",
            p + "'settings delete global sysui_demo_allowed'",
            p + "'cmd uimode night no'",
            p + "'cmd locale set-app-locales com.example.samplerecipes'",
            p + "'settings put global window_animation_scale 1.0'",
            p + "'settings put global transition_animation_scale 1.0'",
            p + "'settings put global animator_duration_scale 1.0'",
            p + "'wm density reset'",
            p + "'wm size reset'",
            p + "'am force-stop com.example.samplerecipes'",
            "adb -s emulator-5580 emu kill",
        ])

    def test_a_persons_device_is_used_as_it_is_and_never_stopped(self):
        self.answers(connected="R5EXAMPLE01\tdevice\n")
        ADB_P = "adb -s R5EXAMPLE01 "
        self.run_.on(r"^adb -s R5EXAMPLE01 shell 'getprop sys.boot_completed'", out="1\n")
        self.run_.on(r"^adb -s R5EXAMPLE01 shell 'getprop ro.build.version.sdk'", out="35\n")
        self.run_.on(r"^adb -s R5EXAMPLE01 shell 'wm size'$", out="Physical size: 1080x1920\n")
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(target={"serial": "R5EXAMPLE01"})
        drv.prepare(device, {})
        drv.reset(device)
        self.assertEqual(self.hooks.spawned, [])
        self.assertEqual(self.run_.matching(r"emu kill|wm size 1080x1920|avdmanager"), [])
        self.assertTrue(self.run_.matching(ADB_P + "shell 'settings put global window_animation_scale 1.0'"))

    def test_a_missing_serial_fails_prepare(self):
        self.answers(connected="")
        drv = adb_driver.AdbDriver(self.options)
        with self.assertRaises(base.DriverError):
            drv.prepare(self.device(target={"serial": "R5EXAMPLE01"}), {})

    def test_its_own_avd_is_created_and_deleted_with_cleanup(self):
        self.answers()
        self.options.cleanup = True
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(target={"systemImage": "system-images;android-36;google_apis;arm64-v8a",
                                     "profile": "medium_phone"})
        drv.prepare(device, {})
        drv.reset(device)
        self.assertTrue(self.run_.matching(r"^avdmanager create avd -n appstores-android-phone -k "
                                           r"'system-images;android-36;google_apis;arm64-v8a' -d medium_phone$"))
        self.assertEqual(self.hooks.spawned[0].split()[:3], ["emulator", "-avd", "appstores-android-phone"])
        self.assertTrue(self.run_.matching(r"^avdmanager delete avd -n appstores-android-phone$"))

    def test_text_adb_cannot_type_fails_plainly(self):
        with self.assertRaises(base.StepFailed):
            adb_driver.input_text("Spätzle")
        self.assertEqual(adb_driver.input_text("50% off"), "50\\%%soff")
        self.assertEqual(adb_driver.demo_clock("2026-06-01T09:41:00"), "0941")


class UiAutomatorTests(AdbCase):
    def test_it_changes_nothing_on_the_device(self):
        self.answers(connected="R5EXAMPLE01\tdevice\n")
        self.run_.on(r"^adb -s R5EXAMPLE01 exec-out cat", out=UI_XML)
        self.run_.on(r"^adb -s R5EXAMPLE01 exec-out screencap -p", out=kit.png_bytes(1080, 1920))
        drv = uia_driver.UiAutomatorDriver(self.options)
        device = self.device(driver="uiautomator", target={"serial": "R5EXAMPLE01"})
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([{"tap": {"label": "Search recipes"}}]), "de-DE")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(shot.status_bar, "none")
        drv.reset(device)
        self.assertEqual(self.run_.matching(r"wm |uimode|locale|demo|settings put|install"), [])
        self.assertTrue(self.run_.matching(r"shell 'input tap 970 170'"))
        self.assertTrue(any("leaves the status bar" in w for w in drv.warnings))

    def test_it_cannot_launch(self):
        drv = uia_driver.UiAutomatorDriver(self.options)
        shot = drv.run_screen(self.device(), self.screen([{"launch": {}}]), "en-US")
        self.assertEqual(shot.status, "skipped")


# -- chrome --------------------------------------------------------------------------------------------------

class FakeChrome(object):
    """Records DevTools calls; answers finds from ``elements`` and screenshots with a PNG of ``size``."""

    def __init__(self, size=(1290, 2796), elements=None):
        self.calls = []
        self.size = size
        self.elements = elements or {}
        self.closed = False
        self.started = False

    def start(self):
        self.started = True

    def close(self):
        self.closed = True

    def wait_event(self, method, session_id=None, predicate=None, timeout=30):
        return {"name": "load"}

    def call(self, method, params=None, session_id=None, timeout=30):
        self.calls.append((method, params or {}))
        if method == "Browser.getVersion":
            return {"userAgent": "Mozilla/5.0 HeadlessChrome/140.0.0.0 Safari/537.36"}
        if method == "Target.createTarget":
            return {"targetId": "T1"}
        if method == "Target.attachToTarget":
            return {"sessionId": "S1"}
        if method == "Page.navigate":
            return {"frameId": "F", "loaderId": "L1"}
        if method == "Page.captureScreenshot":
            return {"data": base64.b64encode(kit.png_bytes(*self.size)).decode("ascii")}
        if method == "Runtime.evaluate":
            expr = params["expression"]
            if '"finder"' in expr:
                q = json.loads(expr[expr.rindex("({") + 1:-1])
                hit = self.elements.get((q["finder"], q["value"]))
                return {"result": {"value": hit}}
            return {"result": {"value": True}}
        return {}

    def methods(self):
        return [m for m, _ in self.calls]


class ChromeTests(DriverCase):
    def setUp(self):
        DriverCase.setUp(self)
        self.fake = FakeChrome(elements={("id", "search"): {"x": 200, "y": 40, "width": 40, "height": 40},
                                         ("text", "This week"): {"x": 100, "y": 100, "width": 80, "height": 20}})
        saved = chrome_driver.CHROME_FACTORY
        chrome_driver.CHROME_FACTORY = lambda: self.fake
        self.addCleanup(setattr, chrome_driver, "CHROME_FACTORY", saved)

    def device(self, **kw):
        d = DriverCase.device(self, id="web-phone", platform="ios", driver="chrome", width=1290, height=2796,
                              app={}, target={"scale": 3})
        d.update(kw)
        return d

    def test_a_page_at_the_device_size_with_locale_and_appearance(self):
        drv = chrome_driver.ChromeDriver(self.options)
        device = self.device(appearance="dark")
        drv.prepare(device, {"app": {"web": {"url": "http://localhost:8080/app"}}})
        shot = drv.run_screen(device, self.screen([
            {"launch": {"args": {"ScreenshotScreen": "plan"}}},
            {"wait": {"text": "This week"}},
            {"tap": {"id": "search"}},
            {"type": {"text": "pasta"}},
            {"scroll": {"direction": "down"}},
            {"url": "/recipes/demo"}]), "de-DE")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(png.info(shot.path)[1:3], (1290, 2796))
        calls = dict((m, p) for m, p in self.fake.calls)
        self.assertEqual(calls["Emulation.setDeviceMetricsOverride"],
                         {"width": 430, "height": 932, "deviceScaleFactor": 3.0, "mobile": True})
        self.assertEqual(calls["Emulation.setUserAgentOverride"],
                         {"userAgent": "Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36", "acceptLanguage": "de-DE"})
        self.assertIn({"name": "prefers-color-scheme", "value": "dark"},
                      calls["Emulation.setEmulatedMedia"]["features"])
        navs = [p["url"] for m, p in self.fake.calls if m == "Page.navigate"]
        self.assertEqual(navs, ["http://localhost:8080/app?ScreenshotSeed=demo&ScreenshotScreen=plan",
                                "http://localhost:8080/recipes/demo"])
        mouse = [p for m, p in self.fake.calls if m == "Input.dispatchMouseEvent"]
        self.assertEqual([(p["type"], p["x"], p["y"]) for p in mouse],
                         [("mouseMoved", 200, 40), ("mousePressed", 200, 40), ("mouseReleased", 200, 40)])
        self.assertIn(("Input.insertText", {"text": "pasta"}), self.fake.calls)
        drv.reset(device)
        self.assertTrue(self.fake.closed)

    def test_only_this_machines_pages(self):
        drv = chrome_driver.ChromeDriver(self.options)
        with self.assertRaises(base.NotLocal):
            drv.prepare(self.device(), {"app": {"web": {"url": "https://example.com/"}}})
        drv = chrome_driver.ChromeDriver(self.options)
        device = self.device()
        drv.prepare(device, {"app": {"web": {"url": "http://127.0.0.1:5173/"}}})
        shot = drv.run_screen(device, self.screen([{"url": "https://example.org/elsewhere"}]), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("only to this machine", shot.reason)
        self.assertNotIn("https://example.org/elsewhere", [p.get("url") for m, p in self.fake.calls])

    def test_a_scale_that_does_not_divide_is_refused(self):
        drv = chrome_driver.ChromeDriver(self.options)
        with self.assertRaises(base.DriverError):
            drv.prepare(self.device(width=1290, height=2797), {})

    def test_an_element_that_never_appears(self):
        drv = chrome_driver.ChromeDriver(self.options)
        device = self.device()
        drv.prepare(device, {"app": {"web": {"url": "http://localhost:8080/"}}})
        shot = drv.run_screen(device, self.screen([{"tap": {"css": "#nope", "timeout": 2}}]), "en-US")
        self.assertEqual(shot.status, "missed")


# -- macos ---------------------------------------------------------------------------------------------------

class MacOSTests(DriverCase):
    def device(self, **kw):
        d = DriverCase.device(self, id="mac", platform="macos", driver="macos", width=2880, height=1800,
                              app={"bundleId": "com.example.samplerecipes", "app": "build/Sample Recipes.app"},
                              target={})
        d.update(kw)
        return d

    def setUp(self):
        DriverCase.setUp(self)
        os.makedirs(os.path.join(self.tmp, "build", "Sample Recipes.app"))
        self.running = [False]
        self.run_.on(r"is running", then=None, out="false")
        self.run_.on(r"^osascript -l JavaScript", out=json.dumps([
            {"id": 4242, "owner": "Sample Recipes", "pid": 7, "name": "", "bounds":
             {"X": 0, "Y": 40, "Width": 1440, "Height": 900}}]))
        self.run_.on(r"^screencapture ", write_png=(2880, 1800, {"color_type": 6}))

    def test_launch_sizes_the_window_and_captures_it_without_shadow(self):
        drv = macos_driver.MacOSDriver(self.options)
        device = self.device(appearance="dark")
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([{"launch": {"args": {"ScreenshotScreen": "plan"},
                                                               "env": {"DEMO": "1"}}}]), "de-DE")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertTrue(self.run_.matching(
            r"^open -n --env DEMO=1 -a '.*/build/Sample Recipes.app' --args -ScreenshotSeed demo -ScreenshotScreen plan "
            r"-AppleLanguages '\(de-DE\)' -AppleLocale de_DE -AppleInterfaceStyle Dark$"))
        self.assertTrue(self.run_.matching(r"set size of window 1 to \{1440, 900\}"))
        self.assertTrue(self.run_.matching(r"^screencapture -x -o -l4242 .*/de-DE/mac/plan.png$"))
        self.run_.on(r"is running", out="true")
        self.run_.on(r"to quit", then=lambda cmd: self.run_.on(r"is running", out="false"))
        drv.reset(device)
        self.assertTrue(self.run_.matching(r'tell application id "com.example.samplerecipes" to quit'))

    def test_a_running_copy_is_the_persons_and_is_refused(self):
        self.run_.on(r"is running", out="true")
        drv = macos_driver.MacOSDriver(self.options)
        with self.assertRaises(base.DriverError) as c:
            drv.prepare(self.device(), {})
        self.assertIn("already running", str(c.exception))
        self.assertEqual(self.run_.matching(r"^open "), [])

    def test_tap_by_id_clicks_through_accessibility(self):
        drv = macos_driver.MacOSDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        self.run_.on(r"(?s)AXIdentifier.*set p to position", out="10,20,30,40")
        self.run_.on(r"(?s)AXIdentifier.*click e", out="clicked")
        shot = drv.run_screen(device, self.screen([{"launch": {}}, {"tap": {"id": "search"}},
                                                   {"type": {"text": "pasta"}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertTrue(self.run_.matching(r'keystroke "pasta"'))


# -- through capture.py: reset happens in finally ------------------------------------------------------------

class CaptureWithSimctlTests(DriverCase):
    def test_reset_runs_after_a_failed_shot_and_the_report_says_why(self):
        self.run_.on(r"simctl list devices -j", out=json.dumps({"devices": {}}))
        self.run_.on(r"simctl list devicetypes -j", out=json.dumps(DEVICETYPES))
        self.run_.on(r"simctl list runtimes -j", out=json.dumps(RUNTIMES))
        self.run_.on(r"simctl create ", out=UDID + "\n")
        self.run_.on(r"simctl status_bar \S+ list", out="Time: 9:41")
        self.run_.on(r"simctl launch", code=1, err="no such app")
        plan = kit.sample_plan([{"id": "iphone-6.9", "platform": "ios", "driver": "simctl", "width": 1320,
                                 "height": 2868, "target": {"deviceType": "iPhone 17 Pro Max"}}],
                               [{"id": "plan", "steps": [{"launch": {}}]}, {"id": "recipe", "steps": [{"launch": {}}]}])
        path = kit.write_plan(self.tmp, plan)
        saved = capture.log
        capture.log = lambda m: None
        self.addCleanup(setattr, capture, "log", saved)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(capture.main(["--plan", path]), 1)
        launch = self.run_.index(r"simctl launch")
        self.assertGreater(self.run_.index(r"status_bar \S+ clear", launch), launch)
        self.assertGreater(self.run_.index(r"simctl shutdown", launch), launch)
        with open(os.path.join(self.tmp, "captures", "capture-report.json")) as f:
            report = json.load(f)
        self.assertEqual([s["status"] for s in report["shots"]], ["missed", "missed"])
        self.assertIn("no such app", report["shots"][0]["reason"])
        self.assertIn("not attempted", report["shots"][1]["reason"])
        self.assertEqual(len(self.run_.matching(r"simctl launch")), 1)


def tearDownModule():
    kit.assert_no_residue()


if __name__ == "__main__":
    unittest.main()
