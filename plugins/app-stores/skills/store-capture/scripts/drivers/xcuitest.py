"""The ``xcuitest`` driver: the app's own XCUITest screenshot tests, run with ``xcodebuild test
-only-testing:``, their screenshots exported from the result bundle with ``xcrun xcresulttool export
attachments``.

A screen's ``flow`` names the test (``StoreShotsUITests/StoreShots/testPlan``, or a class or a whole target) or is
``{"test": "…", "attachment": "plan"}``. The test reaches the screen and attaches a full-screen picture::

    let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
    shot.name = "plan"            // the screen id (or the flow's "attachment")
    shot.lifetime = .keepAlways
    add(shot)

One test run serves every screen that names it (per locale and device): each screen takes the attachment named
after it. The test gets the run's settings as environment variables (``xcodebuild`` passes ``TEST_RUNNER_<NAME>``
to the test runner as ``<NAME>``): ``ScreenshotSeed``, ``APPSTORES_LOCALE``, ``APPSTORES_SCREEN`` (the first
screen that asked), ``APPSTORES_DEVICE``; pass them on to the app's ``launchArguments``/``launchEnvironment``.
The locale is also xcodebuild's ``-testLanguage``/``-testRegion``.

The simulator (create ``appstores-<device id>``, boot, install, appearance, the clean status bar, the device's
locale) is the ``simctl`` host's; a Mac target runs on ``platform=macOS`` with no host.

Target settings: ``project`` or ``workspace``, ``scheme`` (required), ``testPlan``, ``configuration``,
``xctestrun`` (run ``test-without-building`` against a built ``.xctestrun`` instead), ``destination`` (instead
of the host's simulator), ``testTimeout`` (seconds, default 1800), plus the host's (``deviceType``, ``runtime``…).
"""

from __future__ import annotations

import os
import re
import shutil

from . import base
from .hosted import HostedDriver
from appstores_lib import jsonio

XCRESULT_SUFFIX = re.compile(r"_\d+_[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
SIM_PLATFORMS = {"ios": "iOS Simulator", "ipados": "iOS Simulator", "tvos": "tvOS Simulator",
                 "visionos": "visionOS Simulator", "watchos": "watchOS Simulator"}


def attachment_name(human):
    """An attachment's own name from xcresulttool's ``suggestedHumanReadableName``
    (``plan_1_8F3E2A10-….png`` → ``plan``)."""
    stem = os.path.splitext(os.path.basename(human))[0]
    return XCRESULT_SUFFIX.sub("", stem)


def read_manifest(folder):
    """``xcresulttool export attachments``' ``manifest.json`` as ``[(name, file, test, attachment)]``: the
    attachment's own name, its exported file (absolute), the test's identifier and the manifest's entry."""
    path = os.path.join(folder, "manifest.json")
    if not os.path.isfile(path):
        return []
    data = jsonio.load(path)
    out = []
    for test in data if isinstance(data, list) else []:
        for att in test.get("attachments") or []:
            exported = att.get("exportedFileName")
            if not exported:
                continue
            name = attachment_name(att.get("suggestedHumanReadableName") or exported)
            out.append((name, os.path.join(folder, exported), test.get("testIdentifier"), att))
    return out


def language_region(locale):
    """``de-DE`` → (``de``, ``DE``); ``zh-Hans-CN`` → (``zh-Hans``, ``CN``); ``fr`` → (``fr``, ``None``)."""
    parts = locale.split("-")
    lang = parts[0]
    region = None
    for p in parts[1:]:
        if len(p) == 4:
            lang = "%s-%s" % (lang, p)
        elif len(p) == 2:
            region = p.upper()
    return lang, region


class XcuitestDriver(HostedDriver):
    """The app's XCUITest screenshot tests (see the module's docstring)."""

    NAME = "xcuitest"
    PLATFORMS = ("ios", "ipados", "tvos", "visionos", "macos")
    STEPS = ("flow",)
    FINDERS = ()
    HOST_STEPS = ()
    POSTURE_SETTING = True   # the device's posture is set by the host before the flow runs

    def __init__(self, options=None):
        """Set up."""
        HostedDriver.__init__(self, options)
        self.runs = {}
        self.count = 0

    def has_own_step(self, kind):
        return True

    def prepare_app(self, device, plan):
        """Check the target names a scheme (or an ``xctestrun``)."""
        t = device.get("target") or {}
        if not (t.get("scheme") or t.get("xctestrun")):
            raise base.DriverError("%s needs target.scheme (and project or workspace), or target.xctestrun"
                                   % device["id"])

    def destination(self, device):
        """``-destination``: the target's, the host simulator's (``platform=iOS Simulator,id=<udid>``) or
        ``platform=macOS``."""
        t = device.get("target") or {}
        if t.get("destination"):
            return t["destination"]
        if device.get("platform") == "macos":
            return "platform=macOS"
        ref = self.device_ref(device)
        if not ref:
            raise base.DriverError("%s has no simulator to test on (no host, no target.destination)" % device["id"])
        return "platform=%s,id=%s" % (SIM_PLATFORMS.get(device.get("platform"), "iOS Simulator"), ref)

    def test_command(self, device, test, locale, bundle):
        """The ``xcodebuild`` command for one test in one locale, writing ``bundle``."""
        t = device.get("target") or {}
        lang, region = language_region(locale)
        if t.get("xctestrun"):
            cmd = ["xcodebuild", "test-without-building", "-xctestrun", self.path(t["xctestrun"])]
        else:
            cmd = ["xcodebuild", "test"]
            if t.get("workspace"):
                cmd += ["-workspace", self.path(t["workspace"])]
            elif t.get("project"):
                cmd += ["-project", self.path(t["project"])]
            cmd += ["-scheme", t["scheme"]]
            if t.get("configuration"):
                cmd += ["-configuration", t["configuration"]]
        if t.get("testPlan"):
            cmd += ["-testPlan", t["testPlan"]]
        cmd += ["-destination", self.destination(device), "-resultBundlePath", bundle, "-only-testing:%s" % test,
                "-testLanguage", lang]
        if region:
            cmd += ["-testRegion", region]
        return cmd

    def run_test(self, ctx, test):
        """Run ``test`` once for this locale (cached) and return ``{"files": {name: path}, "code", "tail"}``."""
        key = (ctx.locale, test)
        if key in self.runs:
            return self.runs[key]
        self.count += 1
        folder = os.path.join(self.options.workdir, "xcuitest", "%s-%d" % (ctx.locale, self.count))
        bundle = os.path.join(folder, "result.xcresult")
        exported = os.path.join(folder, "attachments")
        if not base.DRY_RUN:
            if os.path.exists(folder):
                shutil.rmtree(folder)
            os.makedirs(exported)
        t = ctx.device.get("target") or {}
        env = {"TEST_RUNNER_APPSTORES_LOCALE": ctx.locale, "TEST_RUNNER_APPSTORES_SCREEN": ctx.screen["id"],
               "TEST_RUNNER_APPSTORES_DEVICE": ctx.device["id"]}
        seed = ctx.screen.get("seed") if ctx.screen.get("seed") is not None else ctx.device.get("seed")
        if seed is not None:
            env["TEST_RUNNER_ScreenshotSeed"] = str(seed)
        res = base.run(self.test_command(ctx.device, test, ctx.locale, bundle), timeout=float(
            t.get("testTimeout") or 1800), check=False, env=env, cwd=self.options.plan_dir)
        tail = (res.out or "").strip().splitlines()[-6:]
        files = {}
        if base.DRY_RUN or os.path.isdir(bundle):
            base.run(["xcrun", "xcresulttool", "export", "attachments", "--path", bundle, "--output-path", exported],
                     timeout=600, check=not base.DRY_RUN)
            for name, path, _test, _att in read_manifest(exported):
                files.setdefault(name, path)
        result = {"files": files, "code": res.code, "tail": tail}
        self.runs[key] = result
        return result

    def run_screen(self, device, screen, locale):
        """Apply the locale, appearance and status bar (by the host), run the screen's test (once for every screen
        that names it), and take the attachment named after the screen."""
        shot = base.Shot(source=self.source(device), status_bar="none")
        why = self.unsupported(screen, device)
        if not why and len(screen.get("steps") or []) != 1:
            why = "an xcuitest screen is one flow step (the test that attaches its picture)"
        if why:
            shot.status = "skipped"
            shot.reason = why
            return shot
        _, value = base.step_of(screen["steps"][0])
        test = value.get("test") if isinstance(value, dict) else value
        name = (value.get("attachment") if isinstance(value, dict) else None) or screen["id"]
        if not test:
            shot.status = "skipped"
            shot.reason = "the flow names no test"
            return shot
        try:
            self.enter_screen(device, screen, locale, shot)
            ctx = base.StepContext(device, screen, locale, shot, 1, screen["steps"][0])
            base.LOG("  step 1: test %s (attachment %s)" % (test, name))
            result = self.recorded(ctx, lambda: self.run_test(ctx, test), cached=(locale, test) in self.runs)
        except base.ToolMissing:
            raise
        except base.DriverError as e:
            shot.status = "missed"
            shot.reason = str(e)
            return shot
        path = self.shot_path(device, screen, locale)
        if base.DRY_RUN:
            shot.path = path
            return shot
        found = result["files"].get(name)
        if not found:
            shot.status = "missed"
            made = ", ".join(sorted(result["files"])) or "none"
            shot.reason = "%s made no attachment named %s (it made: %s)%s" % (
                test, name, made, "; xcodebuild exited %s: %s" % (result["code"], " / ".join(result["tail"]))
                if result["code"] else "")
            return shot
        if result["code"]:
            shot.warnings.append("xcodebuild exited %s, but the attachment is there" % result["code"])
        ext = os.path.splitext(found)[1].lower()
        if ext != ".png":
            path = os.path.splitext(path)[0] + ext
        shutil.copyfile(found, path)
        shot.path = path
        shot.status_bar = self.status_bar
        return shot


DRIVER = XcuitestDriver
