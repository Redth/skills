"""The ``uiautomator`` driver: the ``adb`` driver's element steps on their own, for an Android device already in
the state the person wants.

It connects to ``target.serial`` (or an emulator already running ``target.avd``; it never starts one), finds
elements in ``uiautomator dump`` (``id``, ``text``, ``label``, ``xpath``), acts with ``input`` (``tap``, ``type``,
``scroll``, ``swipe``, ``back``) and captures with ``screencap``. It changes nothing else: no display size, no
language, no dark mode, no demo mode (so the status bar is as it is: ``none`` in the report), no install, no launch.
Use the ``adb`` driver for those.
"""

from __future__ import annotations

from . import adb
from . import base


class UiAutomatorDriver(adb.AdbDriver):
    """Element steps and screenshots on a connected Android device, changing nothing else."""

    NAME = "uiautomator"
    STEPS = ("tap", "type", "wait", "scroll", "back", "swipe", "settle", "script", "hideKeyboard")
    MANAGES_DEVICE = False

    def prepare(self, device, plan):
        """Connect to the device the plan names; never start, size or set it up."""
        t = device.get("target") or {}
        self.adb = [t.get("adb") or self._sdk_tool("adb", "platform-tools")]
        if t.get("serial"):
            self.serial = t["serial"]
        elif t.get("avd"):
            self.serial = self.running_avd(t["avd"])
            if not self.serial and not base.DRY_RUN:
                raise base.DriverError("no emulator is running %s: start it (or use the adb driver, which can)"
                                       % t["avd"])
            self.serial = self.serial or "<serial of %s>" % t["avd"]
            self.info["avd"] = t["avd"]
        else:
            raise base.DriverError("%s needs target.serial (or target.avd of a running emulator)" % device["id"])
        if not base.DRY_RUN and self.serial not in self.connected():
            raise base.DriverError("no device %s is connected (adb devices)" % self.serial)
        if device.get("statusBar", "clean") == "clean":
            self.warnings.append("the uiautomator driver leaves the status bar, size, language and appearance as "
                                 "they are: use the adb driver to set them")


DRIVER = UiAutomatorDriver
