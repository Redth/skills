"""The ``simctl`` driver: iOS, iPadOS, tvOS, watchOS and visionOS simulators through ``xcrun simctl``.

By default it owns a dedicated simulator a device, ``appstores-<device id>``, created from ``target.deviceType``
(a name, ``iPhone 17 Pro Max``, or an identifier) and ``target.runtime`` (``latest``, a name like ``iOS 27.2``, a
version like ``27.2`` or an identifier), reused on later runs and deleted only with ``--cleanup``. A plan that
names an existing simulator (``target.udid``) gets that one, which is never deleted and whose device language is
never changed (the app gets the locale through its launch arguments).

What it does, in order (CONTRACT.md 10.3, 10.5):

- ``prepare``: find or create the simulator, boot it (``simctl boot``, then ``bootstatus -b``), install the app
  (``app.app``, a built ``.app``).
- per screen, when it changes: the locale (``simctl spawn … defaults write -g AppleLanguages`` / ``AppleLocale``
  and a reboot, on its own simulators; ``target.localeScope: "app"`` skips that), the appearance (``simctl ui …
  appearance``), and a clean status bar (``simctl status_bar … override``, read back with ``status_bar … list``).
- steps: ``launch`` (``simctl launch --terminate-running-process`` with ``-ScreenshotSeed``, the screen's
  ``args`` as ``-Key value``, ``-AppleLanguages (xx)`` / ``-AppleLocale``, and ``env`` as ``SIMCTL_CHILD_*``;
  ``clean`` reinstalls), ``deepLink`` and ``url`` (``simctl openurl``), ``wait``, ``settle``, ``script``. It can't
  tap or see elements: pair it with a UI driver for those.
- screenshot: ``simctl io … screenshot --type=png --mask=ignored`` (``--display`` from ``target.display`` for a
  device with more than one screen).
- ``reset``: clear the status bar, put the appearance back, stop the app, shut down a simulator it booted, and
  with ``--cleanup`` delete its own.
"""

from __future__ import annotations

import json
import os
import re

from . import base

SIMCTL = ["xcrun", "simctl"]
RUNTIME_PLATFORMS = {"ios": ("iOS",), "ipados": ("iOS",), "tvos": ("tvOS",), "watchos": ("watchOS",),
                     "visionos": ("visionOS", "xrOS")}
STATUS_BAR_PLATFORMS = ("ios", "ipados")
PREFIX = "appstores-"


def apple_locale(locale):
    """BCP 47 to the ``AppleLocale`` form: ``de-DE`` -> ``de_DE``, ``zh-Hans-CN`` -> ``zh-Hans_CN``, ``fr`` -> ``fr``."""
    parts = locale.split("-")
    if len(parts) > 1 and (len(parts[-1]) == 2 or parts[-1].isdigit()):
        return "-".join(parts[:-1]) + "_" + parts[-1].upper()
    return locale


def status_bar_time(clock):
    """The status bar's time as iOS draws it: ``09:41`` -> ``9:41``; an ISO date-time as it is."""
    m = re.match(r"^0?(\d{1,2}):(\d{2})$", clock or "")
    if m:
        return "%d:%s" % (int(m.group(1)), m.group(2))
    return clock


def _version_key(text):
    return tuple(int(p) for p in re.findall(r"\d+", text or ""))


def first_language(defaults_output):
    """The first entry of ``defaults read -g AppleLanguages`` (``(\\n    "en-US"\\n)``), or ``None``."""
    m = re.search(r'"?([A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*)"?\s*[,)\n]', (defaults_output or "").split("(", 1)[-1])
    return m.group(1) if m else None


class SimctlDriver(base.Driver):
    """Apple simulators through ``xcrun simctl`` (see the module's docstring)."""

    NAME = "simctl"
    PLATFORMS = ("ios", "ipados", "tvos", "watchos", "visionos")
    STEPS = ("launch", "deepLink", "url", "wait", "settle", "script")
    FINDERS = ()
    BOOT_TIMEOUT = 600

    def __init__(self, options=None):
        """Set up; nothing runs until ``prepare``."""
        base.Driver.__init__(self, options)
        self.udid = None
        self.ours = False
        self.created = False
        self.booted_by_us = False
        self.launched = False
        self.info = {}

    # -- finding and creating -----------------------------------------------------------------------------

    def simctl(self, *args, **kw):
        """Run ``xcrun simctl <args>``."""
        return base.run(SIMCTL + [str(a) for a in args], **kw)

    def list_json(self, what):
        """``simctl list <what> -j`` parsed."""
        res = self.simctl("list", what, "-j", dry_output='{"%s": %s}' % (what, "{}" if what == "devices" else "[]"),
                          quiet=True)
        try:
            return json.loads(res.out)
        except ValueError:
            raise base.DriverError("simctl list %s didn't return JSON" % what) from None

    def devices(self):
        """Every simulator as ``(runtime id, device dict)``."""
        data = self.list_json("devices").get("devices") or {}
        for runtime, items in data.items():
            for d in items:
                yield runtime, d

    def find_device(self, udid=None, name=None):
        """A simulator by UDID or name, as ``(runtime id, device dict)``, or ``(None, None)``."""
        for runtime, d in self.devices():
            if (udid and d.get("udid") == udid) or (name and d.get("name") == name and d.get("isAvailable", True)):
                return runtime, d
        return None, None

    def device_type(self, wanted):
        """The device type a name or identifier means, as its JSON (``name``, ``identifier``)."""
        if base.DRY_RUN:
            return {"name": wanted, "identifier": wanted}
        types = self.list_json("devicetypes").get("devicetypes") or []
        for t in types:
            if wanted in (t.get("identifier"), t.get("name")):
                return t
        for t in types:
            if (t.get("name") or "").lower() == wanted.lower():
                return t
        names = ", ".join(t.get("name", "?") for t in types[:12])
        raise base.DriverError("no simulator device type %r (xcrun simctl list devicetypes: %s, ...)" % (wanted, names))

    def runtime(self, wanted, platform, device_type):
        """The runtime ``wanted`` means for this platform and device type: ``latest`` (the newest available that
        supports the device type), a name (``iOS 27.2``), a version (``27.2``) or an identifier."""
        if base.DRY_RUN:
            return {"name": wanted or "latest", "identifier": wanted or "latest"}
        wanted = wanted or "latest"
        families = RUNTIME_PLATFORMS.get(platform, ("iOS",))
        runtimes = [r for r in self.list_json("runtimes").get("runtimes") or [] if r.get("isAvailable", True)]
        fits = []
        for r in runtimes:
            plat = r.get("platform") or (r.get("name") or "").split(" ")[0]
            if plat not in families:
                continue
            supported = [t.get("identifier") for t in r.get("supportedDeviceTypes") or []]
            if supported and device_type["identifier"] not in supported:
                continue
            fits.append(r)
        if wanted != "latest":
            fits = [r for r in fits if wanted in (r.get("identifier"), r.get("name"), r.get("version"))]
        if not fits:
            raise base.DriverError("no available %s runtime %sfor %s (install one in Xcode > Settings > Components)"
                                   % ("/".join(families), "" if wanted == "latest" else "%r " % wanted,
                                      device_type.get("name")))
        # The newest; among equals, the one for the most device types (a general runtime over a device-specific one).
        fits.sort(key=lambda r: (_version_key(r.get("version")), len(r.get("supportedDeviceTypes") or [])))
        return fits[-1]

    def source(self, device):
        """The device type and runtime, for the report."""
        return dict(self.info)

    # -- the four calls -----------------------------------------------------------------------------------

    def prepare(self, device, plan):
        """Find or create the simulator, boot it and install the app."""
        t = device.get("target") or {}
        if t.get("udid"):
            runtime, d = self.find_device(udid=t["udid"])
            if d is None and not base.DRY_RUN:
                raise base.DriverError("no simulator %s (xcrun simctl list devices)" % t["udid"])
            self.udid = t["udid"]
            self.ours = False
        else:
            if not t.get("deviceType"):
                raise base.DriverError("%s needs target.deviceType (or target.udid)" % device["id"])
            name = PREFIX + device["id"]
            runtime, d = self.find_device(name=name)
            self.ours = True
            if d is not None:
                self.udid = d["udid"]
            else:
                dtype = self.device_type(t["deviceType"])
                rt = self.runtime(t.get("runtime"), device["platform"], dtype)
                res = self.simctl("create", name, dtype["identifier"], rt["identifier"],
                                  dry_output="<udid of %s>" % name)
                self.udid = res.out.strip().splitlines()[-1].strip() if res.out.strip() else None
                if not self.udid:
                    raise base.DriverError("simctl create %s gave no UDID" % name)
                self.created = True
                runtime, d = rt["identifier"], {"name": name, "state": "Shutdown",
                                                "deviceTypeIdentifier": dtype["identifier"]}
                self.info = {"deviceType": dtype.get("name"), "runtime": rt.get("name"), "simulator": name}
        if not self.info:
            d = d or {}
            self.info = {"deviceType": self._type_name(d.get("deviceTypeIdentifier") or t.get("deviceType")),
                         "runtime": self._runtime_name(runtime), "simulator": d.get("name")}
        if (d or {}).get("state") != "Booted":
            self.boot()
        app = (device.get("app") or {}).get("app")
        if app:
            self.install(app)

    def _type_name(self, identifier):
        if not identifier:
            return None
        tail = identifier.rsplit(".", 1)[-1]
        return tail.replace("-", " ") if identifier.startswith("com.apple.") else identifier

    def _runtime_name(self, identifier):
        if not identifier:
            return None
        m = re.match(r".*SimRuntime\.([A-Za-z]+)-(\d+)-(\d+)", identifier)
        if not m:
            return identifier
        plat = {"xrOS": "visionOS"}.get(m.group(1), m.group(1))
        return "%s %s.%s" % (plat, m.group(2), m.group(3))

    def boot(self):
        """Boot the simulator and wait until it's fully up."""
        res = self.simctl("boot", self.udid, check=False, timeout=self.BOOT_TIMEOUT)
        if not res.ok and "Booted" not in (res.err + res.out):
            raise base.CommandError(SIMCTL + ["boot", self.udid], res.code, res.out, res.err)
        self.booted_by_us = True
        self.simctl("bootstatus", self.udid, "-b", timeout=self.BOOT_TIMEOUT)

    def shutdown(self):
        """Shut the simulator down."""
        res = self.simctl("shutdown", self.udid, check=False, timeout=120)
        if not res.ok and "Shutdown" not in (res.err + res.out):
            raise base.CommandError(SIMCTL + ["shutdown", self.udid], res.code, res.out, res.err)

    def install(self, app):
        """Install a built ``.app``."""
        path = self.path(app)
        if not base.DRY_RUN and not os.path.isdir(path):
            raise base.DriverError("the app to install isn't there: %s (build it first)" % path)
        self.simctl("install", self.udid, path, timeout=600)

    def reset(self, device):
        """Clear the status bar, restore the appearance, stop the app, shut down what it booted, delete its own
        simulator with ``--cleanup``."""
        warnings = []
        if not self.udid:
            return warnings

        def attempt(what, fn):
            try:
                fn()
            except base.DriverError as e:
                warnings.append("%s: %s" % (what, e))

        if self.changed.get("statusBar"):
            attempt("clearing the status bar", lambda: self.simctl("status_bar", self.udid, "clear"))
        original = self.changed.get("appearance")
        if original in ("light", "dark"):
            attempt("restoring the appearance", lambda: self.simctl("ui", self.udid, "appearance", original))
        bundle = (device.get("app") or {}).get("bundleId")
        if self.launched and bundle:
            self.simctl("terminate", self.udid, bundle, check=False)
        if self.booted_by_us or (self.options.cleanup and self.ours):
            attempt("shutting down", self.shutdown)
        if self.options.cleanup and self.ours:
            attempt("deleting %s" % self.info.get("simulator"), lambda: self.simctl("delete", self.udid))
        return warnings

    # -- per screen -----------------------------------------------------------------------------------------

    def apply_locale(self, device, locale, shot):
        """On its own simulators, set the device's language and region and reboot (system UI follows only the
        device); the app also gets the locale at launch, which is all a named simulator gets."""
        scope = (device.get("target") or {}).get("localeScope") or ("device" if self.ours else "app")
        if scope != "device":
            return
        current = self.simctl("spawn", self.udid, "defaults", "read", "-g", "AppleLanguages", check=False,
                              quiet=True).out
        if first_language(current) == locale:
            return
        self.simctl("spawn", self.udid, "defaults", "write", "-g", "AppleLanguages", "-array", locale)
        self.simctl("spawn", self.udid, "defaults", "write", "-g", "AppleLocale", "-string", apple_locale(locale))
        self.shutdown()
        self.boot()
        self.state.pop("statusBar", None)  # overrides don't survive a reboot

    def apply_appearance(self, device, appearance, shot):
        """``simctl ui <udid> appearance light|dark``, remembering the original."""
        if "appearance" not in self.changed:
            now = self.simctl("ui", self.udid, "appearance", check=False, dry_output="light").out.strip()
            if now in ("unsupported", "unknown") and not base.DRY_RUN:
                shot.warnings.append("this runtime has no appearance setting (simctl ui says %s)" % now)
                self.changed["appearance"] = None
                return
            self.changed["appearance"] = now
        self.simctl("ui", self.udid, "appearance", appearance)

    def apply_status_bar(self, device, mode, clock, shot):
        """``status_bar override`` with the plan's clock, Wi-Fi and full bars, a charged battery and no carrier;
        read back with ``status_bar list``: ``verified`` when the time shows there, else ``overridden``."""
        if device["platform"] not in STATUS_BAR_PLATFORMS:
            return "none"
        if mode != "clean":
            if self.changed.get("statusBar"):
                self.simctl("status_bar", self.udid, "clear", check=False)
                self.changed["statusBar"] = False
            return "none"
        when = status_bar_time(clock)
        res = self.simctl("status_bar", self.udid, "override", "--time", when, "--dataNetwork", "wifi",
                          "--wifiMode", "active", "--wifiBars", "3", "--cellularMode", "active", "--cellularBars", "4",
                          "--operatorName", "", "--batteryState", "charged", "--batteryLevel", "100", check=False)
        if not res.ok:
            shot.warnings.append("the status bar override failed: %s" % (res.err or res.out).strip()[:200])
            return "unverified"
        self.changed["statusBar"] = True
        listed = self.simctl("status_bar", self.udid, "list", check=False, dry_output=when).out
        if when in listed:
            return "verified"
        shot.warnings.append("status_bar list doesn't show the override: check the picture's status bar")
        return "overridden"

    def script_env(self, device):
        """A ``script`` step gets the simulator's UDID as ``APPSTORES_UDID``."""
        return {"APPSTORES_UDID": self.udid or ""}

    # -- steps ------------------------------------------------------------------------------------------------

    def _bundle(self, ctx):
        bundle = (ctx.device.get("app") or {}).get("bundleId")
        if not bundle:
            raise base.StepFailed("step %d: launch needs the plan's app.%s.bundleId" % (ctx.index,
                                                                                         ctx.device["platform"]))
        return bundle

    def launch_args(self, ctx, args):
        """The launch arguments: the seed, the screen's ``args`` (``-Key value``; booleans ``YES``/``NO``) and the
        locale (``-AppleLanguages (de-DE) -AppleLocale de_DE``)."""
        out = []
        seed = ctx.screen.get("seed") if ctx.screen.get("seed") is not None else ctx.device.get("seed")
        if seed is not None and "ScreenshotSeed" not in (args or {}):
            out += ["-ScreenshotSeed", str(seed)]
        for k, v in (args or {}).items():
            if isinstance(v, bool):
                v = "YES" if v else "NO"
            out += ["-" + k, str(v)]
        out += ["-AppleLanguages", "(%s)" % ctx.locale, "-AppleLocale", apple_locale(ctx.locale)]
        return out

    def step_launch(self, ctx, value):
        """Launch the app (``clean``: uninstall and install it again first)."""
        value = value or {}
        bundle = self._bundle(ctx)
        if value.get("clean"):
            app = (ctx.device.get("app") or {}).get("app")
            if app:
                self.simctl("terminate", self.udid, bundle, check=False)
                self.simctl("uninstall", self.udid, bundle, check=False)
                self.install(app)
            else:
                ctx.warn("launch clean needs app.%s.app to reinstall from: nothing was cleared"
                         % ctx.device["platform"])
        env = dict(("SIMCTL_CHILD_" + k, str(v)) for k, v in (value.get("env") or {}).items())
        self.simctl("launch", "--terminate-running-process", self.udid, bundle, *self.launch_args(ctx, value.get("args")),
                    env=env or None, timeout=120)
        self.launched = True

    def step_deepLink(self, ctx, value):
        """``simctl openurl``."""
        url = value.get("url") if isinstance(value, dict) else value
        self.simctl("openurl", self.udid, url, timeout=60)

    def step_url(self, ctx, value):
        """``simctl openurl`` (opens in Safari, or the app that claims it)."""
        self.step_deepLink(ctx, value)

    def screenshot(self, device, path):
        """``simctl io <udid> screenshot --type=png --mask=ignored [--display=…] <path>``."""
        args = ["io", self.udid, "screenshot", "--type=png", "--mask=ignored"]
        display = (device.get("target") or {}).get("display")
        if display:
            args.append("--display=%s" % display)
        self.simctl(*(args + [path]), timeout=60)


DRIVER = SimctlDriver
