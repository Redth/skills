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
  ``clean`` reinstalls), ``deepLink`` and ``url`` (``simctl openurl``), ``appFile`` (a file copied into the app's
  data container, from ``simctl get_app_container … data``, the app stopped first), ``wait``, ``settle``,
  ``script``. It can't tap or see elements: pair it with a UI driver for those.
- the plan's ``staging.permissions`` for the platform are granted after install (``simctl privacy … grant``) and
  revoked in ``reset``.
- foldables (the iPhone Duo; ``posture``: ``folded``, ``open``, ``half-open``): ``simctl`` has no hinge command, and
  Xcode opens one only from its Device Hub. The driver uses DevFlow's fold control (``maui devflow device fold set
  folded|unfolded|partially-folded --udid <udid> --experimental``: the ``Microsoft.Maui.Cli`` tool, no agent needed,
  any app; experimental, through private Simulator APIs, Apple silicon and Xcode 27.1 or later), reads which
  display is active from its answer, and puts the posture back in ``reset``. ``target.foldCli`` names the command.
- screenshot: ``simctl io … screenshot --type=png --mask=ignored`` with ``--display``: ``target.display``, else on a
  simulator with more than one built-in screen (``simctl io <udid> enumerate``) the active one after a posture
  change, or the one whose pixel size is the device's ``width`` x ``height`` (either way round).
- recording (``capture.py --record``): ``simctl io <udid> recordVideo --codec=h264 --mask=ignored [--display=…]
  --force <file>`` from the screen's first ``launch`` (after the reboot a locale change needs) until after its last
  step, stopped with SIGINT before ``verify``, the screenshot and ``reset``. simctl writes a frame only when the
  screen changes and holds the last back until the next change, so a second after the last step the status bar's
  battery is set to 99 % for a second (the flush; its time is in the report: trim there), then back to 100 %.
- a CoreSimulator hiccup (``server died``, ``Mach error -308``, an interrupted connection) while booting,
  installing, launching or capturing is tried once more after a few seconds.
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
FOLD_CLI = ["maui", "devflow"]
FOLD_MODES = {"folded": "folded", "open": "unfolded", "half-open": "partially-folded"}
FOLD_INSTALL = ("install DevFlow's CLI (dotnet tool install -g Microsoft.Maui.Cli --prerelease): its fold control "
                "works on any simulator without an agent; or open the simulator by hand in Xcode's Device Hub and "
                "leave posture out of the plan")
# CoreSimulator's own hiccups: worth one more try.
TRANSIENT = ("server died", "(ipc/mig)", "mach error -308", "connection interrupted", "connection invalid",
             "connection became invalid", "coresimulatorservice", "unable to lookup in current state")


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


def app_file_paths(driver, ctx, value, family):
    """An ``appFile`` step's source (absolute, from the plan's folder) and destination inside the app's data
    (``into``: a path, or one by platform family, ``{"ios": …, "android": …}``). Raises ``StepFailed``."""
    value = value or {}
    src = driver.path(value.get("file"))
    into = value.get("into")
    if isinstance(into, dict):
        into = into.get(ctx.device.get("platform")) or into.get(family)
    if not src or not into:
        raise base.StepFailed("step %d: appFile needs file and into (for %s)" % (ctx.index, ctx.device.get("platform")))
    if not base.DRY_RUN and not os.path.isfile(src):
        raise base.StepFailed("step %d: appFile's file isn't there: %s" % (ctx.index, src))
    rel = into.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        raise base.StepFailed("step %d: appFile's into stays inside the app's data: %s" % (ctx.index, into))
    return src, rel


def integrated_screens(enumerate_output):
    """The built-in screens ``simctl io <udid> enumerate`` lists, as ``[(screen id, width, height)]`` (the iPhone
    Duo: its cover and its inner display; a TV-out or CarPlay screen isn't one)."""
    out = []
    for block in re.split(r"\n\s*\(\d+\)\s", enumerate_output or ""):
        sid = re.search(r"Screen ID:\s*(\d+)", block)
        kind = re.search(r"Screen Type:\s*(\w+)", block)
        size = re.search(r"Pixel Size:\s*\{(\d+),\s*(\d+)\}", block)
        if sid and kind and size and kind.group(1) == "Integrated":
            out.append((sid.group(1), int(size.group(1)), int(size.group(2))))
    return out


def transient(error):
    """True when a simctl failure is CoreSimulator's own hiccup, worth trying once more."""
    text = str(error).lower()
    return any(t in text for t in TRANSIENT)


def copy_replacing(src, dest):
    """Copy ``src`` to ``dest`` (making its folder), removing ``dest`` and a database's ``-wal``/``-shm`` first."""
    import shutil
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for extra in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(dest + extra):
            os.unlink(dest + extra)
    shutil.copyfile(src, dest)


class SimctlDriver(base.Driver):
    """Apple simulators through ``xcrun simctl`` (see the module's docstring)."""

    NAME = "simctl"
    PLATFORMS = ("ios", "ipados", "tvos", "watchos", "visionos")
    STEPS = ("launch", "deepLink", "url", "appFile", "wait", "settle", "script", "posture")
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
        self.granted = []
        self.info = {}
        self.display = None           # the screen captured when the simulator has more than one
        self.displays_read = False
        self.original_posture = None
        self.posture_changed = False

    # -- finding and creating -----------------------------------------------------------------------------

    def simctl(self, *args, **kw):
        """Run ``xcrun simctl <args>``."""
        return base.run(SIMCTL + [str(a) for a in args], **kw)

    def simctl_again(self, *args, **kw):
        """``simctl`` once more after a few seconds when CoreSimulator hiccups (``server died``, ``Mach error -308``):
        for booting, installing, launching and capturing. A command run with ``check=False`` is tried again on a
        non-zero exit with that kind of message too."""
        try:
            res = self.simctl(*args, **kw)
        except base.CommandError as e:
            if not transient(e):
                raise
            problem = str(e)
        else:
            if res.ok or not transient((res.err or "") + (res.out or "")):
                return res
            problem = (res.err or res.out).strip()
        base.note("  CoreSimulator hiccupped (%s): trying once more in 5 s" % problem[:160])
        self.warnings.append("simctl %s hit a CoreSimulator hiccup and was tried again: %s" % (args[0], problem[:160]))
        base.sleep(5)
        return self.simctl(*args, **kw)

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
        self.grant(device)

    def grant(self, device):
        """Grant the plan's ``staging.permissions`` for this platform (``simctl privacy <udid> grant <service>
        <bundle>``) before the app launches, so no prompt shows; remembered for ``reset``."""
        bundle = (device.get("app") or {}).get("bundleId")
        for service in device.get("permissions") or []:
            if not bundle:
                raise base.DriverError("granting %s needs the plan's app.%s.bundleId" % (service, device["platform"]))
            res = self.simctl("privacy", self.udid, "grant", service, bundle, check=False)
            if not res.ok:
                raise base.DriverError("simctl privacy grant %s failed: %s (services: all, calendar, contacts, "
                                       "location, location-always, photos, photos-add, media-library, microphone, "
                                       "motion, reminders, siri; notifications can't be granted this way)"
                                       % (service, (res.err or res.out).strip()[:200]))
            if service not in self.granted:
                self.granted.append(service)

    def ensure_booted(self):
        """Boot the simulator again if something shut it down (a failed Appium session can); return True when it
        had to. The status bar override doesn't survive, so it's applied again."""
        if base.DRY_RUN or not self.udid:
            return False
        _, d = self.find_device(udid=self.udid)
        if d is not None and d.get("state") == "Booted":
            return False
        base.note("  the simulator %s isn't booted (state %s): booting it again" % (
            self.udid, (d or {}).get("state", "unknown")))
        self.boot()
        self.state.pop("statusBar", None)
        return True

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
        res = self.simctl_again("boot", self.udid, check=False, timeout=self.BOOT_TIMEOUT)
        if not res.ok and "Booted" not in (res.err + res.out):
            raise base.CommandError(SIMCTL + ["boot", self.udid], res.code, res.out, res.err)
        self.booted_by_us = True
        self.simctl("bootstatus", self.udid, "-b", timeout=self.BOOT_TIMEOUT)
        if self.state.get("posture"):
            self.state.pop("posture", None)   # applied again after a reboot

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
        self.simctl_again("install", self.udid, path, timeout=600)

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

        if self.posture_changed and self.original_posture in FOLD_MODES and \
                self.info.get("posture") != self.original_posture:
            attempt("putting the posture back (%s)" % self.original_posture,
                    lambda: self.fold(device, self.original_posture))
        if self.changed.get("statusBar"):
            attempt("clearing the status bar", lambda: self.simctl("status_bar", self.udid, "clear"))
        original = self.changed.get("appearance")
        if original in ("light", "dark"):
            attempt("restoring the appearance", lambda: self.simctl("ui", self.udid, "appearance", original))
        bundle = (device.get("app") or {}).get("bundleId")
        for service in self.granted:
            self.simctl("privacy", self.udid, "revoke", service, bundle, check=False)
        self.granted = []
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
        try:
            self.simctl("spawn", self.udid, "defaults", "write", "-g", "AppleLanguages", "-array", locale)
        except base.CommandError as e:
            # Something shut the simulator down (a failed UI-test session can): boot it again, once.
            if "not booted" not in str(e) or not self.ensure_booted():
                raise
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
        read back with ``status_bar list``: ``verified`` when the time shows there, else ``unverified`` (applied
        but not confirmed: look at the picture, and retake)."""
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
        shot.warnings.append("status_bar list doesn't show the override's time %s: it may not have taken; look at "
                             "the picture's status bar" % when)
        return "unverified"

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
                self.granted = []
                self.grant(ctx.device)
            else:
                ctx.warn("launch clean needs app.%s.app to reinstall from: nothing was cleared"
                         % ctx.device["platform"])
        env = dict(("SIMCTL_CHILD_" + k, str(v)) for k, v in (value.get("env") or {}).items())
        self.simctl_again("launch", "--terminate-running-process", self.udid, bundle,
                          *self.launch_args(ctx, value.get("args")), env=env or None, timeout=120)
        self.launched = True

    def step_appFile(self, ctx, value):
        """``appFile``: copy ``file`` (from the plan's folder) to ``into`` inside the app's data container
        (``simctl get_app_container <udid> <bundle> data``: ``Library/Caches/…``, ``Documents/…``), the app stopped
        first and the file it replaces (and any ``-wal``/``-shm`` beside it) removed. The app must be installed."""
        src, rel = app_file_paths(self, ctx, value, "ios")
        bundle = self._bundle(ctx)
        self.simctl("terminate", self.udid, bundle, check=False)
        res = self.simctl("get_app_container", self.udid, bundle, "data", dry_output="<data container>")
        container = res.out.strip()
        dest = os.path.join(container, rel)
        base.note("  copy %s -> %s" % (src, dest))
        if base.DRY_RUN:
            return
        if not container or not os.path.isdir(container):
            raise base.StepFailed("step %d: simctl gave no data container for %s (is it installed?)" % (ctx.index, bundle))
        copy_replacing(src, dest)

    def step_deepLink(self, ctx, value):
        """``simctl openurl``."""
        url = value.get("url") if isinstance(value, dict) else value
        self.simctl("openurl", self.udid, url, timeout=60)

    def step_url(self, ctx, value):
        """``simctl openurl`` (opens in Safari, or the app that claims it)."""
        self.step_deepLink(ctx, value)

    # -- foldables -------------------------------------------------------------------------------------------------

    def fold_cmd(self, device):
        """The fold control's command (``target.foldCli``, default ``maui devflow``)."""
        cli = (device.get("target") or {}).get("foldCli") or FOLD_CLI
        return cli.split() if isinstance(cli, str) else list(cli)

    def fold_state(self, device):
        """``fold get --json``: ``{"mode", "hinges", "displays": [{"id", "active", …}]}`` (``{}`` when unread)."""
        res = self.fold_run(device, ["get"], check=False, dry_output="{}")
        return _first_json(res.out) or {}

    def fold_run(self, device, args, check=True, dry_output="{}", timeout=90):
        cmd = self.fold_cmd(device) + ["device", "fold"] + list(args) + ["--udid", self.udid, "--experimental",
                                                                          "--json"]
        try:
            return base.run(cmd, check=check, timeout=timeout, dry_output=dry_output)
        except base.ToolMissing as e:
            raise base.ToolMissing("%s (%s)" % (e, FOLD_INSTALL)) from None

    def fold(self, device, posture):
        """Set the hinge and wait for the display handover (DevFlow's fold control, which verifies it); returns
        the state it reports. A half-open hinge that settles a few degrees off is accepted with a warning."""
        mode = FOLD_MODES[posture]
        args = ["set", mode, "--timeout", "60"]
        angle = None
        if posture == "half-open":
            angle = float((device.get("target") or {}).get("hingeAngle") or 90)
            args += ["--angle", "%g" % angle]
        res = self.fold_run(device, args, check=False)
        data = _first_json(res.out) or {}
        if res.ok and not data.get("error"):
            return data.get("state") or data
        problem = str(data.get("error") or (res.err or res.out).strip())[:300]
        if posture == "half-open" and "not confirmed" in problem.lower():
            state = self.fold_state(device)
            hinges = state.get("hinges") or []
            got = hinges[0].get("angleDegrees") if hinges and isinstance(hinges[0], dict) else None
            if isinstance(got, (int, float)) and abs(got - angle) <= 10:
                self.warnings.append("the hinge settled at %.0f degrees, not %g (DevFlow couldn't confirm the "
                                     "exact angle)" % (got, angle))
                return state
        raise base.DriverError("couldn't put %s in the %s posture: %s (DevFlow's fold control is experimental: "
                               "Apple silicon, Xcode 27.1 or later)" % (self.udid, posture, problem))

    def apply_posture(self, device, posture, shot):
        """Fold, open or half-open the simulator (the iPhone Duo) through DevFlow's fold control, and capture the
        display it makes active (unless ``target.display`` names one). Already in that posture, nothing is set.
        After a change the app's scene moves to the other display: ``target.postureSettle`` seconds (default 3)
        are waited before the steps."""
        back = dict((v, k) for k, v in FOLD_MODES.items())
        state = None
        if self.original_posture is None:
            state = self.fold_state(device) or {}
            self.original_posture = back.get(state.get("mode"), "unknown")
            if back.get(state.get("mode")) != posture or posture == "half-open":
                state = None
        if state is None:
            state = self.fold(device, posture)
            self.posture_changed = True
            base.sleep(float((device.get("target") or {}).get("postureSettle", 3)))
        active = [str(d.get("id")) for d in state.get("displays") or [] if isinstance(d, dict) and d.get("active")]
        if len(active) == 1:
            self.display = active[0]
            self.displays_read = True
            base.note("  capturing display %s (active in the %s posture)" % (self.display, posture))
        else:
            self.displays_read = False
            self.display = None
        self.info["posture"] = posture

    def screen_for(self, device):
        """The ``--display`` to capture: ``target.display``; else the one a posture made active; else, with more than
        one built-in screen, the one whose pixels are the device's size; ``None`` with one screen."""
        explicit = (device.get("target") or {}).get("display")
        if explicit not in (None, "", "auto"):
            return str(explicit)
        if self.displays_read or base.DRY_RUN:
            return self.display
        self.displays_read = True
        screens = integrated_screens(self.simctl("io", self.udid, "enumerate", check=False, quiet=True).out)
        if len(screens) <= 1:
            self.display = None
            return None
        size = (device["width"], device["height"])
        fits = [sid for sid, w, h in screens if (w, h) in (size, size[::-1])]
        if len(fits) == 1:
            self.display = fits[0]
            base.note("  capturing screen %s (of %s: the one %dx%d)" % (fits[0], ", ".join(s[0] for s in screens),
                                                                       size[0], size[1]))
            return self.display
        raise base.DriverError("%s has %d screens (%s) and none is just %dx%d: set target.display (simctl io %s "
                               "enumerate)" % (self.udid, len(screens), ", ".join(
                                   "%s %dx%d" % s for s in screens), size[0], size[1], self.udid))

    # -- recording (capture.py --record) ---------------------------------------------------------------------

    RECORD_START_TIMEOUT = 30   # seconds for recordVideo's "Recording started"
    FLUSH_HOLD = 1.0            # seconds the flush's frame is held before the recording stops

    def record_support(self, device):
        """Every simulator records (``simctl io recordVideo``)."""
        return None

    def recording_ext(self, device):
        """simctl writes a QuickTime movie."""
        return ".mov"

    def start_recording(self, device, path):
        """``simctl io <udid> recordVideo --codec=h264 --mask=ignored [--display=…] --force <path>`` in the
        background, the display the screenshots take (``screen_for``: the iPhone Duo's cover or inner one); waits
        for its "Recording started" (its first frame is in)."""
        display = self.screen_for(device)
        cmd = SIMCTL + ["io", self.udid, "recordVideo", "--codec=h264", "--mask=ignored"]
        if display:
            cmd.append("--display=%s" % display)
        cmd += ["--force", path]
        log = path + ".log"
        if not base.DRY_RUN:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        proc = base.spawn(cmd, log_path=log)
        rec = {"proc": proc, "file": path, "log": log, "display": display}
        if base.DRY_RUN:
            rec["started"] = base.CLOCK()
            return rec

        def started():
            text = _read(log)
            if "Recording started" in text:
                return True
            if proc.poll() is not None:
                raise base.DriverError("simctl recordVideo stopped before it started: %s" % (
                    text.strip()[-300:] or "it said nothing"))
            return False

        try:
            base.poll(started, self.RECORD_START_TIMEOUT, interval=0.2, what="simctl recordVideo's first frame")
        except base.DriverError:
            base.interrupt(proc)
            raise
        rec["started"] = base.CLOCK()
        return rec

    def stop_recording(self, device, rec, shot):
        """A second for the last step's settled frames, then the flush (the status bar's battery at 99 % for a
        second: simctl holds the last frame back until the screen changes again), SIGINT, and the battery back
        (100 %, or the status bar cleared when it wasn't overridden). Raises ``DriverError`` without a file."""
        base.sleep(self.RECORD_TAIL)
        flush = None
        if device.get("platform") in STATUS_BAR_PLATFORMS:
            at = base.CLOCK() - rec["started"]
            res = self.simctl("status_bar", self.udid, "override", "--batteryLevel", "99", check=False)
            if res.ok:
                flush = {"by": "status bar battery 99%", "at": round(at, 2)}
            else:
                shot.warnings.append("the flush (a status bar change) failed, so the recording may lack its last "
                                     "moment: %s" % (res.err or res.out).strip()[:200])
            base.sleep(self.FLUSH_HOLD)
        else:
            shot.warnings.append("%s has no status bar to change, so nothing flushed the recording's last frames: "
                                 "it may end on the frame before the last change" % device.get("platform"))
        seconds = base.CLOCK() - rec["started"]
        base.note("  stop the recording (SIGINT)")
        base.interrupt(rec["proc"])
        if flush:
            if self.changed.get("statusBar"):
                self.simctl("status_bar", self.udid, "override", "--batteryLevel", "100", check=False)
            else:
                self.simctl("status_bar", self.udid, "clear", check=False)
        if not base.DRY_RUN and not (os.path.isfile(rec["file"]) and os.path.getsize(rec["file"]) > 0):
            raise base.DriverError("simctl recordVideo left no movie: %s" % (
                _read(rec["log"]).strip()[-300:] or "it said nothing"))
        return {"file": rec["file"], "seconds": round(seconds, 1), "by": "simctl recordVideo",
                "display": rec.get("display"), "flush": flush}

    def discard_recording(self, device, rec):
        """Stop it (SIGINT); the workdir goes with the run."""
        base.interrupt(rec.get("proc"))

    def screenshot(self, device, path):
        """``simctl io <udid> screenshot --type=png --mask=ignored [--display=…] <path>``."""
        args = ["io", self.udid, "screenshot", "--type=png", "--mask=ignored"]
        display = self.screen_for(device)
        if display:
            args.append("--display=%s" % display)
        self.simctl_again(*(args + [path]), timeout=60)


def _read(path):
    """A log file's text (empty when it isn't there yet)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _first_json(text):
    """The first JSON object in a command's output, or ``None``."""
    text = (text or "").strip()
    for start in range(len(text)):
        if text[start] == "{":
            try:
                value = json.JSONDecoder().raw_decode(text[start:])[0]
            except ValueError:
                continue
            return value if isinstance(value, dict) else None
    return None


DRIVER = SimctlDriver
