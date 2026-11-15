"""The ``adb`` driver: Android phones, tablets, TV, Wear and Fire devices, emulators or real ones, through ``adb``.

Which device (``target``):

- ``serial``: a device or emulator already connected (``adb devices``). It's the person's: it's never stopped or
  deleted, and everything changed on it is put back.
- ``avd``: an emulator by AVD name; one already running is used as it is, else it's started headless
  (``emulator -avd … -no-window -no-audio -no-boot-anim -no-snapshot-save``; ``readOnly: true`` adds
  ``-read-only`` so the AVD's disk is never written) and stopped after.
- ``systemImage`` (and ``profile``, a device definition such as ``medium_phone``): an AVD of our own,
  ``appstores-<device id>``, created with ``avdmanager`` if it isn't there and deleted with ``--cleanup``.

What it does (CONTRACT.md 10.3, 10.5):

- ``prepare``: boot (poll until ``sys.boot_completed`` is 1), lay out at the device's size (``wm size
  <width>x<height>``, or ``target.wmSize``; ``null`` leaves it; ``target.density`` for ``wm density``), turn
  animations off, switch the navigation mode (``target.navigation``: ``gesture``, ``threebutton``), install
  ``app.apk`` (``install -r``; a .NET debug APK built for Fast Deployment, with no assemblies inside, is warned
  about), and grant the plan's ``staging.permissions`` (``pm grant``; revoked in ``reset``).
- tools: ``target.adb``, ``target.emulator`` and ``target.avdmanager`` name them; else ``$ANDROID_HOME`` (or
  ``$ANDROID_SDK_ROOT``)'s ``platform-tools``, ``emulator`` and ``cmdline-tools/latest/bin`` (or the newest
  ``cmdline-tools/<version>/bin``, then ``tools/bin``), else ``PATH``.
- per screen, when it changes: the app's language (``cmd locale set-app-locales <package> --locales <locale>``,
  Android 13 and later; ``target.deviceLocale: true`` sets the device's too: ``cmd locale set-device-locale``,
  or ``setprop persist.sys.locale`` and a SystemUI restart on older emulators), dark mode (``cmd uimode night
  yes|no``), and SystemUI demo mode for a clean status bar (the plan's clock, a full battery, Wi-Fi shown fully
  connected, the mobile icon hidden unless ``target.statusBarMobile``, no notifications or other icons). The
  status bar is then checked in the pixels: its strip is captured, demo mode's clock moved and put back, and only
  when the strip changed with it and came back is it ``verified``; otherwise ``unverified`` (or ``overridden``
  with ``target.statusBarCheck: false``).
- steps: ``launch`` (``am start -W -S -n <package>/<activity>`` with ``--es ScreenshotSeed …`` and the screen's
  ``args`` as extras: ``--es``/``--ez``/``--ei``/``--ef``; ``clean`` runs ``pm clear`` first), ``deepLink``
  (``am start -a android.intent.action.VIEW -d <url> <package>``), ``url``, ``tap``/``type``/``swipe``/``back``
  (``input``), ``wait``/``scroll`` with elements found in ``uiautomator dump`` by ``id`` (resource id), ``text``,
  ``label`` (content description) or ``xpath``; ``appFile`` (a file pushed into the app's own data folder through
  ``run-as``: debug builds only).
- screenshot: ``adb exec-out screencap -p`` (``-d <display>`` from ``target.display``).
- ``reset``: leave demo mode, put back the display size, density, dark mode, language and animation scales, stop
  the app, stop an emulator it started, and with ``--cleanup`` delete its own AVD.
"""

from __future__ import annotations

import os
import re
import shlex
import zipfile

from . import base
from .simctl import app_file_paths

try:
    from appstores_lib import png
except ImportError:  # pragma: no cover - the skill always ships it
    png = None

DEMO = "com.android.systemui.demo"
ANIMATIONS = ("window_animation_scale", "transition_animation_scale", "animator_duration_scale")
PREFIX = "appstores-"
UI_DUMP = "/sdcard/appstores-ui.xml"
NAV_OVERLAYS = {"gesture": "com.android.internal.systemui.navbar.gestural",
                "threebutton": "com.android.internal.systemui.navbar.threebutton",
                "twobutton": "com.android.internal.systemui.navbar.twobutton"}
STATUS_ICONS = ("bluetooth", "volume", "alarm", "location", "sync", "mute", "speakerphone", "zen", "eri", "tty",
                "cast", "hotspot")


def demo_commands(clock, mobile=False):
    """SystemUI demo mode's broadcasts (the ``-e`` extras after ``-a com.android.systemui.demo``) for a clean bar:
    the clock, a full battery not charging, Wi-Fi at full strength and *fully* connected (without ``fully`` some
    images draw a "!" on it), the mobile icon hidden (an emulator without a SIM otherwise shows an empty triangle and
    "3G"), or with ``mobile`` full and fully connected with no data type, no notifications, no other icons."""
    out = [["command", "enter"],
           ["command", "clock", "-e", "hhmm", demo_clock(clock)],
           ["command", "battery", "-e", "level", "100", "-e", "plugged", "false"],
           ["command", "network", "-e", "wifi", "show", "-e", "level", "4", "-e", "fully", "true"]]
    if mobile:
        out.append(["command", "network", "-e", "mobile", "show", "-e", "datatype", "none", "-e", "level", "4",
                    "-e", "fully", "true"])
    else:
        out.append(["command", "network", "-e", "mobile", "hide"])
    out.append(["command", "notifications", "-e", "visible", "false"])
    status = ["command", "status"]
    for icon in STATUS_ICONS:
        status += ["-e", icon, "hide"]
    out.append(status)
    return out


def other_clock(clock):
    """A demo clock that draws differently from ``clock`` (to see the status bar respond)."""
    return "1208" if demo_clock(clock) != "1208" else "0317"


def fast_deployment_apk(path):
    """True when ``path`` is a .NET for Android APK with no assemblies in it: a Debug build made for Fast
    Deployment, which only runs when the IDE pushes the assemblies beside it (it crashes after ``adb install``).
    Build it with ``-p:EmbedAssembliesIntoApk=true``. False for anything else, or a file that isn't a zip."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return False
    dotnet = any(n.rsplit("/", 1)[-1] in ("libmonodroid.so", "libxamarin-app.so", "libmonosgen-2.0.so")
                 for n in names)
    if not dotnet:
        return False
    return not any("assembl" in n.lower() or n.endswith(".dll") or n.endswith(".dll.so") for n in names)


def demo_clock(clock):
    """The plan's clock as demo mode's ``hhmm``: ``09:41`` -> ``0941``; an ISO date-time's time likewise."""
    m = re.search(r"(\d{1,2}):(\d{2})", clock or "")
    if not m:
        return "0941"
    return "%02d%s" % (int(m.group(1)), m.group(2))


def extras(args):
    """Intent extras for ``am start``: strings ``--es``, booleans ``--ez``, integers ``--ei``, other numbers ``--ef``."""
    out = []
    for k, v in (args or {}).items():
        if isinstance(v, bool):
            out += ["--ez", k, "true" if v else "false"]
        elif isinstance(v, int):
            out += ["--ei", k, str(v)]
        elif isinstance(v, float):
            out += ["--ef", k, repr(v)]
        else:
            out += ["--es", k, str(v)]
    return out


def input_text(text):
    """Text as ``input text`` takes it (spaces as ``%s``); raises ``StepFailed`` for what it can't type."""
    if any(ord(c) > 126 or ord(c) < 32 for c in text):
        raise base.StepFailed("adb's input text types only plain ASCII: %r (seed it through the app instead)" % text)
    return text.replace("%", "\\%").replace(" ", "%s")


def parse_size(output, label):
    """``Physical size: 1080x2400`` (or ``density``) from ``wm size``/``wm density`` output, by its label."""
    m = re.search(r"%s (?:size|density): (\S+)" % label, output or "")
    return m.group(1) if m else None


class AdbDriver(base.Driver):
    """Android through ``adb`` (see the module's docstring)."""

    NAME = "adb"
    PLATFORMS = ("android",)
    STEPS = ("launch", "deepLink", "url", "appFile", "tap", "type", "wait", "scroll", "back", "swipe", "settle",
             "script")
    FINDERS = ("id", "text", "label", "xpath")
    MANAGES_DEVICE = True     # the uiautomator driver leaves size, locale, appearance and status bar alone
    BOOT_TIMEOUT = 600

    def __init__(self, options=None):
        """Set up; nothing runs until ``prepare``."""
        base.Driver.__init__(self, options)
        self.serial = None
        self.adb = ["adb"]
        self.proc = None
        self.started = False
        self.avd_created = None
        self.sdk = 0
        self.launched = False
        self.info = {}
        self.screen_size = None
        self.log_path = None
        self.granted = []

    # -- commands -------------------------------------------------------------------------------------------

    def adb_run(self, *args, **kw):
        """``adb -s <serial> <args>``."""
        return base.run(self.adb + ["-s", self.serial] + [str(a) for a in args], **kw)

    def shell(self, *args, **kw):
        """``adb -s <serial> shell '<args, each quoted for the device's shell>'``."""
        line = " ".join(shlex.quote(str(a)) for a in args)
        return base.run(self.adb + ["-s", self.serial, "shell", line], **kw)

    def connected(self):
        """The serials ``adb devices`` lists as ready."""
        out = base.run(self.adb + ["devices"], quiet=True, dry_output="").out
        serials = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        return serials

    def _sdk_tool(self, name, *sub):
        home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        if home:
            path = os.path.join(home, *(sub + (name,)))
            if os.path.isfile(path):
                return path
        return name

    def avdmanager(self, t):
        """``target.avdmanager``, else the SDK's ``cmdline-tools/latest/bin/avdmanager``, else the newest versioned
        ``cmdline-tools/<version>/bin/avdmanager`` (an SDK Manager install has no ``latest``), else
        ``tools/bin/avdmanager``, else ``avdmanager`` on ``PATH``."""
        if t.get("avdmanager"):
            return t["avdmanager"]
        home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        if home:
            tools = os.path.join(home, "cmdline-tools")
            names = ["latest"]
            if os.path.isdir(tools):
                versions = [n for n in os.listdir(tools) if n != "latest" and re.match(r"^\d+(\.\d+)*", n)]
                versions.sort(key=lambda n: tuple(int(p) for p in re.findall(r"\d+", n)), reverse=True)
                names += versions
            for n in names:
                path = os.path.join(tools, n, "bin", "avdmanager")
                if os.path.isfile(path):
                    return path
            path = os.path.join(home, "tools", "bin", "avdmanager")
            if os.path.isfile(path):
                return path
        return "avdmanager"

    # -- the four calls ---------------------------------------------------------------------------------------

    def source(self, device):
        """The AVD or device and Android version, for the report."""
        return dict(self.info)

    def prepare(self, device, plan):
        """Find or start the device, then lay it out at the device's size and install the app."""
        t = device.get("target") or {}
        self.adb = [t.get("adb") or self._sdk_tool("adb", "platform-tools")]
        if t.get("serial"):
            self.serial = t["serial"]
            if not base.DRY_RUN and self.serial not in self.connected():
                raise base.DriverError("no device %s is connected (adb devices)" % self.serial)
            self.info["device"] = "serial"
        else:
            avd = t.get("avd")
            if not avd and t.get("systemImage"):
                avd = PREFIX + device["id"]
                self.create_avd(avd, t)
            if not avd:
                raise base.DriverError("%s needs target.serial, target.avd or target.systemImage" % device["id"])
            self.info["avd"] = avd
            self.serial = self.running_avd(avd) or self.start_emulator(avd, t)
        self.wait_for_boot()
        sdk = self.shell("getprop", "ro.build.version.sdk", quiet=True, dry_output="36").out.strip()
        self.sdk = int(sdk) if sdk.isdigit() else 0
        self.info["android"] = "API %d" % self.sdk if self.sdk else None
        if self.MANAGES_DEVICE:
            self.lay_out(device, t)
            if t.get("animations", "off") == "off":
                for key in ANIMATIONS:
                    old = self.shell("settings", "get", "global", key, quiet=True, dry_output="1").out.strip()
                    self.changed.setdefault("animations", {})[key] = old
                    self.shell("settings", "put", "global", key, "0")
            if t.get("navigation"):
                self.set_navigation(t["navigation"])
            apk = (device.get("app") or {}).get("apk")
            if apk:
                path = self.path(apk)
                if not base.DRY_RUN and not os.path.isfile(path):
                    raise base.DriverError("the APK to install isn't there: %s (build it first)" % path)
                if not base.DRY_RUN and fast_deployment_apk(path):
                    self.warnings.append("%s looks like a .NET Debug APK made for Fast Deployment (no assemblies "
                                         "inside): it won't start after adb install. Build it with "
                                         "-p:EmbedAssembliesIntoApk=true" % os.path.basename(path))
                    base.note("  warning: %s" % self.warnings[-1])
                self.adb_run("install", "-r", path, timeout=600)
            self.grant(device)

    def set_navigation(self, mode):
        """Gesture or button navigation through SystemUI's navigation bar overlays (``cmd overlay
        enable-exclusive --category``), remembering the one enabled before for ``reset``."""
        overlay = NAV_OVERLAYS.get(mode)
        if overlay is None:
            raise base.DriverError("target.navigation is one of %s, not %r" % (", ".join(sorted(NAV_OVERLAYS)), mode))
        listed = self.shell("cmd", "overlay", "list", check=False, quiet=True, dry_output="").out
        m = re.search(r"\[x\]\s+(com\.android\.internal\.systemui\.navbar\.\S+)", listed or "")
        before = m.group(1) if m else None
        if before == overlay:
            return
        self.shell("cmd", "overlay", "enable-exclusive", "--category", overlay)
        self.changed["navigation"] = before

    def grant(self, device):
        """``pm grant <package> <permission>`` for the plan's ``staging.permissions`` (Android's names, as
        ``android.permission.POST_NOTIFICATIONS``), remembered so ``reset`` revokes them."""
        package = (device.get("app") or {}).get("package")
        for perm in device.get("permissions") or []:
            if not package:
                raise base.DriverError("granting %s needs the plan's app.android.package" % perm)
            name = perm if "." in perm else "android.permission." + perm
            self.shell("pm", "grant", package, name)
            if name not in self.granted:
                self.granted.append(name)

    def create_avd(self, name, t):
        """``avdmanager create avd -n appstores-<id> -k <systemImage> [-d <profile>]`` unless it exists."""
        emulator = t.get("emulator") or self._sdk_tool("emulator", "emulator")
        have = base.run([emulator, "-list-avds"], quiet=True, dry_output="").out.split()
        if name in have:
            return
        avdmanager = self.avdmanager(t)
        cmd = [avdmanager, "create", "avd", "-n", name, "-k", t["systemImage"]]
        if t.get("profile"):
            cmd += ["-d", t["profile"]]
        base.run(cmd, input="no\n", timeout=300)
        self.avd_created = name

    def running_avd(self, avd):
        """The serial of an emulator already running this AVD, or ``None``."""
        for serial in self.connected():
            if not serial.startswith("emulator-"):
                continue
            out = base.run(self.adb + ["-s", serial, "emu", "avd", "name"], check=False, quiet=True).out
            if out.strip().splitlines()[:1] == [avd]:
                return serial
        return None

    def start_emulator(self, avd, t):
        """Start the AVD headless on a free port and return its serial."""
        used = set(self.connected())
        port = t.get("port")
        if not port:
            port = next(p for p in range(5580, 5680, 2) if "emulator-%d" % p not in used)
        emulator = t.get("emulator") or self._sdk_tool("emulator", "emulator")
        cmd = [emulator, "-avd", avd, "-port", str(port), "-no-audio", "-no-boot-anim", "-no-snapshot-save"]
        if not t.get("window"):
            cmd.append("-no-window")
        if t.get("readOnly"):
            cmd.append("-read-only")
        cmd += [str(a) for a in t.get("emulatorArgs") or []]
        self.log_path = os.path.join(self.options.workdir, "emulator-%s.log" % avd) if not base.DRY_RUN else None
        self.proc = base.spawn(cmd, log_path=self.log_path)
        self.started = True
        return "emulator-%d" % int(port)

    def wait_for_boot(self):
        """Poll until the device answers and ``sys.boot_completed`` is 1 (a dropped adb server or a device still
        coming up is just "not yet"); an emulator this driver started that exits fails with its log's last lines."""

        def booted():
            if self.proc is not None and self.proc.poll() is not None:
                raise base.DriverError("the emulator exited (%s)%s" % (self.proc.poll(), self._log_tail()))
            res = self.shell("getprop", "sys.boot_completed", check=False, quiet=True, dry_output="1", timeout=30)
            return res.ok and res.out.strip() == "1"

        base.run(self.adb + ["start-server"], check=False, quiet=True, timeout=60)
        base.poll(booted, self.BOOT_TIMEOUT, interval=2, what="%s to finish booting" % self.serial)

    def _log_tail(self, lines=8):
        if not self.log_path or not os.path.isfile(self.log_path):
            return ""
        with open(self.log_path, "rb") as f:
            text = f.read().decode("utf-8", "replace").strip().splitlines()
        return ": " + " / ".join(text[-lines:]) if text else ""

    def lay_out(self, device, t):
        """``wm size`` the device's size (and ``wm density``), remembering what to put back."""
        wanted = t["wmSize"] if "wmSize" in t else "%dx%d" % (device["width"], device["height"])
        # Under --dry-run the device's own size isn't known: show the wm size a real run would set.
        out = self.shell("wm", "size", quiet=True, dry_output="Physical size: (the device's)").out
        physical, override = parse_size(out, "Physical"), parse_size(out, "Override")
        self.screen_size = wanted or override or physical
        if wanted and (override or physical) != wanted:
            self.changed["wmSize"] = override or "reset"
            self.shell("wm", "size", wanted)
        if t.get("density"):
            out = self.shell("wm", "density", quiet=True, dry_output="").out
            override = parse_size(out, "Override")
            self.changed["density"] = override or "reset"
            self.shell("wm", "density", str(t["density"]))

    def reset(self, device):
        """Put back everything changed; stop an emulator it started; delete its own AVD with ``--cleanup``."""
        warnings = []
        if not self.serial:
            return warnings

        def attempt(what, *args):
            try:
                self.shell(*args)
            except base.DriverError as e:
                warnings.append("%s: %s" % (what, e))

        if self.changed.get("demo"):
            attempt("leaving demo mode", "am", "broadcast", "-a", DEMO, "-e", "command", "exit")
            old = self.changed.get("demoAllowed")
            if old in (None, "", "null"):
                attempt("restoring sysui_demo_allowed", "settings", "delete", "global", "sysui_demo_allowed")
            else:
                attempt("restoring sysui_demo_allowed", "settings", "put", "global", "sysui_demo_allowed", old)
        if self.changed.get("night"):
            attempt("restoring dark mode", "cmd", "uimode", "night", self.changed["night"])
        package = (device.get("app") or {}).get("package")
        for perm in self.granted:
            if package:
                attempt("revoking %s" % perm, "pm", "revoke", package, perm)
        self.granted = []
        if self.changed.get("navigation"):
            attempt("restoring the navigation mode", "cmd", "overlay", "enable-exclusive", "--category",
                    self.changed["navigation"])
        if self.changed.get("appLocale") and package:
            attempt("restoring the app's language", "cmd", "locale", "set-app-locales", package)
        if "deviceLocale" in self.changed:
            old = self.changed["deviceLocale"]
            if old:
                attempt("restoring the device's language", "cmd", "locale", "set-device-locale", old)
        for key, old in (self.changed.get("animations") or {}).items():
            if old in ("", "null"):
                attempt("restoring %s" % key, "settings", "delete", "global", key)
            else:
                attempt("restoring %s" % key, "settings", "put", "global", key, old)
        if "density" in self.changed:
            attempt("restoring the density", "wm", "density", self.changed["density"])
        if "wmSize" in self.changed:
            attempt("restoring the display size", "wm", "size", self.changed["wmSize"])
        if self.launched and package:
            attempt("stopping the app", "am", "force-stop", package)
        if self.started:
            try:
                self.adb_run("emu", "kill", check=False, timeout=60)
            except base.DriverError as e:
                warnings.append("stopping the emulator: %s" % e)
            base.stop(self.proc)
        if self.options.cleanup and self.avd_created is None and (self.info.get("avd") or "").startswith(PREFIX):
            self.avd_created = self.info["avd"]
        if self.options.cleanup and self.avd_created:
            t = device.get("target") or {}
            avdmanager = self.avdmanager(t)
            try:
                base.run([avdmanager, "delete", "avd", "-n", self.avd_created], timeout=120)
            except base.DriverError as e:
                warnings.append("deleting %s: %s" % (self.avd_created, e))
        return warnings

    # -- per screen --------------------------------------------------------------------------------------------

    def apply_locale(self, device, locale, shot):
        """The app's language (Android 13+), and the device's with ``target.deviceLocale``."""
        if not self.MANAGES_DEVICE:
            return
        t = device.get("target") or {}
        package = (device.get("app") or {}).get("package")
        if t.get("deviceLocale"):
            if "deviceLocale" not in self.changed:
                self.changed["deviceLocale"] = self.shell("getprop", "persist.sys.locale", quiet=True,
                                                          dry_output="").out.strip() or None
            if self.sdk >= 33 or base.DRY_RUN:
                self.shell("cmd", "locale", "set-device-locale", locale)
            else:
                self.adb_run("root", check=False)
                self.shell("setprop", "persist.sys.locale", locale)
                self.shell("setprop", "ctl.restart", "zygote")
                self.wait_for_boot()
                self.state.pop("statusBar", None)
                self.state.pop("appearance", None)
        if package and (self.sdk >= 33 or base.DRY_RUN):
            self.shell("cmd", "locale", "set-app-locales", package, "--locales", locale)
            self.changed["appLocale"] = True
        elif package and not t.get("deviceLocale"):
            shot.warnings.append("Android %s has no per-app language: set target.deviceLocale (a rooted emulator) "
                                 "or have the app read the locale itself" % (self.sdk or "?"))

    def apply_appearance(self, device, appearance, shot):
        """``cmd uimode night yes|no``, remembering the original."""
        if not self.MANAGES_DEVICE:
            return
        if "night" not in self.changed:
            out = self.shell("cmd", "uimode", "night", quiet=True, dry_output="Night mode: no").out
            m = re.search(r"Night mode:\s*(\w+)", out)
            self.changed["night"] = m.group(1) if m else "no"
        self.shell("cmd", "uimode", "night", "yes" if appearance == "dark" else "no")

    def apply_status_bar(self, device, mode, clock, shot):
        """SystemUI demo mode (``demo_commands``): the clock, a full battery not charging, Wi-Fi full and fully
        connected, the mobile icon hidden (``target.statusBarMobile: true`` shows it full), no notifications or
        other icons. Then the pixels are checked (``check_status_bar``): ``verified`` when the status bar's strip
        moved with demo mode's clock and came back, else ``unverified``; ``overridden`` only when
        ``target.statusBarCheck`` is false (applied, not looked at)."""
        if not self.MANAGES_DEVICE or device.get("kind") in ("tv", "watch"):
            return "none"
        if mode != "clean":
            if self.changed.get("demo"):
                self.shell("am", "broadcast", "-a", DEMO, "-e", "command", "exit")
                self.changed["demo"] = False
            return "none"
        t = device.get("target") or {}
        if "demoAllowed" not in self.changed:
            self.changed["demoAllowed"] = self.shell("settings", "get", "global", "sysui_demo_allowed", quiet=True,
                                                     dry_output="null").out.strip()
        self.shell("settings", "put", "global", "sysui_demo_allowed", "1")
        # The first pass after a boot can leave the real Wi-Fi icon beside demo mode's (two Wi-Fi icons on an
        # API 36 image, seen 2026-11-14): the first time, enter, leave and enter again.
        passes = 1 if self.changed.get("demo") else 2
        self.changed["demo"] = True
        for n in range(passes):
            if n:
                self.shell("am", "broadcast", "-a", DEMO, "-e", "command", "exit")
            for extra in demo_commands(clock, mobile=bool(t.get("statusBarMobile"))):
                self.shell("am", "broadcast", "-a", DEMO, "-e", *extra)
        if t.get("statusBarCheck") is False:
            return "overridden"
        return self.check_status_bar(device, clock, shot)

    def status_rows(self, device):
        """How many rows from the top the status bar takes: 24 dp at the density (``target.density``, else ``wm
        density``), at most a tenth of the screen."""
        dpi = (device.get("target") or {}).get("density")
        if not dpi:
            out = self.shell("wm", "density", check=False, quiet=True, dry_output="Physical density: 420").out
            found = parse_size(out, "Override") or parse_size(out, "Physical")
            dpi = int(found) if found and found.isdigit() else 420
        height = self.size(device)[1]
        return max(8, min(height // 10, int(round(24 * float(dpi) / 160.0))))

    def steady_strip(self, device, rows, tries=6):
        """The top ``rows`` rows once two reads in a row agree (the bar redraws a moment after a broadcast), at
        most ``tries`` reads; the last read if they never agree, ``None`` when it can't be read."""
        last = None
        for n in range(tries):
            strip = self.top_strip(device, rows)
            if strip is None or strip == last:
                return strip
            last = strip
            base.sleep(0.4)
        return last

    def top_strip(self, device, rows):
        """The top ``rows`` rows of a screenshot now, as RGB bytes (``None`` when it can't be read)."""
        path = os.path.join(self.options.workdir, ".statusbar-%s.png" % device["id"])
        try:
            os.makedirs(self.options.workdir, exist_ok=True)
            self.screenshot(device, path)
            if png is None:
                return None
            width, height, rgb = png.decode_rgb(path)
            return rgb[:width * 3 * min(rows, height)]
        except (base.DriverError, OSError, ValueError):
            return None
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def check_status_bar(self, device, clock, shot):
        """Look at the pixels: the status bar's strip now, with demo mode's clock moved to another time, and with
        it put back. ``verified`` when the strip changed with the clock and came back (demo mode draws the bar);
        ``unverified`` when it didn't change (demo mode ignored: some makers' skins, a SystemUI that crashed) or
        kept changing (an animation behind it), with a warning. The icons themselves are still for a person to
        look at."""
        if base.DRY_RUN:
            base.note("  (dry run: the status bar would be checked: demo mode's clock moved to %s and back, the "
                      "strip compared)" % other_clock(clock))
            return "verified"
        rows = self.status_rows(device)
        before = self.steady_strip(device, rows)
        self.shell("am", "broadcast", "-a", DEMO, "-e", "command", "clock", "-e", "hhmm", other_clock(clock))
        moved = self.steady_strip(device, rows)
        self.shell("am", "broadcast", "-a", DEMO, "-e", "command", "clock", "-e", "hhmm", demo_clock(clock))
        after = self.steady_strip(device, rows)
        if before is None or moved is None or after is None:
            shot.warnings.append("couldn't read the status bar's pixels to check demo mode: look at it")
            return "unverified"
        if moved == before:
            shot.warnings.append("the status bar didn't change when demo mode's clock did: demo mode may be "
                                 "ignored on this device; look at the picture's status bar")
            return "unverified"
        if after != before:
            shot.warnings.append("the status bar's strip kept changing (something animating behind it): demo mode "
                                 "couldn't be confirmed; look at the picture's status bar")
            return "unverified"
        return "verified"

    def script_env(self, device):
        """A ``script`` step gets the device's serial as ``ANDROID_SERIAL`` (adb honours it) and
        ``APPSTORES_SERIAL``."""
        return {"ANDROID_SERIAL": self.serial or "", "APPSTORES_SERIAL": self.serial or ""}

    def inspect_tree(self, ctx):
        """The ``uiautomator dump`` XML (``capture.py --inspect``)."""
        self.shell("uiautomator", "dump", UI_DUMP, check=False, quiet=True, timeout=60)
        return self.adb_run("exec-out", "cat", UI_DUMP, quiet=True, timeout=60).out

    # -- elements -------------------------------------------------------------------------------------------

    def dump(self):
        """The UI tree: ``uiautomator dump`` to the device, then read it back. Returns ``(root, elements)``."""
        self.shell("uiautomator", "dump", UI_DUMP, check=False, quiet=True, timeout=60)
        xml = self.adb_run("exec-out", "cat", UI_DUMP, quiet=True, timeout=60).out
        return base.parse_uiautomator(xml)

    def find(self, ctx, query):
        """An element on screen now by ``id``, ``text``, ``label`` or ``xpath``, or ``None``."""
        if base.DRY_RUN:
            w, h = self.size(ctx.device)
            base.LOG("  (dry run: %s %r taken as found, at the screen's middle)" % query)
            return base.Element(id=str(query[1]), bounds=(0, 0, w, h))
        root, elements = self.dump()
        finder, wanted = query
        if finder == "xpath":
            return base.find_xpath(root, wanted)
        return base.find_element(elements, finder, wanted)

    def size(self, device):
        """The screen's size in pixels as ``(width, height)``."""
        m = re.match(r"(\d+)x(\d+)", self.screen_size or "")
        if m:
            return int(m.group(1)), int(m.group(2))
        return device["width"], device["height"]

    # -- steps ------------------------------------------------------------------------------------------------

    def step_launch(self, ctx, value):
        """``am start -W -S -n <package>/<activity>`` with the seed and the screen's args as extras."""
        value = value or {}
        app = ctx.device.get("app") or {}
        package, activity = app.get("package"), app.get("activity")
        if not package or not activity:
            raise base.StepFailed("step %d: launch needs the plan's app.android.package and app.android.activity"
                                  % ctx.index)
        if value.get("clean"):
            self.shell("pm", "clear", package)
        missing = sorted(set(value.get("env") or {}) - set(value.get("args") or {}))
        if missing:
            ctx.warn("Android apps get no environment variables: pass %s as args (extras) instead"
                     % ", ".join(missing))
        args = {}
        seed = ctx.screen.get("seed") if ctx.screen.get("seed") is not None else ctx.device.get("seed")
        if seed is not None:
            args["ScreenshotSeed"] = str(seed)
        args.update(value.get("args") or {})
        component = "%s/%s" % (package, activity)
        res = self.shell("am", "start", "-W", "-S", "-n", component, *extras(args), timeout=120)
        if "Error" in res.out or "Exception" in res.out:
            raise base.StepFailed("step %d: am start %s: %s" % (ctx.index, component, res.out.strip()[-300:]))
        self.launched = True

    def step_appFile(self, ctx, value):
        """``appFile``: push ``file`` and copy it to ``into`` inside the app's own data folder (``files/…``,
        ``cache/…``, ``databases/…``, relative to ``/data/data/<package>``) through ``run-as``, so only a debuggable
        build; the app stopped first and the file it replaces (and a database's ``-wal``/``-shm``) removed."""
        src, rel = app_file_paths(self, ctx, value, "android")
        package = (ctx.device.get("app") or {}).get("package")
        if not package:
            raise base.StepFailed("step %d: appFile needs the plan's app.android.package" % ctx.index)
        staged = "/data/local/tmp/appstores-%s" % os.path.basename(rel)
        self.shell("am", "force-stop", package, check=False)
        self.adb_run("push", src, staged, timeout=300)
        folder = rel.rsplit("/", 1)[0] if "/" in rel else "."
        script = "mkdir -p %s && rm -f %s %s-wal %s-shm %s-journal && cp %s %s" % (
            shlex.quote(folder), shlex.quote(rel), shlex.quote(rel), shlex.quote(rel), shlex.quote(rel),
            shlex.quote(staged), shlex.quote(rel))
        res = self.shell("run-as", package, "sh", "-c", script, check=False, timeout=120)
        self.shell("rm", "-f", staged, check=False, quiet=True)
        text = (res.out or "") + (res.err or "")
        if not res.ok or "not debuggable" in text or "unknown package" in text.lower():
            raise base.StepFailed("step %d: appFile: run-as %s couldn't copy into the app's data (%s): it works only "
                                  "on a debuggable (debug) build" % (ctx.index, package, text.strip()[:200]))

    def step_deepLink(self, ctx, value):
        """``am start -W -a android.intent.action.VIEW -d <url> [<package>]``."""
        url = value.get("url") if isinstance(value, dict) else value
        package = (ctx.device.get("app") or {}).get("package")
        args = ["am", "start", "-W", "-a", "android.intent.action.VIEW", "-d", url]
        if package:
            args.append(package)
            self.launched = True
        res = self.shell(*args, timeout=120)
        if "Error" in res.out:
            raise base.StepFailed("step %d: %s" % (ctx.index, res.out.strip()[-300:]))

    def step_url(self, ctx, value):
        """Open a URL in whatever handles it (``am start -a android.intent.action.VIEW -d <url>``)."""
        res = self.shell("am", "start", "-W", "-a", "android.intent.action.VIEW", "-d", value, timeout=120)
        if "Error" in res.out:
            raise base.StepFailed("step %d: %s" % (ctx.index, res.out.strip()[-300:]))

    def _point(self, ctx, value, what):
        if isinstance(value, dict) and "x" in value and "y" in value:
            return int(value["x"]), int(value["y"])
        query = base.element_query(value)
        if query is None:
            raise base.StepFailed("step %d: %s needs an element (id, text, label, xpath) or x and y" % (ctx.index, what))
        el = self.wait_for(ctx, query, (value or {}).get("timeout"))
        if el.center is None:
            raise base.StepFailed("step %d: %s %r has no bounds to %s" % (ctx.index, query[0], query[1], what))
        return el.center

    def step_tap(self, ctx, value):
        """``input tap x y`` at an element's middle (or the given point)."""
        x, y = self._point(ctx, value, "tap")
        self.shell("input", "tap", x, y)

    def step_type(self, ctx, value):
        """Tap the field if one's named, then ``input text``."""
        query = base.step_element("type", value)
        target = {query[0]: query[1], "timeout": value.get("timeout")} if query else None
        if target:
            self.step_tap(ctx, target)
        self.shell("input", "text", input_text(value["text"]))

    def _swipe_for(self, ctx, direction):
        w, h = self.size(ctx.device)
        cx, cy = w // 2, h // 2
        dx, dy = int(w * 0.3), int(h * 0.25)
        # The finger moves against the way the content scrolls.
        return {"down": (cx, cy + dy, cx, cy - dy), "up": (cx, cy - dy, cx, cy + dy),
                "right": (cx + dx, cy, cx - dx, cy), "left": (cx - dx, cy, cx + dx, cy)}[direction]

    def step_scroll(self, ctx, value):
        """Scroll ``direction`` (``times``), or until the element ``to`` is on screen (at most ``times``, 10)."""
        value = value or {}
        direction = value.get("direction") or "down"
        times = int(value.get("times") or (10 if value.get("to") else 1))
        target = base.element_query(value.get("to")) if value.get("to") else None
        for _ in range(times):
            if target and self.find(ctx, target):
                return
            self.shell("input", "swipe", *(self._swipe_for(ctx, direction) + (400,)))
            base.sleep(0.4)
        if target and not self.find(ctx, target):
            raise base.StepFailed("step %d: scrolled %s %d times and %s %r didn't appear"
                                  % (ctx.index, direction, times, target[0], target[1]))

    def step_back(self, ctx, value):
        """``input keyevent KEYCODE_BACK``."""
        self.shell("input", "keyevent", "KEYCODE_BACK")

    def step_swipe(self, ctx, value):
        """``input swipe`` from ``from`` to ``to`` (pixels) over ``ms``, or a ``direction``."""
        ms = int(value.get("ms") or 300)
        if value.get("from") and value.get("to"):
            coords = tuple(int(v) for v in list(value["from"]) + list(value["to"]))
        else:
            coords = self._swipe_for(ctx, value.get("direction") or "up")
        self.shell("input", "swipe", *(coords + (ms,)))

    def screenshot(self, device, path):
        """``adb exec-out screencap -p [-d <display>]`` written to ``path``."""
        args = ["exec-out", "screencap", "-p"]
        display = (device.get("target") or {}).get("display")
        if display is not None:
            args += ["-d", str(display)]
        res = self.adb_run(*args, binary=True, timeout=60)
        if base.DRY_RUN:
            return
        if not res.out.startswith(b"\x89PNG"):
            raise base.DriverError("screencap didn't return a PNG: %r" % res.out[:120])
        with open(path, "wb") as f:
            f.write(res.out)


DRIVER = AdbDriver
