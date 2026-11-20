"""The ``macos`` driver: Mac apps, their window captured at an exact size.

- ``launch`` opens the app (``open -a <app.app>``, or ``open -b <bundleId>``) with its arguments after ``--args``:
  ``-ScreenshotSeed``, the screen's ``args`` as ``-Key value``, the locale (``-AppleLanguages (de-DE) -AppleLocale
  de_DE``) and the appearance (``-AppleInterfaceStyle Dark``), all for this app alone, never the person's Mac;
  ``env`` goes through ``open --env``. A running copy is quit first. Then it waits for the app's window and sizes
  it so the capture is exactly the device's pixels: ``width/scale`` x ``height/scale`` points (``target.scale``,
  default 2, a Retina display's), at ``target.position`` (default ``[0, 40]``).
- ``tap``, ``type``, ``wait`` through Accessibility (``osascript``, System Events): elements by ``id``
  (``AXIdentifier``), ``text`` or ``label`` (name, description, title or value); ``type`` is ``keystroke``.
- screenshot: ``screencapture -x -o -l <window id>`` (no sound, no shadow), the window found with
  ``CGWindowListCopyWindowInfo`` (through ``osascript -l JavaScript``). Its rounded corners come out transparent:
  ``capture.py`` flattens them onto the plan's ``flatten`` colour (``fixes: alpha-flattened``).
- ``reset``: quit the app if it launched it.

Needs the terminal to have **Accessibility** (for clicks and sizing) and **Screen Recording** (for
``screencapture``) in System Settings > Privacy & Security. If the app is already running when the run starts,
it's the person's: the driver refuses (quit it first) rather than touch it.
"""

from __future__ import annotations

import json
import os
import re

from . import base
from .simctl import apple_locale

WINDOWS_JS = (
    'ObjC.import("CoreGraphics");'
    'var l = ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo('
    '$.kCGWindowListOptionOnScreenOnly | $.kCGWindowListExcludeDesktopElements, $.kCGNullWindowID)));'
    'JSON.stringify(l.filter(function (w) { return w.kCGWindowLayer === 0; }).map(function (w) {'
    ' return {id: w.kCGWindowNumber, owner: w.kCGWindowOwnerName, pid: w.kCGWindowOwnerPID,'
    ' name: w.kCGWindowName || "", bounds: w.kCGWindowBounds}; }))'
)


def applescript_string(text):
    """``text`` as an AppleScript string literal."""
    return '"%s"' % str(text).replace("\\", "\\\\").replace('"', '\\"')


def find_script(process, finder, wanted, action):
    """AppleScript that finds the first element of ``process``'s front window by ``finder`` and either clicks it
    (``action="click"``) or returns its ``x,y,w,h`` in points (``"bounds"``); ``missing`` when there's none.
    ``text`` and ``label`` match as every driver's do: the whole of a name, description, title or value
    (AppleScript's ``is`` ignores case), then, when nothing is, a part of one (``contains``)."""
    if finder == "id":
        tests = ['value of attribute "AXIdentifier" of e is %s' % applescript_string(wanted)]
    else:
        w = applescript_string(wanted)
        part = applescript_string(str(wanted).strip())
        tests = ["(name of e is %s) or (description of e is %s) or (title of e is %s) or (value of e is %s)" % (
            w, w, w, w),
            "(name of e contains %s) or (description of e contains %s) or (title of e contains %s) or "
            "(value of e contains %s)" % (part, part, part, part)]
    act = "click e\n          return \"clicked\"" if action == "click" else (
        "set p to position of e\n          set s to size of e\n"
        "          return (item 1 of p as text) & \",\" & (item 2 of p as text) & \",\" & "
        "(item 1 of s as text) & \",\" & (item 2 of s as text)")
    loops = "".join('  repeat with e in (entire contents of window 1)\n'
                    '    try\n'
                    '      if %s then\n'
                    '          %s\n'
                    '      end if\n'
                    '    end try\n'
                    '  end repeat\n' % (test, act) for test in tests)
    return ('tell application "System Events" to tell process %s\n%s'
            'end tell\n'
            'return "missing"' % (applescript_string(process), loops))


class MacOSDriver(base.Driver):
    """Mac apps' windows (see the module's docstring)."""

    NAME = "macos"
    PLATFORMS = ("macos",)
    STEPS = ("launch", "tap", "type", "wait", "settle", "script")
    FINDERS = ("id", "text", "label")
    WINDOW_TIMEOUT = 30

    def __init__(self, options=None):
        """Set up; nothing runs until ``prepare``."""
        base.Driver.__init__(self, options)
        self.launched = False
        self.window = None
        self.process = None
        self.app = {}
        self.scale = 2.0

    def osascript(self, script, js=False, **kw):
        """Run AppleScript (or JavaScript for Automation) and return its output, stripped."""
        cmd = ["osascript"] + (["-l", "JavaScript"] if js else []) + ["-e", script]
        return base.run(cmd, **kw).out.strip()

    def _ref(self):
        if self.app.get("bundleId"):
            return "application id %s" % applescript_string(self.app["bundleId"])
        return "application %s" % applescript_string(self.process)

    def running(self):
        """Whether the app is running."""
        out = self.osascript("return %s is running" % self._ref(), check=False, quiet=True, dry_output="false")
        return out == "true"

    def source(self, device):
        """The app and scale, for the report."""
        return {"app": self.process, "scale": self.scale}

    def prepare(self, device, plan):
        """Check the app isn't already running (the person's copy) and work out its process name."""
        self.app = device.get("app") or {}
        t = device.get("target") or {}
        self.scale = float(t.get("scale") or 2)
        path = self.app.get("app")
        if not path and not self.app.get("bundleId"):
            raise base.DriverError("%s needs the plan's app.macos.app or app.macos.bundleId" % device["id"])
        if path and not base.DRY_RUN and not os.path.isdir(self.path(path)):
            raise base.DriverError("the app isn't there: %s (build it first)" % self.path(path))
        self.process = self.app.get("processName") or (os.path.splitext(os.path.basename(path.rstrip("/")))[0]
                                                       if path else self.app["bundleId"].rsplit(".", 1)[-1])
        if self.running():
            raise base.DriverError("%s is already running: quit it first (the driver won't touch a copy it didn't "
                                   "open)" % self.process)
        w, h = device["width"] / self.scale, device["height"] / self.scale
        if abs(w - round(w)) > 1e-6 or abs(h - round(h)) > 1e-6:
            raise base.DriverError("%dx%d at scale %g isn't a whole number of points: pick a scale that divides both"
                                   % (device["width"], device["height"], self.scale))

    def reset(self, device):
        """Quit the app if this driver opened it."""
        warnings = []
        if self.launched:
            try:
                self.quit()
            except base.DriverError as e:
                warnings.append("quitting %s: %s" % (self.process, e))
        return warnings

    def quit(self):
        """Ask the app to quit and wait until it has."""
        self.osascript("tell %s to quit" % self._ref(), check=False, timeout=30)
        base.poll(lambda: not self.running(), 20, interval=0.5, what="%s to quit" % self.process)

    # -- windows ------------------------------------------------------------------------------------------------

    def windows(self):
        """On-screen windows (``id``, ``owner``, ``pid``, ``name``, ``bounds``), front to back."""
        out = self.osascript(WINDOWS_JS, js=True, quiet=True, dry_output="[]")
        try:
            return json.loads(out or "[]")
        except ValueError:
            raise base.DriverError("couldn't list windows: %s" % out[:200]) from None

    def front_window(self):
        """The app's front window, or ``None``."""
        for w in self.windows():
            if w.get("owner") == self.process:
                return w
        return None

    def size_window(self, device):
        """Move and size the app's front window to the device's size in points."""
        t = device.get("target") or {}
        x, y = (t.get("position") or [0, 40])[:2]
        w, h = int(round(device["width"] / self.scale)), int(round(device["height"] / self.scale))
        self.osascript('tell application "System Events" to tell process %s\n'
                       '  set position of window 1 to {%d, %d}\n'
                       '  set size of window 1 to {%d, %d}\n'
                       'end tell' % (applescript_string(self.process), x, y, w, h), timeout=30)
        return w, h

    # -- steps ----------------------------------------------------------------------------------------------------

    def step_launch(self, ctx, value):
        """Quit a running copy, open the app with its arguments, wait for its window and size it."""
        value = value or {}
        if self.launched and self.running():
            self.quit()
        if value.get("clean"):
            ctx.warn("a Mac app has no generic way to clear its data: launch clean cleared nothing (have the app's "
                     "screenshot mode start fresh)")
        cmd = ["open", "-n"]
        for k, v in sorted((value.get("env") or {}).items()):
            cmd += ["--env", "%s=%s" % (k, v)]
        cmd += ["-a", self.path(self.app["app"])] if self.app.get("app") else ["-b", self.app["bundleId"]]
        args = []
        seed = ctx.screen.get("seed") if ctx.screen.get("seed") is not None else ctx.device.get("seed")
        if seed is not None and "ScreenshotSeed" not in (value.get("args") or {}):
            args += ["-ScreenshotSeed", str(seed)]
        for k, v in (value.get("args") or {}).items():
            args += ["-" + k, ("YES" if v else "NO") if isinstance(v, bool) else str(v)]
        args += ["-AppleLanguages", "(%s)" % ctx.locale, "-AppleLocale", apple_locale(ctx.locale)]
        appearance = ctx.screen.get("appearance") or ctx.device.get("appearance") or "light"
        args += ["-AppleInterfaceStyle", "Dark" if appearance == "dark" else "Light"]
        base.run(cmd + ["--args"] + args, timeout=60)
        self.launched = True
        self.window = base.poll(self.front_window, self.WINDOW_TIMEOUT, interval=0.5,
                                what="a window of %s" % self.process) if not base.DRY_RUN else {"id": "<window id>"}
        want = self.size_window(ctx.device)
        if not base.DRY_RUN:
            base.sleep(0.5)
            self.window = self.front_window() or self.window
            b = self.window.get("bounds") or {}
            got = (int(b.get("Width", 0)), int(b.get("Height", 0)))
            if got != want:
                ctx.warn("the window is %dx%d points, not %dx%d (a minimum or maximum size?)" % (got + want))

    def find(self, ctx, query):
        """An element of the front window by ``id``, ``text`` or ``label``, with its bounds in points."""
        out = self.osascript(find_script(self.process, query[0], query[1], "bounds"), check=False, timeout=60,
                             dry_output="0,0,2,2")
        m = re.match(r"^(-?\d+),(-?\d+),(\d+),(\d+)$", out)
        if not m:
            return None
        x, y, w, h = (int(v) for v in m.groups())
        return base.Element(id=str(query[1]), bounds=(x, y, x + w, y + h))

    def step_tap(self, ctx, value):
        """Click an element (Accessibility's ``click``), or ``{x, y}`` in the picture's pixels within the window."""
        self.osascript("tell %s to activate" % self._ref(), check=False)
        if isinstance(value, dict) and "x" in value and "y" in value:
            b = (self.window or {}).get("bounds") or {}
            x = int(b.get("X", 0) + value["x"] / self.scale)
            y = int(b.get("Y", 0) + value["y"] / self.scale)
            self.osascript('tell application "System Events" to click at {%d, %d}' % (x, y))
            return
        query = base.element_query(value)
        if query is None:
            raise base.StepFailed("step %d: tap needs an element (id, text, label) or x and y" % ctx.index)
        self.wait_for(ctx, query, (value or {}).get("timeout"))
        out = self.osascript(find_script(self.process, query[0], query[1], "click"), check=False, timeout=60,
                             dry_output="clicked")
        if out != "clicked":
            raise base.StepFailed("step %d: couldn't click %s %r" % (ctx.index, query[0], query[1]))

    def step_type(self, ctx, value):
        """Click the named field (if any), then ``keystroke`` the text."""
        query = base.step_element("type", value)
        target = {query[0]: query[1], "timeout": value.get("timeout")} if query else None
        if target:
            self.step_tap(ctx, target)
        self.osascript("tell %s to activate" % self._ref(), check=False)
        self.osascript('tell application "System Events" to keystroke %s' % applescript_string(value["text"]))

    def screenshot(self, device, path):
        """``screencapture -x -o -l <window id> <path>``."""
        window = (self.window or {"id": "<window id>"}) if base.DRY_RUN else (self.front_window() or self.window)
        if not window:
            raise base.DriverError("%s has no window on screen to capture (launch it first)" % self.process)
        res = base.run(["screencapture", "-x", "-o", "-l%s" % window["id"], path], check=False, timeout=60)
        if base.DRY_RUN:
            return
        if not res.ok or not os.path.isfile(path):
            raise base.DriverError("screencapture failed (%s): give the terminal Screen Recording in System Settings "
                                   "> Privacy & Security" % (res.err or res.out).strip()[:200])


DRIVER = MacOSDriver
