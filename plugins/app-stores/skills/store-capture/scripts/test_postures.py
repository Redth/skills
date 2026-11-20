"""Tests for foldables and the keyboard: the ``posture`` setting and step on Android emulators and devices (the
emulator's console, ``cmd device_state``) and on the iPhone Duo simulator (DevFlow's fold control), what a fold
undoes (the lock screen, ``wm size`` on the other display, demo mode, the display captured), ``hideKeyboard`` and
``verify``'s keyboard check, and the XPath every tree-reading driver evaluates.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here runs a real tool, reaches
a network or waits: a fake foldable answers the commands.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture_testkit as kit  # noqa: E402
from drivers import adb as adb_driver  # noqa: E402
from drivers import base  # noqa: E402
from drivers import hosted  # noqa: E402
from drivers import simctl as simctl_driver  # noqa: E402

INNER = "4619827259835644672"
OUTER = "4619827551948147201"
PHYSICAL = {INNER: "2076x2152", OUTER: "1080x2424"}
STATES = ("Supported states: [\n"
          "  DeviceState{identifier=0, name='CLOSED', app_accessible=true},\n"
          "  DeviceState{identifier=1, name='HALF_OPENED', app_accessible=true},\n"
          "  DeviceState{identifier=2, name='OPENED', app_accessible=true},\n"
          "  DeviceState{identifier=3, name='REAR_DISPLAY_MODE', app_accessible=true},\n]\n")
STATE_IDS = {"folded": 0, "half-open": 1, "open": 2}


class FakeFoldable(object):
    """A foldable Android emulator (or, with ``serial``, a real one) behind ``adb``: two physical displays, a
    posture, ``wm size``/``wm density`` overrides kept per display (as Android keeps them), a lock screen that
    comes up on every fold, an on-screen keyboard. Install with ``install(runner)``."""

    def __init__(self, serial="emulator-5580", posture="open", foldable=True, unlockable=True):
        self.serial = serial
        self.posture = posture
        self.foldable = foldable
        self.unlockable = unlockable
        self.sizes = {}
        self.densities = {}
        self.keyguard = False
        self.keyboard = False
        self.navigated_back = 0
        self.hinge = None
        self.override_state = None

    def active(self):
        return OUTER if self.posture == "folded" else INNER

    def size_now(self):
        return self.sizes.get(self.active()) or PHYSICAL[self.active()]

    def install(self, runner):
        runner.on(r".", out=self.answer)
        return self

    def answer(self, cmd):
        line = " ".join(cmd)
        if line.endswith("adb devices"):
            # An emulator the driver starts isn't listed before it starts (so it takes the first free port).
            listed = "" if self.serial.startswith("emulator-") else "%s\tdevice\n" % self.serial
            return "List of devices attached\n" + listed
        if " emu " in line:
            return self.console(cmd[cmd.index("emu") + 1:])
        if "screencap" in line:
            return self.screencap(cmd)
        if " shell " not in " %s " % line or "shell" not in cmd:
            return ""
        return self.shell(cmd[-1])

    def console(self, args):
        if args[:1] == ["fold"]:
            self.posture, self.keyguard = "folded", True
        elif args[:1] == ["unfold"]:
            self.posture, self.keyguard = "open", True
        elif args[:2] == ["posture", "2"]:
            self.posture = "half-open"
        elif args[:3] == ["sensor", "set", "hinge-angle0"] and len(args) > 3:
            self.hinge = args[3]
        elif args[:2] == ["avd", "name"]:
            return "not-this-one\nOK\n"
        return "OK\n"

    def screencap(self, cmd):
        w, h = (int(v) for v in self.size_now().split("x"))
        if "-d" in cmd:
            if cmd[cmd.index("-d") + 1] != self.active():
                w, h = 32, 32       # the display that's off: not the picture wanted
            return kit.png_bytes(w, h)
        return (b"[Warning] Multiple displays were found, but no display id was specified! Defaulting to the first "
                b"display found.\n" + kit.png_bytes(w, h))

    def shell(self, text):
        if text == "getprop sys.boot_completed":
            return "1\n"
        if text == "getprop ro.build.version.sdk":
            return "36\n"
        if text == "cmd device_state print-states":
            return STATES if self.foldable else "Supported states: [\n  DeviceState{identifier=0, name='DEFAULT'},\n]\n"
        if text == "cmd device_state print-state":
            return "%d\n" % STATE_IDS[self.posture] if self.foldable else "0\n"
        m = re.match(r"cmd device_state state (\S+)$", text)
        if m:
            if m.group(1) == "reset":
                self.override_state = None
                self.posture = "open"
            else:
                self.override_state = int(m.group(1))
                self.posture = dict((v, k) for k, v in STATE_IDS.items())[self.override_state]
                self.keyguard = True
            return ""
        if text == "dumpsys SurfaceFlinger --display-id":
            if not self.foldable:
                return "Display 4619827259835644672 (HWC display 0): port=0 displayName=\"EMU_display_0\"\n"
            return ("Display %s (HWC display 0): port=0 displayName=\"EMU_display_0\"\n"
                    "Display %s (HWC display 1): port=1 displayName=\"EMU_display_1\"\n" % (INNER, OUTER))
        if text == "dumpsys display":
            other = INNER if self.active() == OUTER else OUTER
            return ("  mViewports=[DisplayViewport{type=INTERNAL, valid=true, isActive=true, displayId=0, "
                    "uniqueId='local:%s', physicalPort=1}, DisplayViewport{type=INTERNAL, valid=true, isActive=false, "
                    "displayId=1, uniqueId='local:%s', physicalPort=0}]\n" % (self.active(), other))
        if text == "wm size":
            out = "Physical size: %s\n" % PHYSICAL[self.active()]
            if self.active() in self.sizes:
                out += "Override size: %s\n" % self.sizes[self.active()]
            return out
        m = re.match(r"wm size (\S+)$", text)
        if m:
            if m.group(1) == "reset":
                self.sizes.pop(self.active(), None)
            else:
                self.sizes[self.active()] = m.group(1)
            return ""
        if text == "wm density":
            out = "Physical density: 390\n"
            if self.active() in self.densities:
                out += "Override density: %s\n" % self.densities[self.active()]
            return out
        m = re.match(r"wm density (\S+)$", text)
        if m:
            if m.group(1) == "reset":
                self.densities.pop(self.active(), None)
            else:
                self.densities[self.active()] = m.group(1)
            return ""
        if text == "wm dismiss-keyguard":
            if self.unlockable:
                self.keyguard = False
            return ""
        if text == "dumpsys window":
            return "    isKeyguardShowing=%s\n" % ("true" if self.keyguard else "false")
        if text == "dumpsys input_method":
            return "      mImeWindowVis=%d\n      mInputShown=%s\n  mIsInputViewShown=true\n" % (
                3 if self.keyboard else 0, "true" if self.keyboard else "false")
        if text == "input keyevent KEYCODE_BACK":
            if self.keyboard:
                self.keyboard = False
            else:
                self.navigated_back += 1
            return ""
        if text.startswith("am start"):
            return "Status: ok\n"
        if text.startswith("settings get global"):
            return "1.0\n"
        if text == "cmd uimode night":
            return "Night mode: no\n"
        return ""


class Case(unittest.TestCase):
    def setUp(self):
        self.hooks = kit.Hooks()
        self.addCleanup(self.hooks.restore)
        self.run_ = self.hooks.runner
        self.tmp = tempfile.mkdtemp(prefix="capture-postures-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.options = base.Options(plan_dir=self.tmp, workdir=os.path.join(self.tmp, "work"))
        self.saved_env = dict(os.environ)
        os.environ.pop("ANDROID_HOME", None)
        os.environ.pop("ANDROID_SDK_ROOT", None)
        self.addCleanup(self._env_back)

    def _env_back(self):
        os.environ.clear()
        os.environ.update(self.saved_env)

    def device(self, **kw):
        d = {"id": "fold-outer", "platform": "android", "driver": "adb", "width": 1080, "height": 1920,
             "locales": ["en-US"], "appearance": "light", "clock": "09:41", "statusBar": "clean", "seed": None,
             "flatten": "#000000", "posture": None,
             "app": {"package": "com.example.samplerecipes", "activity": ".MainActivity"},
             "target": {"avd": "appstores-fold", "density": 420, "statusBarCheck": False}}
        d.update(kw)
        return d

    def screen(self, steps, **kw):
        s = {"id": "plan", "steps": steps, "locales": ["en-US"], "appearance": None, "clock": None,
             "statusBar": None, "seed": None, "flatten": None, "posture": None}
        s.update(kw)
        return s

    def assertInOrder(self, patterns, start=0):
        at = start
        for p in patterns:
            i = self.run_.index(p, at)
            self.assertGreaterEqual(i, 0, "no command matching %r after #%d in:\n%s" % (p, at, "\n".join(self.run_.lines)))
            at = i + 1


ADB = r"^adb -s emulator-5580 "


class AndroidFoldTests(Case):
    def test_a_folded_device_is_folded_unlocked_then_laid_out_on_the_cover_display(self):
        fold = FakeFoldable().install(self.run_)
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(posture="folded")
        drv.prepare(device, {})
        self.assertInOrder([
            ADB + r"emu fold$",
            ADB + r"shell 'cmd device_state print-state'$",
            ADB + r"shell 'input keyevent KEYCODE_WAKEUP'$",
            ADB + r"shell 'wm dismiss-keyguard'$",
            ADB + r"shell 'dumpsys display'$",
            ADB + r"shell 'wm size 1080x1920'$",
            ADB + r"shell 'wm density 420'$",
        ])
        # The size went to the cover display, the one in use; the inner display was never touched.
        self.assertEqual(fold.sizes, {OUTER: "1080x1920"})
        self.assertFalse(fold.keyguard)
        shot = drv.run_screen(device, self.screen([{"launch": {}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertTrue(self.run_.matching(ADB + r"exec-out screencap -p -d %s$" % OUTER))
        self.assertEqual(png_size(shot.path), (1080, 1920))
        drv.reset(device)
        self.assertEqual((fold.posture, fold.sizes, fold.densities), ("open", {}, {}))

    def test_a_posture_change_lays_out_again_and_cleans_the_status_bar_again(self):
        fold = FakeFoldable().install(self.run_)
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(id="fold", posture="open", target={"avd": "appstores-fold", "statusBarCheck": False})
        drv.prepare(device, {})
        self.assertEqual(fold.sizes, {INNER: "1080x1920"})
        drv.run_screen(device, self.screen([]), "en-US")
        enters = len(self.run_.matching(r"-e command enter"))
        self.assertEqual(enters, 2)   # the first time after a boot: entered twice
        start = len(self.run_.lines)
        shot = drv.run_screen(device, self.screen([{"launch": {}}], sid="cover", posture="folded"), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        # wm size didn't carry across the fold: set again on the cover display; demo mode entered twice again.
        self.assertEqual(fold.sizes, {INNER: "1080x1920", OUTER: "1080x1920"})
        self.assertEqual(len(self.run_.matching(r"-e command enter")) - enters, 2)
        self.assertInOrder([ADB + r"emu fold$", ADB + r"shell 'wm dismiss-keyguard'$", ADB + r"shell 'wm size 1080x1920'$",
                            r"-e command enter", ADB + r"shell 'am start"], start)
        # Each display's override is put back in the posture it was in use in, then the posture.
        drv.reset(device)
        self.assertEqual((fold.posture, fold.sizes), ("open", {}))
        resets = [l for l in self.run_.lines if "emu fold" in l or "emu unfold" in l or "wm size reset" in l]
        self.assertEqual(resets[-4:], ["adb -s emulator-5580 emu fold", "adb -s emulator-5580 shell 'wm size reset'",
                                       "adb -s emulator-5580 emu unfold", "adb -s emulator-5580 shell 'wm size reset'"])

    def test_half_open_sets_the_posture_and_the_hinge(self):
        fold = FakeFoldable().install(self.run_)
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(id="fold-tabletop", width=1920, height=1080, posture="half-open",
                             target={"avd": "appstores-fold", "hingeAngle": 110})
        drv.prepare(device, {})
        self.assertEqual((fold.posture, fold.hinge), ("half-open", "110"))
        self.assertTrue(self.run_.matching(ADB + r"emu posture 2$"))

    def test_a_posture_step_in_the_middle_of_a_screen(self):
        fold = FakeFoldable().install(self.run_)
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(target={"avd": "appstores-fold"})
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([{"launch": {}}, {"posture": "closed"}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(fold.posture, "folded")
        self.assertEqual(drv.state["posture"], "folded")

    def test_a_real_foldable_uses_device_state_and_is_reset(self):
        fold = FakeFoldable(serial="R5FOLD01", posture="open").install(self.run_)
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(posture="folded", target={"serial": "R5FOLD01"})
        drv.prepare(device, {})
        self.assertTrue(self.run_.matching(r"^adb -s R5FOLD01 shell 'cmd device_state state 0'$"))
        self.assertEqual(self.run_.matching(r" emu "), [], "a real device has no emulator console")
        drv.reset(device)
        self.assertTrue(self.run_.matching(r"^adb -s R5FOLD01 shell 'cmd device_state state reset'$"))
        self.assertEqual((fold.posture, fold.sizes), ("open", {}))

    def test_a_device_that_does_not_fold_says_so(self):
        FakeFoldable(foldable=False).install(self.run_)
        drv = adb_driver.AdbDriver(self.options)
        with self.assertRaises(base.DriverError) as cm:
            drv.prepare(self.device(posture="folded"), {})
        self.assertIn("isn't a foldable", str(cm.exception))

    def test_a_lock_screen_that_stays_is_a_warning(self):
        FakeFoldable(unlockable=False).install(self.run_)
        drv = adb_driver.AdbDriver(self.options)
        drv.prepare(self.device(posture="folded"), {})
        self.assertTrue(any("lock screen is still up" in w for w in drv.warnings))

    def test_screencaps_words_before_the_picture_are_dropped(self):
        FakeFoldable().install(self.run_)
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(target={"avd": "appstores-fold", "display": INNER})
        drv.prepare(device, {})
        drv.display = None
        path = os.path.join(self.tmp, "x.png")
        device["target"] = {"avd": "appstores-fold"}
        drv.screenshot(device, path)
        with open(path, "rb") as f:
            self.assertTrue(f.read().startswith(b"\x89PNG"))

    def test_the_dry_run_shows_the_fold(self):
        lines = []
        base.DRY_RUN = True
        base.LOG = lines.append
        drv = adb_driver.AdbDriver(self.options)
        drv.prepare(self.device(posture="folded", target={"serial": "emulator-5580"}), {})
        self.assertTrue(any("emu fold" in l for l in lines), lines)
        self.assertTrue(any("wm dismiss-keyguard" in l for l in lines), lines)


class KeyboardTests(Case):
    def prepared(self, keyboard):
        fold = FakeFoldable().install(self.run_)
        fold.keyboard = keyboard
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(target={"avd": "appstores-fold", "statusBarCheck": False})
        drv.prepare(device, {})
        return fold, drv, device

    def test_hide_keyboard_presses_back_only_while_the_keyboard_is_up(self):
        fold, drv, device = self.prepared(keyboard=True)
        shot = drv.run_screen(device, self.screen([{"hideKeyboard": True}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertFalse(fold.keyboard)
        shot = drv.run_screen(device, self.screen([{"hideKeyboard": True}], sid="again"), "en-US")
        self.assertEqual(fold.navigated_back, 0, "with the keyboard down, back would have navigated")

    def test_a_screen_that_types_nothing_with_the_keyboard_up_is_a_wrong_state(self):
        fold, drv, device = self.prepared(keyboard=True)
        shot = drv.run_screen(device, self.screen([{"launch": {}}], state="the recipe, nothing being typed"), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertEqual(shot.state_check, "failed")
        self.assertIn("the keyboard is up", shot.reason)
        shot = drv.run_screen(device, self.screen([{"launch": {}}], verify={"keyboard": "any"}), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)

    def test_a_screen_that_types_is_warned_unless_it_asks(self):
        fold, drv, device = self.prepared(keyboard=True)
        self.run_.on(r"exec-out cat /sdcard/appstores-ui.xml", out=UI_XML)
        steps = [{"type": {"id": "amount", "text": "12"}}]
        shot = drv.run_screen(device, self.screen(steps), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertTrue(any("keyboard is up" in w for w in shot.warnings))
        shot = drv.run_screen(device, self.screen(steps, verify=[{"id": "amount"}, {"keyboard": "hidden"}]), "en-US")
        self.assertEqual(shot.status, "missed")
        shot = drv.run_screen(device, self.screen(steps + [{"hideKeyboard": True}],
                                                  verify=[{"id": "amount"}, {"keyboard": "hidden"}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(shot.state_check, "passed")

    def test_a_driver_that_cannot_see_the_keyboard_reports_an_asked_check_unchecked(self):
        class Blind(base.Driver):
            NAME = "blind"
            STEPS = ("wait",)

            def screenshot(self, device, path):
                kit.write_png(path, 10, 10)
        drv = Blind(self.options)
        shot = drv.run_screen(self.device(), self.screen([], verify={"keyboard": "hidden"}), "en-US")
        self.assertEqual(shot.status, "taken")
        self.assertEqual(shot.state_check, "unchecked")
        shot = drv.run_screen(self.device(), self.screen([]), "en-US")
        self.assertEqual(shot.state_check, "none", "the default check is quiet where it can't be made")
        shot = drv.run_screen(self.device(), self.screen([{"hideKeyboard": True}]), "en-US")
        self.assertEqual(shot.status, "skipped")


UI_XML = ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
          '<node index="0" text="" resource-id="" class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">'
          '<node index="0" text="COOKING TIME" resource-id="com.example.samplerecipes:id/title" content-desc="" '
          'class="android.widget.TextView" bounds="[40,200][600,260]"/>'
          '<node index="1" text="12" resource-id="com.example.samplerecipes:id/amount" content-desc="Amount" '
          'class="android.widget.EditText" bounds="[40,300][600,360]"/>'
          '<node index="2" text="  Lemon Pasta for 4 people" resource-id="" content-desc="" '
          'class="android.widget.TextView" bounds="[40,400][1000,460]"/>'
          '</node></hierarchy>')


class XPathTests(unittest.TestCase):
    def setUp(self):
        self.root, _ = base.parse_uiautomator(UI_XML)

    def texts(self, expr):
        return [n.attrib.get("text") for n in base.xpath_all(self.root, expr)]

    def test_the_cross_platform_xpath_from_the_trial_works_on_android(self):
        self.assertEqual(self.texts("//*[contains(@label,'Lemon') or contains(@text,'Lemon')]"),
                         ["  Lemon Pasta for 4 people"])
        el = base.find_xpath(self.root, "//*[contains(@label,'Lemon') or contains(@text,'Lemon')]")
        self.assertEqual(el.center, (520, 430))

    def test_functions_predicates_and_paths(self):
        self.assertEqual(self.texts("//node[starts-with(@resource-id,'com.example') and not(@text='12')]"),
                         ["COOKING TIME"])
        self.assertEqual(self.texts("//node[translate(@text,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"
                                    "='cooking time']"), ["COOKING TIME"])
        self.assertEqual(self.texts("/hierarchy/node/node[last()]"), ["  Lemon Pasta for 4 people"])
        self.assertEqual(self.texts("//node[@class='android.widget.EditText']/../node[1]"), ["COOKING TIME"])
        self.assertEqual(self.texts("(//node[@text!=''])[2]"), ["12"])
        self.assertEqual(self.texts("//node[normalize-space(@text)='Lemon Pasta for 4 people']"),
                         ["  Lemon Pasta for 4 people"])
        self.assertEqual(self.texts("//node[@index=2]"), ["  Lemon Pasta for 4 people"])

    def test_an_xpath_it_cannot_read_is_a_plain_step_failure(self):
        with self.assertRaises(base.StepFailed) as cm:
            base.find_xpath(self.root, "//node[matches(@text,'x')]")
        self.assertIn("isn't one this driver understands", str(cm.exception))


# -- the iPhone Duo -------------------------------------------------------------------------------------------

UDID = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
DUO_TYPE = "com.apple.CoreSimulator.SimDeviceType.iPhone-Duo"
ENUMERATE = """Port:
    Class: DisplayAdapter
    Connected Screens:
    (1) LCD:
        Screen ID: 1
        Screen Type: Integrated
        Pixel Size: {1398, 2034}
    (2) TVOut:
        Screen ID: 2
        Screen Type: TVOut
        Pixel Size: {720, 480}
    (3) LCD-1:
        Screen ID: 3
        Screen Type: Integrated
        Pixel Size: {2007, 2853}
"""


def fold_state(mode, angle, active):
    return {"deviceId": UDID, "platform": "ios", "mode": mode, "hinges": [{"index": 0, "angleDegrees": angle}],
            "displays": [{"id": "1", "name": "LCD", "active": active == "1", "nativeWidth": 1398, "nativeHeight": 2034},
                         {"id": "3", "name": "LCD-1", "active": active == "3", "nativeWidth": 2007,
                          "nativeHeight": 2853}]}


class FakeDuo(object):
    """The iPhone Duo simulator as ``simctl`` and DevFlow's fold control see it."""

    def __init__(self, settle_at=None):
        self.mode = "folded"
        self.angle = 0
        self.settle_at = settle_at
        self.shots = []

    def install(self, runner):
        runner.on(r"simctl list devices -j", out=json.dumps({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-27-2": [
            {"udid": UDID, "name": "appstores-%s" % name, "state": "Booted", "isAvailable": True,
             "deviceTypeIdentifier": DUO_TYPE} for name in ("duo-inner", "duo-outer")]}}))
        runner.on(r"simctl io \S+ enumerate", out=ENUMERATE)
        runner.on(r"simctl status_bar \S+ list", out="Time: 9:41\n")
        runner.on(r"simctl ui \S+ appearance$", out="light\n")
        runner.on(r"simctl io .* screenshot", then=self.screenshot)
        runner.on(r"devflow device fold", out=self.fold)
        return self

    def active(self):
        return "1" if self.mode == "folded" else "3"

    def fold(self, cmd):
        at = cmd.index("fold")
        if cmd[at + 1] == "get":
            return json.dumps(fold_state(self.mode, self.angle, self.active()))
        mode = cmd[at + 2]
        if mode == "partially-folded":
            want = float(cmd[cmd.index("--angle") + 1])
            self.mode, self.angle = "partially-folded", self.settle_at if self.settle_at is not None else want
            if self.settle_at is not None:
                return json.dumps({"error": "Fold change on %s was not confirmed within 60s. Last observed hinges: "
                                            "0=%s degrees" % (UDID, self.settle_at), "type": "FoldVerificationTimeout"})
        else:
            self.mode, self.angle = mode, 0 if mode == "folded" else 180
        return json.dumps({"requestedMode": mode, "state": fold_state(self.mode, self.angle, self.active())})

    def screenshot(self, cmd):
        display = [a.split("=", 1)[1] for a in cmd if a.startswith("--display=")]
        self.shots.append(display[0] if display else None)
        if not display:
            raise AssertionError("the Duo needs --display (simctl says Invalid argument without one)")
        w, h = (1398, 2034) if display[0] == "1" else (2853, 2007) if self.mode != "folded" else (2007, 2853)
        kit.write_png(cmd[-1], w, h)


class DuoTests(Case):
    def device(self, **kw):
        d = {"id": "duo-inner", "platform": "ios", "driver": "simctl", "width": 2853, "height": 2007,
             "locales": ["en-US"], "appearance": "light", "clock": "09:41", "statusBar": "clean", "seed": None,
             "flatten": "#000000", "posture": "open", "app": {"bundleId": "com.example.samplerecipes"},
             "target": {"deviceType": "iPhone Duo", "localeScope": "app"}}
        d.update(kw)
        return d

    def test_opening_the_duo_captures_its_inner_display_and_folds_it_back_after(self):
        duo = FakeDuo().install(self.run_)
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([{"launch": {}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertTrue(self.run_.matching(
            r"^maui devflow device fold set unfolded --timeout 60 --udid %s --experimental --json$" % UDID))
        self.assertEqual(duo.shots[-1], "3")
        self.assertEqual(png_size(shot.path), (2853, 2007), "the inner display is landscape: 2853x2007")
        self.assertIn(3, self.hooks.time.slept, "a moment for the app's scene to move to the inner display")
        self.assertEqual(drv.source(device)["posture"], "open")
        drv.reset(device)
        self.assertEqual(duo.mode, "folded")
        self.assertTrue(self.run_.index(r"fold set folded") > self.run_.index(r"fold set unfolded"))

    def test_already_folded_is_left_as_it_is(self):
        duo = FakeDuo().install(self.run_)
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device(id="duo-outer", width=1398, height=2034, posture="folded")
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(shot.source.get("posture"), "folded")
        self.assertEqual(self.run_.matching(r"fold set"), [])
        self.assertEqual(duo.shots, ["1"])
        drv.reset(device)
        self.assertEqual(self.run_.matching(r"fold set"), [], "nothing to put back")

    def test_without_a_posture_the_screen_of_the_devices_size_is_captured(self):
        duo = FakeDuo().install(self.run_)
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device(id="duo-outer", width=1398, height=2034, posture=None)
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(duo.shots, ["1"])
        self.assertEqual(self.run_.matching(r"devflow device fold"), [])

    def test_a_half_open_hinge_a_few_degrees_off_is_accepted_with_a_warning(self):
        FakeDuo(settle_at=85.4).install(self.run_)
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device(posture="half-open")
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertTrue(any("settled at 85 degrees" in w for w in drv.warnings))
        self.assertTrue(self.run_.matching(r"fold set partially-folded --timeout 60 --angle 90 "))

    def test_a_half_open_hinge_far_off_is_a_missed_shot(self):
        FakeDuo(settle_at=40).install(self.run_)
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device(posture="half-open")
        drv.prepare(device, {})
        shot = drv.run_screen(device, self.screen([]), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("half-open posture", shot.reason)

    def test_no_fold_control_says_how_to_get_one(self):
        FakeDuo().install(self.run_)
        self.run_.on(r"^maui ", raises=FileNotFoundError())
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device()
        drv.prepare(device, {})
        with self.assertRaises(base.ToolMissing) as cm:
            drv.run_screen(device, self.screen([]), "en-US")
        self.assertIn("dotnet tool install -g Microsoft.Maui.Cli", str(cm.exception))

    def test_the_fold_command_can_be_named(self):
        FakeDuo().install(self.run_)
        self.run_.on(r"^dnx ", out=json.dumps({"state": fold_state("unfolded", 180, "3")}))
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device(target={"deviceType": "iPhone Duo", "foldCli": ["dnx", "maui", "devflow"]})
        drv.prepare(device, {})
        drv.run_screen(device, self.screen([]), "en-US")
        self.assertTrue(self.run_.matching(r"^dnx maui devflow device fold set unfolded "))

    def test_a_coresimulator_hiccup_installing_is_tried_once_more(self):
        FakeDuo().install(self.run_)
        app = os.path.join(self.tmp, "Sample.app")
        os.makedirs(app)
        # The first install meets "server died"; the next one works.
        self.run_.on(r"simctl install ", code=149, err="An error was encountered processing the command "
                     "(domain=NSMachErrorDomain, code=-308): Mach error -308 - (ipc/mig) server died",
                     then=lambda cmd: self.run_.on(r"simctl install "))
        drv = simctl_driver.SimctlDriver(self.options)
        device = self.device(app={"bundleId": "com.example.samplerecipes", "app": app})
        drv.prepare(device, {})
        self.assertEqual(len(self.run_.matching(r"simctl install ")), 2)
        self.assertTrue(any("tried again" in w for w in drv.warnings))
        self.assertIn(5, self.hooks.time.slept)

    def test_an_install_that_keeps_failing_reports_its_own_error(self):
        FakeDuo().install(self.run_)
        app = os.path.join(self.tmp, "Sample.app")
        os.makedirs(app)
        self.run_.on(r"simctl install ", code=149, err="Mach error -308 - (ipc/mig) server died")
        drv = simctl_driver.SimctlDriver(self.options)
        with self.assertRaises(base.CommandError) as cm:
            drv.prepare(self.device(app={"bundleId": "com.example.samplerecipes", "app": app}), {})
        self.assertIn("server died", str(cm.exception))
        self.assertEqual(len(self.run_.matching(r"simctl install ")), 2, "once more, not forever")
        self.run_.on(r"simctl install ", code=1, err="No such file")
        before = len(self.run_.matching(r"simctl install "))
        with self.assertRaises(base.CommandError):
            simctl_driver.SimctlDriver(self.options).prepare(
                self.device(app={"bundleId": "com.example.samplerecipes", "app": app}), {})
        self.assertEqual(len(self.run_.matching(r"simctl install ")) - before, 1, "an ordinary failure isn't retried")


class HostedPostureTests(Case):
    def test_a_hosted_driver_folds_through_its_host_once(self):
        fold = FakeFoldable().install(self.run_)

        class Hosted(hosted.HostedDriver):
            NAME = "hosted"
            PLATFORMS = ("android",)
            STEPS = ("wait", "posture")

        drv = Hosted(self.options)
        device = self.device(posture="folded")
        drv.prepare(device, {})
        self.assertEqual(fold.posture, "folded")
        shot = drv.run_screen(device, self.screen([]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(len(self.run_.matching(r"emu fold$")), 1, "the host folded it preparing; not again")
        shot = drv.run_screen(device, self.screen([{"posture": "open"}], sid="inner"), "en-US")
        self.assertEqual(fold.posture, "open")

    def test_a_host_that_cannot_fold_skips_the_screen(self):
        class NoFold(base.Driver):
            NAME = "nofold"
            STEPS = ("wait",)

        class Hosted(hosted.HostedDriver):
            NAME = "hosted"
            PLATFORMS = ("android",)
            STEPS = ("wait", "posture")

            def host(self, device):
                self._host = self._host or NoFold(self.options)
                self._host_name = "nofold"
                return self._host
        drv = Hosted(self.options)
        shot = drv.run_screen(self.device(posture="folded"), self.screen([]), "en-US")
        self.assertEqual(shot.status, "skipped")
        self.assertIn("posture", shot.reason)


def png_size(path):
    from appstores_lib import png
    meta = png.info(path)
    return meta.width, meta.height


class HygieneTests(unittest.TestCase):
    def test_nothing_is_left_beside_the_scripts(self):
        self.assertEqual(kit.stray_folders(), [])


def tearDownModule():
    kit.assert_no_residue()


if __name__ == "__main__":
    unittest.main()
