"""The ``adb`` driver: Android phones, tablets, TV, Wear and Fire devices, emulators or real ones, through ``adb``.

Which device (``target``):

- ``serial``: a device or emulator already connected (``adb devices``). It's the person's: it's never stopped or
  deleted, and everything changed on it is put back.
- ``avd``: an emulator by AVD name; one already running is used as it is, else it's started headless
  (``emulator -avd … -no-window -no-audio -no-boot-anim -no-snapshot-save``; ``readOnly: true`` adds
  ``-read-only`` so the AVD's disk is never written) and stopped after.
- ``systemImage`` (and ``profile``, a device definition such as ``medium_phone``): an AVD of our own,
  ``appstores-<device id>``, created with ``avdmanager`` if it isn't there and deleted with ``--cleanup``. With
  ``avd`` too, named ``appstores-…``, that AVD is created when it isn't there (two postures of one foldable can
  share one). Before ``avdmanager`` runs (and in ``--dry-run``), the image is looked for in the SDK in use
  (``$ANDROID_HOME``, else ``$ANDROID_SDK_ROOT``): ``<sdk>/system-images/android-36/google_apis/arm64-v8a/`` with a
  ``system.img`` (or ``source.properties``). When it isn't there the device fails once, naming the SDK and the
  other SDK folders that have it (``$ANDROID_SDK_ROOT``, ``$ANDROID_HOME``, ``SDK_DEFAULTS``), instead of
  avdmanager's "Package path is not valid. Valid system image paths are: null".

What it does (CONTRACT.md 10.3, 10.5):

- ``prepare``: boot (poll until ``sys.boot_completed`` is 1), lay out at the device's size (``wm size
  <width>x<height>``, or ``target.wmSize``; ``null`` leaves it; ``target.density`` for ``wm density``), turn
  animations off, switch the navigation mode (``target.navigation``: ``gesture``, ``threebutton``), install
  ``app.apk`` (``install -r``; a .NET debug APK built for Fast Deployment, with no assemblies inside, is warned
  about), and grant the plan's ``staging.permissions`` (``pm grant``; revoked in ``reset``).
- tools: ``target.adb``, ``target.emulator`` and ``target.avdmanager`` name them; else ``$ANDROID_HOME`` (or
  ``$ANDROID_SDK_ROOT``)'s ``platform-tools``, ``emulator`` and ``cmdline-tools/latest/bin`` (or the newest
  ``cmdline-tools/<version>/bin``, then ``tools/bin``), else ``PATH``. The emulator is started with
  ``ANDROID_SDK_ROOT`` set to ``$ANDROID_HOME`` when only that is set (it fails "Cannot find AVD system path.
  Please define ANDROID_SDK_ROOT" otherwise).
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
  (``input``; a swipe's ``hold``: ``input motionevent`` DOWN, MOVE, UP), ``wait``/``scroll`` with elements found in ``uiautomator dump`` by ``id`` (resource id), ``text``,
  ``label`` (content description) or ``xpath``; ``appFile`` (a file pushed into the app's own data folder through
  ``run-as``: debug builds only).
- foldables (``posture``: ``folded``, ``open``, ``half-open``; the device's setting, a screen's, or a ``posture``
  step): the emulator's console (``adb emu fold``, ``emu unfold``, ``emu posture 2`` with ``emu sensor set
  hinge-angle0 <target.hingeAngle>``), a real device's ``cmd device_state state <id>`` (``state reset`` after),
  checked with ``cmd device_state print-state``. A posture change locks the screen and moves the app to another
  physical display, so after one (once ``sys.boot_completed`` is 1) the screen is woken and unlocked (``input
  keyevent KEYCODE_WAKEUP``, ``wm dismiss-keyguard``, then ``input keyevent 82`` too), tried again with a longer
  wait each time (``KEYGUARD_WAITS``: right after a cold boot the first try can come too early), the display in
  use is found again, ``wm size``/``wm density`` are set again on it (each physical display keeps its own
  override, and each is put back), and demo mode is applied again.
- the keyboard: ``hideKeyboard`` presses back only while ``dumpsys input_method`` says the keyboard is up
  (``mInputShown``); ``verify``'s keyboard check reads the same.
- screenshot: ``adb exec-out screencap -p`` with ``-d <display>``: ``target.display`` (SurfaceFlinger's long id,
  ``dumpsys SurfaceFlinger --display-id``), or on a device with more than one physical display the one in use
  (``dumpsys display``'s active viewport for display 0). Text a screencap prints before the PNG is dropped.
- recording (``capture.py --record``): ``screenrecord --bit-rate 20000000 --time-limit 180 [--display-id …]`` on the
  device (the display the screenshots take) from the screen's first ``launch`` until a second after its last step,
  stopped with ``pkill -INT screenrecord`` before ``verify``, the screenshot and ``reset``, then pulled and deleted
  from the device. It stops by itself at 180 s (a warning says so); no flush is needed.
- ``reset``: leave demo mode, put back the display size and density (on each display it changed), the posture,
  dark mode, language and animation scales, stop the app, stop an emulator it started, and with ``--cleanup``
  delete its own AVD.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
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
# A posture's device state (cmd device_state print-states) and the emulator console's command for it.
POSTURE_STATES = {"folded": "CLOSED", "open": "OPENED", "half-open": "HALF_OPENED"}
STATE_POSTURES = dict((v, k) for k, v in POSTURE_STATES.items())
CONSOLE_POSTURES = {"folded": ("fold",), "open": ("unfold",), "half-open": ("posture", "2")}
DRY_STATES = {"CLOSED": 0, "HALF_OPENED": 1, "OPENED": 2}
HOLD_MOVES = 5                # MOVE events a held swipe goes through on its way (input motionevent)
NO_MOTIONEVENT = re.compile(r"(?i)unknown command|usage: input")   # an input without motionevent (older Android)
# Where an Android SDK usually is when no variable names it (Android Studio's default; on a Mac also the Homebrew
# android-commandlinetools cask's), by sys.platform prefix: only to say where a system image missing from the SDK in
# use *is*. ~ and %VARIABLES% are expanded.
SDK_DEFAULTS = {
    "darwin": ("~/Library/Android/sdk", "/opt/homebrew/share/android-commandlinetools",
               "/usr/local/share/android-commandlinetools"),
    "linux": ("~/Android/Sdk",),
    "win32": ("%LOCALAPPDATA%\\Android\\Sdk",),
}
# A system image's folder holds one of these once it's installed (an interrupted download leaves neither).
IMAGE_FILES = ("system.img", "source.properties")
STATUS_ICONS = ("bluetooth", "volume", "alarm", "location", "sync", "mute", "speakerphone", "zen", "eri", "tty",
                "cast", "hotspot")


def sdk_in_use():
    """The Android SDK the driver takes its tools from (and avdmanager and the emulator read), as ``(folder,
    variable)``: ``$ANDROID_HOME``, else ``$ANDROID_SDK_ROOT``; ``(None, None)`` when neither is set (the tools on
    ``PATH`` then find their own SDK)."""
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(var):
            return os.environ[var], var
    return None, None


def image_dir(sdk, package):
    """A system image's folder in an SDK: ``system-images;android-36;google_apis;arm64-v8a`` ->
    ``<sdk>/system-images/android-36/google_apis/arm64-v8a``; ``None`` for a package id that isn't a system image."""
    parts = [p for p in (package or "").split(";") if p]
    if len(parts) < 2 or parts[0] != "system-images":
        return None
    return os.path.join(sdk, *parts)


def image_installed(sdk, package):
    """True when the SDK folder ``sdk`` has the system image ``package`` installed (``IMAGE_FILES`` in its folder)."""
    folder = image_dir(sdk, package)
    return bool(folder) and any(os.path.isfile(os.path.join(folder, f)) for f in IMAGE_FILES)


def sdk_folders():
    """The SDK folders worth looking in, each once: ``$ANDROID_SDK_ROOT``, ``$ANDROID_HOME``, then this system's
    ``SDK_DEFAULTS``; only those that exist."""
    paths = [os.environ.get("ANDROID_SDK_ROOT"), os.environ.get("ANDROID_HOME")]
    for prefix, defaults in SDK_DEFAULTS.items():
        if sys.platform.startswith(prefix):
            paths += [os.path.expanduser(os.path.expandvars(p)) for p in defaults]
    out, seen = [], set()
    for p in paths:
        if not p or not os.path.isdir(p):
            continue
        real = os.path.realpath(p)
        if real not in seen:
            seen.add(real)
            out.append(p)
    return out


def sdks_with_image(package, besides=None):
    """The SDK folders (``sdk_folders``) other than ``besides`` that have the system image ``package``."""
    skip = os.path.realpath(besides) if besides else None
    return [p for p in sdk_folders() if os.path.realpath(p) != skip and image_installed(p, package)]


def image_advice(package, sdk):
    """What to do about a system image missing from the SDK ``sdk`` (``None``: the one the tools on PATH use): the
    other SDK folders that have it, and how to install it."""
    others = sdks_with_image(package, sdk)
    install = "sdkmanager %s\"%s\"" % ("--sdk_root=%s " % shlex.quote(sdk) if sdk else "", package)
    if others:
        return ("it's installed in %s: run with ANDROID_HOME=%s ANDROID_SDK_ROOT=%s, or install it in this SDK: %s"
                % (" and ".join(others), shlex.quote(others[0]), shlex.quote(others[0]), install))
    return ("no other SDK folder looked in has it (%s): install it (%s), or point ANDROID_HOME and ANDROID_SDK_ROOT "
            "at an SDK that has it" % (", ".join(sdk_folders()) or "none found", install))


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


def parse_states(output):
    """``cmd device_state print-states`` as ``{"CLOSED": 0, "HALF_OPENED": 1, "OPENED": 2, …}``."""
    return dict((name, int(ident)) for ident, name in
                re.findall(r"identifier=(\d+),\s*name='([A-Z_]+)'", output or ""))


def parse_displays(output):
    """The physical display ids ``dumpsys SurfaceFlinger --display-id`` lists (``Display 4619827259835644672 …``)."""
    return re.findall(r"^Display (\d+)", output or "", re.M)


def active_display(output):
    """The physical display behind display 0 now (``dumpsys display``): the active viewport's
    ``uniqueId='local:<id>'``, else the one display device whose state is ON; ``None`` when it can't tell."""
    m = re.search(r"isActive=true, displayId=0, uniqueId='local:(\d+)'", output or "")
    if m:
        return m.group(1)
    on = re.findall(r"mPhysicalDisplayId=(\d+)\s+mState=ON", output or "")
    return on[0] if len(set(on)) == 1 else None


# The classes of the views a person types into, as the dump names them (a .NET MAUI Entry and Compose's TextField
# are EditTexts too).
EDITABLE = ("EditText", "AutoCompleteTextView", "TextInputEditText", "SearchAutoComplete")


def focused_text_field(elements):
    """The dump's text field that has the focus (``focused="true"`` on an EditText or the like), or ``None``."""
    for el in elements:
        if el.attrs.get("focused") == "true" and any(k in (el.cls or "") for k in EDITABLE):
            return el
    return None


def same_field(a, b):
    """True when two dumps' elements are the same field (its id, else its class and bounds)."""
    if a.id:
        return a.id == b.id
    return a.cls == b.cls and a.bounds == b.bounds


def keyboard_up(output):
    """Whether ``dumpsys input_method`` says the keyboard is showing (``mInputShown=true``, or ``mImeWindowVis``
    with its visible bit); ``None`` when it says neither."""
    if re.search(r"mInputShown=true", output or ""):
        return True
    vis = [int(v) for v in re.findall(r"mImeWindowVis=(\d+)", output or "")]
    if any(v & 2 for v in vis):
        return True
    if re.search(r"mInputShown=false", output or "") or vis:
        return False
    return None


def keyboard_fullscreen(output):
    """Whether ``dumpsys input_method`` says the keyboard is in full-screen (extract) mode: the input method's own
    ``mIsFullscreen=true``. Android does it for text entry in landscape on phones, open foldables and some tablets:
    the keyboard and its own copy of the field cover the whole screen, so a tap meant for the app lands on the
    keyboard. ``None`` when it doesn't say."""
    if re.search(r"mIsFullscreen=true", output or ""):
        return True
    if re.search(r"mIsFullscreen=false", output or ""):
        return False
    return None


def parse_size(output, label):
    """``Physical size: 1080x2400`` (or ``density``) from ``wm size``/``wm density`` output, by its label."""
    m = re.search(r"%s (?:size|density): (\S+)" % label, output or "")
    return m.group(1) if m else None


class AdbDriver(base.Driver):
    """Android through ``adb`` (see the module's docstring)."""

    NAME = "adb"
    PLATFORMS = ("android",)
    STEPS = ("launch", "deepLink", "url", "appFile", "tap", "type", "wait", "scroll", "back", "swipe", "settle",
             "script", "posture", "hideKeyboard", "fill", "unfocus")
    FINDERS = ("id", "text", "label", "xpath")
    MANAGES_DEVICE = True     # the uiautomator driver leaves size, locale, appearance and status bar alone
    BOOT_TIMEOUT = 600
    POSTURE_TIMEOUT = 20     # seconds a posture change has to show in cmd device_state print-state
    KEYGUARD_WAITS = (2, 3, 5, 8)   # seconds each wake-and-unlock try waits for the lock screen to go after one

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
        self.display = None          # the physical display captured (on a device with more than one)
        self.sizes = {}              # display (None: the only one) -> {"wmSize": before, "density": before}
        self.display_posture = {}    # display -> the posture it was in use in (None: before any change)
        self.states = None           # cmd device_state print-states
        self.original_posture = None
        self.posture_changed = False
        self.demo_fresh = False      # demo mode to enter twice again (after a posture change)
        self.no_motionevent = False  # this device's input has no motionevent (a held swipe falls back)

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
            elif avd and t.get("systemImage") and avd.startswith(PREFIX):
                self.create_avd(avd, t)
            if not avd:
                raise base.DriverError("%s needs target.serial, target.avd or target.systemImage" % device["id"])
            self.info["avd"] = avd
            self.serial = self.running_avd(avd) or self.start_emulator(avd, t)
        self.wait_for_boot()
        sdk = self.shell("getprop", "ro.build.version.sdk", quiet=True, dry_output="36").out.strip()
        self.sdk = int(sdk) if sdk.isdigit() else 0
        self.info["android"] = "API %d" % self.sdk if self.sdk else None
        self.display = self.resolve_display(device)
        if self.MANAGES_DEVICE:
            if device.get("posture"):
                posture = base.posture_of(device["posture"])
                self.set_posture(device, posture)
                self.unlock(device, None)
                self.display = self.resolve_display(device)
                self.state["posture"] = posture
                self.info["posture"] = posture
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
        self.check_image(t["systemImage"])
        cmd = [avdmanager, "create", "avd", "-n", name, "-k", t["systemImage"]]
        if t.get("profile"):
            cmd += ["-d", t["profile"]]
        try:
            base.run(cmd, input="no\n", timeout=300)
        except base.CommandError as e:
            if "Package path is not valid" not in "%s %s" % (e.out or "", e.err or ""):
                raise
            raise base.DriverError("avdmanager couldn't find the system image %s in its SDK (\"Package path is not "
                                   "valid\"): %s" % (t["systemImage"], image_advice(t["systemImage"], sdk_in_use()[0])))
        self.avd_created = name

    def check_image(self, package):
        """Fail once, before ``avdmanager``, when the system image ``package`` isn't installed in the SDK in use
        (``sdk_in_use``), naming that SDK and the others that have it; skipped when no variable names an SDK or the
        package id isn't a system image's (avdmanager then says what it says)."""
        sdk, var = sdk_in_use()
        folder = image_dir(sdk, package) if sdk else None
        if not folder:
            return
        if image_installed(sdk, package):
            if base.DRY_RUN:
                base.note("  (the system image is installed: %s)" % folder)
            return
        raise base.DriverError("the system image %s isn't installed in the Android SDK in use, %s ($%s): %s has no %s; "
                               "%s" % (package, sdk, var, folder, " or ".join(IMAGE_FILES),
                                       image_advice(package, sdk)))

    def emulator_env(self):
        """``ANDROID_SDK_ROOT`` for the emulator when only ``$ANDROID_HOME`` names the SDK (an emulator that reads
        only ANDROID_SDK_ROOT fails "Cannot find AVD system path" otherwise); ``None`` when there's nothing to add."""
        home = os.environ.get("ANDROID_HOME")
        if home and not os.environ.get("ANDROID_SDK_ROOT"):
            return {"ANDROID_SDK_ROOT": home}
        return None

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
        self.proc = base.spawn(cmd, log_path=self.log_path, env=self.emulator_env())
        self.started = True
        return "emulator-%d" % int(port)

    def wait_for_boot(self, start_server=True):
        """Poll until the device answers and ``sys.boot_completed`` is 1 (a dropped adb server or a device still
        coming up is just "not yet"); an emulator this driver started that exits fails with its log's last lines."""

        def booted():
            if self.proc is not None and self.proc.poll() is not None:
                raise base.DriverError("the emulator exited (%s)%s" % (self.proc.poll(), self._log_tail()))
            res = self.shell("getprop", "sys.boot_completed", check=False, quiet=True, dry_output="1", timeout=30)
            return res.ok and res.out.strip() == "1"

        if start_server:
            base.run(self.adb + ["start-server"], check=False, quiet=True, timeout=60)
        base.poll(booted, self.BOOT_TIMEOUT, interval=2, what="%s to finish booting" % self.serial)

    def _log_tail(self, lines=8):
        if not self.log_path or not os.path.isfile(self.log_path):
            return ""
        with open(self.log_path, "rb") as f:
            text = f.read().decode("utf-8", "replace").strip().splitlines()
        return ": " + " / ".join(text[-lines:]) if text else ""

    def lay_out(self, device, t):
        """``wm size`` the device's size (and ``wm density``) on the display in use, remembering what to put back:
        each physical display keeps its own override, so a foldable's are remembered (and put back) one by one."""
        key = self.display
        saved = self.sizes.setdefault(key, {})
        self.display_posture.setdefault(key, self.state.get("posture"))
        wanted = t["wmSize"] if "wmSize" in t else "%dx%d" % (device["width"], device["height"])
        # Under --dry-run the device's own size isn't known: show the wm size a real run would set.
        out = self.shell("wm", "size", quiet=True, dry_output="Physical size: (the device's)").out
        physical, override = parse_size(out, "Physical"), parse_size(out, "Override")
        self.screen_size = wanted or override or physical
        if wanted and (override or physical) != wanted:
            saved.setdefault("wmSize", override or "reset")
            self.shell("wm", "size", wanted)
        if t.get("density"):
            out = self.shell("wm", "density", quiet=True, dry_output="").out
            override = parse_size(out, "Override")
            saved.setdefault("density", override or "reset")
            self.shell("wm", "density", str(t["density"]))

    # -- foldables ------------------------------------------------------------------------------------------------

    def is_emulator(self):
        return (self.serial or "").startswith("emulator-")

    def device_states(self):
        """``cmd device_state print-states`` (cached): a foldable has ``CLOSED`` and ``OPENED``."""
        if self.states is None:
            out = self.shell("cmd", "device_state", "print-states", check=False, quiet=True, dry_output="").out
            self.states = parse_states(out) or (dict(DRY_STATES) if base.DRY_RUN else {})
        return self.states

    def current_posture(self):
        """The posture the device is in now (``cmd device_state print-state``), or ``None``."""
        out = self.shell("cmd", "device_state", "print-state", check=False, quiet=True, dry_output="2").out.strip()
        names = dict((v, k) for k, v in self.device_states().items())
        name = names.get(int(out)) if out.isdigit() else None
        return STATE_POSTURES.get(name)

    def set_posture(self, device, posture):
        """Fold, unfold or half-open the device and wait until its device state says so: the emulator's console
        (``emu fold``/``unfold``/``posture 2`` and the hinge angle), a real foldable's ``cmd device_state state``."""
        states = self.device_states()
        want = POSTURE_STATES[posture]
        if "CLOSED" not in states or "OPENED" not in states:
            raise base.DriverError("%s isn't a foldable (cmd device_state print-states lists no CLOSED and OPENED): "
                                   "give the device a foldable profile (pixel_9_pro_fold) or leave posture out"
                                   % (self.serial,))
        if want not in states:
            raise base.DriverError("%s has no %s state (it has %s)" % (self.serial, want, ", ".join(sorted(states))))
        if self.original_posture is None:
            self.original_posture = self.current_posture() or "unknown"
        t = device.get("target") or {}
        if self.is_emulator():
            res = self.adb_run("emu", *CONSOLE_POSTURES[posture], check=False, timeout=30)
            if not res.ok or (res.out or "").strip().startswith("KO"):
                raise base.DriverError("the emulator's console refused %s: %s" % (
                    " ".join(CONSOLE_POSTURES[posture]), (res.out or res.err or "").strip()[:200]))
            if posture == "half-open":
                angle = t.get("hingeAngle") or 90
                self.adb_run("emu", "sensor", "set", "hinge-angle0", "%g" % float(angle), check=False, timeout=30)
        else:
            self.shell("cmd", "device_state", "state", str(states[want]))
            self.changed["deviceState"] = True
        self.posture_changed = True

        def there():
            out = self.shell("cmd", "device_state", "print-state", check=False, quiet=True, dry_output="").out
            return out.strip() == str(states[want])

        if not base.DRY_RUN:
            base.poll(there, self.POSTURE_TIMEOUT, interval=0.5, what="%s to be %s" % (self.serial, posture))

    def keyguard_showing(self):
        out = self.shell("dumpsys", "window", check=False, quiet=True, timeout=60, dry_output="").out
        m = re.search(r"isKeyguardShowing=(true|false)", out or "")
        return bool(m and m.group(1) == "true")

    def unlock(self, device, shot):
        """Wake the screen and dismiss the lock screen a fold brings up (an emulator's has no PIN; a person's
        device with one stays locked: a warning). Waits for ``sys.boot_completed`` first, then tries ``input
        keyevent KEYCODE_WAKEUP`` and ``wm dismiss-keyguard`` (and from the second try ``input keyevent 82``, which
        lifts a swipe lock screen) once per ``KEYGUARD_WAITS``, each waiting longer for ``isKeyguardShowing=false``:
        right after a cold boot a fold's lock screen can come back over the first dismiss."""
        if not base.DRY_RUN:
            self.wait_for_boot(start_server=False)
        tries = len(self.KEYGUARD_WAITS)
        for n, wait in enumerate(self.KEYGUARD_WAITS):
            self.shell("input", "keyevent", "KEYCODE_WAKEUP", check=False)
            self.shell("wm", "dismiss-keyguard", check=False)
            if n:
                self.shell("input", "keyevent", "82", check=False)
            if base.DRY_RUN:
                return
            try:
                base.poll(lambda: not self.keyguard_showing(), wait, interval=0.5, what="the lock screen to go")
            except base.StepFailed:
                continue
            if n:
                base.note("  the lock screen went on try %d of %d" % (n + 1, tries))
            return
        message = ("the lock screen is still up after the posture change (%d tries to wake and unlock it; a PIN?): "
                   "the next launch lands behind it; unlock %s by hand" % (tries, self.serial))
        if shot is not None:
            shot.warnings.append(message)
        else:
            self.warnings.append(message)
        base.note("  warning: %s" % message)

    def apply_posture(self, device, posture, shot):
        """Put the foldable in ``posture``, then make right what that undid: wake and unlock it, find the display
        now in use, lay out on it again, and apply demo mode again (entered twice, as after a boot)."""
        if not self.MANAGES_DEVICE:
            raise base.StepSkipped("the %s driver leaves the device as it is: use the adb driver to fold it"
                                   % self.NAME)
        self.set_posture(device, posture)
        self.unlock(device, shot)
        self.display = self.resolve_display(device)
        self.state["posture"] = posture
        self.info["posture"] = posture
        self.lay_out(device, device.get("target") or {})
        self.state.pop("statusBar", None)
        self.demo_fresh = True

    def resolve_display(self, device):
        """The physical display to capture: ``target.display`` when it names one; else, on a device with more than
        one (``dumpsys SurfaceFlinger --display-id``), the one in use; ``None`` on a device with one."""
        explicit = (device.get("target") or {}).get("display")
        if explicit not in (None, "", "auto"):
            return str(explicit)
        ids = parse_displays(self.shell("dumpsys", "SurfaceFlinger", "--display-id", check=False, quiet=True,
                                        dry_output="").out)
        if len(ids) <= 1:
            return None
        found = active_display(self.shell("dumpsys", "display", check=False, quiet=True, timeout=60,
                                          dry_output="").out)
        if found in ids:
            base.note("  capturing display %s (of %s: the one in use)" % (found, ", ".join(ids)))
            return found
        raise base.DriverError("%s has %d displays (%s) and which is in use couldn't be read from dumpsys display: "
                               "set target.display to one" % (self.serial, len(ids), ", ".join(ids)))

    def restore_posture(self, posture):
        """Back to ``posture`` (reset): the console on an emulator, ``cmd device_state state reset`` on a device."""
        if not self.is_emulator():
            self.shell("cmd", "device_state", "state", "reset")
            return
        if posture in CONSOLE_POSTURES:
            self.adb_run("emu", *CONSOLE_POSTURES[posture], check=False, timeout=30)
            states = self.device_states()
            want = str(states.get(POSTURE_STATES[posture], ""))
            try:
                base.poll(lambda: self.shell("cmd", "device_state", "print-state", check=False, quiet=True,
                                             dry_output=want).out.strip() == want,
                          self.POSTURE_TIMEOUT, interval=0.5, what="%s to be %s again" % (self.serial, posture))
            except base.StepFailed:
                pass

    # -- the keyboard -------------------------------------------------------------------------------------------

    def keyboard_shown(self, ctx):
        """``dumpsys input_method``: is the keyboard up (``None`` when it doesn't say)."""
        if base.DRY_RUN:
            return None
        out = self.shell("dumpsys", "input_method", check=False, quiet=True, timeout=60).out
        return keyboard_up(out)

    def keyboard_state(self):
        """``(shown, fullscreen)`` from one ``dumpsys input_method`` (each ``None`` when it doesn't say)."""
        out = self.shell("dumpsys", "input_method", check=False, quiet=True, timeout=60).out
        return keyboard_up(out), keyboard_fullscreen(out)

    def hide_keyboard(self, ctx, value):
        """Close the keyboard: the back key, pressed only while the keyboard is up (with it down, back would
        navigate). A full-screen (landscape, extract-mode) keyboard closes the same way, with its field."""
        if base.DRY_RUN:
            base.note("  (dry run: the back key would be pressed if dumpsys input_method says the keyboard is up)")
            return
        shown, full = self.keyboard_state()
        if shown is None:
            raise base.StepFailed("step %d: hideKeyboard: dumpsys input_method doesn't say whether the keyboard is "
                                  "up, so back wasn't pressed (it might navigate): give hideKeyboard a tap" % ctx.index)
        if not shown:
            return
        if full:
            base.note("  the keyboard is up full screen (landscape text entry): back closes it")
        self.shell("input", "keyevent", "KEYCODE_BACK")
        base.poll(lambda: self.keyboard_shown(ctx) is False, 3, interval=0.3, what="the keyboard to close")

    def focused_field(self, ctx):
        """The text field with the focus now, from the dump (``focused="true"``), or ``False``."""
        if base.DRY_RUN:
            return None
        _, elements = self.dump()
        return focused_text_field(elements) or False

    def clear_focus(self, ctx):
        """Clear a text field's focus (its caret blinks in a shot otherwise; back closes the keyboard, not the
        focus): the keyboard closed first (back, only while it's up), then Escape, which newer Android versions
        take to clear the focus, pressed only while a text field has it. The dump is read again after: the field
        unfocused is ``True``; the field gone means Escape went back instead (an older Android, or an app that
        doesn't take it), a ``StepFailed`` saying to give ``unfocus`` a tap; still focused is ``False`` with a
        warning."""
        if base.DRY_RUN:
            base.note("  (dry run: if the dump shows a text field with the focus, the keyboard closed and Escape "
                      "pressed, then the dump read again)")
            return None
        _, elements = self.dump()
        field = focused_text_field(elements)
        if field is None:
            return False
        if self.keyboard_shown(ctx):
            self.hide_keyboard(ctx, True)
            _, elements = self.dump()
            field = focused_text_field(elements)
            if field is None:
                return True
        self.shell("input", "keyevent", "KEYCODE_ESCAPE")
        base.sleep(0.3)
        _, after = self.dump()
        if not any(same_field(field, el) for el in after):
            raise base.StepFailed("step %d: unfocus: the screen changed when Escape was pressed to clear %s's "
                                  "focus (Escape may have gone back here): give unfocus a tap (a title or label "
                                  "outside the field) instead" % (ctx.index, base.describe_element(field)))
        still = focused_text_field(after)
        if still is not None and same_field(field, still):
            ctx.warn("step %d: %s kept the focus after Escape: give unfocus a tap (a title or label outside the "
                     "field), and look at the picture for a caret" % (ctx.index, base.describe_element(field)))
            return False
        return True

    def clear_fullscreen_keyboard(self, ctx):
        """Before a tap: a keyboard up full screen (``keyboard_fullscreen``) covers the app, so a tap meant for a
        button behind it (a sheet's Done) would land on the keyboard. Close it first, with the back key, only
        while it's up (the field keeps what was typed), and say so. Returns True when it closed one. A keyboard
        that covers only part of the screen is left as it is (a tap on an input accessory's Done is meant)."""
        if base.DRY_RUN:
            return False
        shown, full = self.keyboard_state()
        if not (shown and full):
            return False
        base.note("  the keyboard is up full screen (landscape text entry): closed first, or the tap would land on it")
        self.shell("input", "keyevent", "KEYCODE_BACK")
        try:
            base.poll(lambda: self.keyboard_shown(ctx) is False, 3, interval=0.3, what="the keyboard to close")
        except base.StepFailed:
            ctx.warn("step %d: the full-screen keyboard didn't close before the tap: add a hideKeyboard step before "
                     "it" % ctx.index)
        return True

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
        self.restore_sizes(warnings, attempt)
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

    def restore_sizes(self, warnings, attempt):
        """Put back each display's size and density, in the posture it was in use in, then the posture."""

        def put_back(key, where):
            saved = self.sizes.get(key) or {}
            if "density" in saved:
                attempt("restoring the density%s" % where, "wm", "density", saved["density"])
            if "wmSize" in saved:
                attempt("restoring the display size%s" % where, "wm", "size", saved["wmSize"])

        original = self.original_posture
        first = [k for k in self.sizes if self.display_posture.get(k) not in (None, original)]
        for key in first:
            posture = self.display_posture[key]
            try:
                if self.is_emulator():
                    self.restore_posture(posture)
                else:
                    self.shell("cmd", "device_state", "state", str(self.device_states()[POSTURE_STATES[posture]]))
                put_back(key, " of display %s (%s)" % (key, posture))
            except (base.DriverError, KeyError) as e:
                warnings.append("restoring display %s (%s): %s" % (key, posture, e))
        if self.posture_changed:
            try:
                self.restore_posture(original if original in POSTURE_STATES else "open")
            except base.DriverError as e:
                warnings.append("restoring the posture (%s): %s" % (original, e))
        for key in self.sizes:
            if key not in first:
                put_back(key, "" if key is None else " of display %s" % key)

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
        passes = 1 if self.changed.get("demo") and not self.demo_fresh else 2
        self.changed["demo"] = True
        self.demo_fresh = False
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

    def find_containing(self, ctx, query, wanted):
        """An element ``query`` finds that shows ``wanted`` (its ``text`` or ``content-desc``, or a descendant's:
        a chip whose number is on a child), from one dump; ``None`` when there's none."""
        if base.DRY_RUN:
            return self.find(ctx, query)
        root, elements = self.dump()
        return base.first_containing(root, elements, query, wanted)

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
        """``input tap x y`` at an element's middle (or the given point); a keyboard up full screen is closed first
        (``clear_fullscreen_keyboard``), or the tap would land on it."""
        self.clear_fullscreen_keyboard(ctx)
        x, y = self._point(ctx, value, "tap")
        self.shell("input", "tap", x, y)

    TYPES_AT_A_RATE = True
    SCROLL_SWIPES = True

    def step_type(self, ctx, value):
        """Tap the field if one's named, then ``input text``. With ``rate`` (keys a second), one ``input text`` a
        character, paced (each also takes the device a moment to start, so the pace is at most ``rate``)."""
        query = base.step_element("type", value)
        target = {query[0]: query[1], "timeout": value.get("timeout")} if query else None
        rate = self.rate_of(ctx, value)
        if target:
            self.step_tap(ctx, target)
        text = str(value["text"])
        if rate:
            input_text(text)        # refuse what it can't type before typing any of it
            base.note("  typing %r key by key, %g a second" % (text, rate))
            for n, key in enumerate(text):
                if n:
                    base.sleep(1.0 / rate)
                self.shell("input", "text", input_text(key))
            return
        self.shell("input", "text", input_text(text))

    def _swipe_for(self, ctx, direction, bounds=None):
        """A swipe's ``(x1, y1, x2, y2)`` across the screen's middle, or ``bounds``' (an element's: a pane)."""
        if bounds:
            left, top, right, bottom = bounds
            w, h = right - left, bottom - top
            cx, cy = left + w // 2, top + h // 2
        else:
            w, h = self.size(ctx.device)
            cx, cy = w // 2, h // 2
        dx, dy = int(w * 0.3), int(h * 0.25)
        # The finger moves against the way the content scrolls.
        return {"down": (cx, cy + dy, cx, cy - dy), "up": (cx, cy - dy, cx, cy + dy),
                "right": (cx + dx, cy, cx - dx, cy), "left": (cx - dx, cy, cx + dx, cy)}[direction]

    def scroll_once(self, ctx, direction, within=None):
        """``input swipe`` across the screen's middle, or within ``within``'s bounds (a pane), then a moment for it to
        come to rest."""
        bounds = within.bounds if within is not None else None
        if within is not None and not bounds:
            raise base.StepFailed("step %d: the element to scroll in has no bounds" % ctx.index)
        self.shell("input", "swipe", *(self._swipe_for(ctx, direction, bounds) + (400,)))
        base.sleep(0.4)

    def scroll_pane(self, ctx, query, found):
        """The nearest view that is ``query``'s element or holds it and is ``scrollable="true"`` in the dump (a
        ScrollView, a RecyclerView), with its bounds to swipe within."""
        root, elements = self.dump()
        hit = base.pane_in_tree(root, elements, query)
        if hit is None:
            return None
        node, how = hit
        a = node.attrib
        pane = base.Element(id=a.get("resource-id"), text=a.get("text"), label=a.get("content-desc"),
                            cls=a.get("class"), bounds=base.parse_bounds(a.get("bounds", "")), attrs=a, node=node)
        return pane, how, base.describe_node(node)

    def scroll_fingerprint(self, ctx, within=None):
        """The dump (what's on screen moves in it as the content scrolls; scroll bars don't)."""
        if base.DRY_RUN:
            return None
        self.shell("uiautomator", "dump", UI_DUMP, check=False, quiet=True, timeout=60)
        return self.adb_run("exec-out", "cat", UI_DUMP, quiet=True, timeout=60).out

    def step_back(self, ctx, value):
        """``input keyevent KEYCODE_BACK``."""
        self.shell("input", "keyevent", "KEYCODE_BACK")

    def step_swipe(self, ctx, value):
        """``input swipe`` from ``from`` to ``to`` (pixels) over ``ms``, or a ``direction``; with ``hold``, a held
        drag (``held_swipe``)."""
        ms = int(value.get("ms") or 300)
        hold = self.swipe_hold(ctx, value)
        if value.get("from") and value.get("to"):
            coords = tuple(int(v) for v in list(value["from"]) + list(value["to"]))
        else:
            coords = self._swipe_for(ctx, value.get("direction") or "up")
        if hold:
            self.held_swipe(ctx, coords, hold, ms)
            return
        self.shell("input", "swipe", *(coords + (ms,)))

    def held_swipe(self, ctx, coords, hold, ms):
        """A finger pressed at ``from`` for ``hold`` ms, then moved to ``to`` over ``ms``: ``input swipe`` can't
        hold, so ``input motionevent DOWN``, ``sleep``, ``HOLD_MOVES`` ``MOVE`` events along the way, ``UP``, in one
        shell line (the device keeps the time, not adb's round trips; each ``input`` takes a moment of its own, so
        the move may take a little longer than ``ms``). An ``input`` without ``motionevent`` (older Android: it
        answers "Unknown command") gets ``input swipe`` from ``from`` to itself over ``hold`` (a long press), then
        the swipe, with a warning: the finger lifts between them."""
        x1, y1, x2, y2 = coords
        if not self.no_motionevent:
            line = ["input motionevent DOWN %d %d" % (x1, y1), "sleep %g" % (hold / 1000.0)]
            for i in range(1, HOLD_MOVES + 1):
                line.append("input motionevent MOVE %d %d" % (int(round(x1 + (x2 - x1) * i / float(HOLD_MOVES))),
                                                              int(round(y1 + (y2 - y1) * i / float(HOLD_MOVES)))))
                if i < HOLD_MOVES:
                    line.append("sleep %g" % (ms / 1000.0 / HOLD_MOVES))
            line.append("input motionevent UP %d %d" % (x2, y2))
            res = base.run(self.adb + ["-s", self.serial, "shell", "; ".join(line)], check=False)
            if res.code == 0 and not NO_MOTIONEVENT.search((res.out or "") + (res.err or "")):
                return
            self.no_motionevent = True
        ctx.warn("step %d: this device's input has no motionevent (older Android), so the swipe's hold was a long "
                 "press, then the swipe, the finger lifted between: a slider may not move (drive this device with "
                 "appium)" % ctx.index)
        self.shell("input", "swipe", x1, y1, x1, y1, hold)
        self.shell("input", "swipe", x1, y1, x2, y2, ms)

    # -- recording (capture.py --record) ---------------------------------------------------------------------

    RECORD_LIMIT = 180                              # seconds: screenrecord's longest on most Android versions
    RECORD_REMOTE = "/sdcard/appstores-recording.mp4"

    def record_support(self, device):
        """Every Android device records (``screenrecord``)."""
        return None

    def capture_display(self, device):
        """The physical display the screenshots (and recordings) take: ``target.display``, else the one in use."""
        display = (device.get("target") or {}).get("display")
        if display in (None, "", "auto"):
            display = self.display
        return display

    def start_recording(self, device, path):
        """``adb shell screenrecord --bit-rate 20000000 --time-limit 180 [--display-id …] /sdcard/…`` in the
        background; it takes a moment to start."""
        display = self.capture_display(device)
        args = ["screenrecord", "--bit-rate", "20000000", "--time-limit", str(self.RECORD_LIMIT)]
        if display is not None:
            args += ["--display-id", str(display)]
        args.append(self.RECORD_REMOTE)
        line = " ".join(shlex.quote(str(a)) for a in args)
        if not base.DRY_RUN:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        log = path + ".log"
        proc = base.spawn(self.adb + ["-s", self.serial, "shell", line], log_path=log)
        started = base.CLOCK()
        base.sleep(1)
        if proc is not None and proc.poll() is not None:
            raise base.DriverError("screenrecord stopped as it started: %s" % (_read(log).strip()[-300:]
                                                                               or "it said nothing"))
        return {"proc": proc, "file": path, "log": log, "display": display, "started": started}

    def stop_recording(self, device, rec, shot):
        """A second for the last step's settled frames, then ``pkill -INT screenrecord`` (it finishes the file),
        pull it and delete it from the device. Raises ``DriverError`` without a file."""
        base.sleep(self.RECORD_TAIL)
        seconds = base.CLOCK() - rec["started"]
        if seconds > self.RECORD_LIMIT:
            shot.warnings.append("screenrecord stops at %d s and the steps took %.0f s: the recording ends before "
                                 "the last of them (shorten the steps' waits)" % (self.RECORD_LIMIT, seconds))
            seconds = float(self.RECORD_LIMIT)
        self.shell("pkill", "-INT", "screenrecord", check=False)
        proc = rec.get("proc")
        if proc is not None:
            try:
                proc.wait(timeout=30)
            except Exception:  # noqa: BLE001 - still running: stop the local adb; the file may be cut short
                base.stop(proc)
        try:
            self.adb_run("pull", self.RECORD_REMOTE, rec["file"], timeout=600)
        finally:
            self.shell("rm", "-f", self.RECORD_REMOTE, check=False)
        if not base.DRY_RUN and not (os.path.isfile(rec["file"]) and os.path.getsize(rec["file"]) > 0):
            raise base.DriverError("screenrecord left no video: %s" % (_read(rec["log"]).strip()[-300:]
                                                                      or "it said nothing"))
        return {"file": rec["file"], "seconds": round(seconds, 1), "by": "adb screenrecord",
                "display": None if rec.get("display") is None else str(rec["display"]), "flush": None}

    def discard_recording(self, device, rec):
        """Stop it on the device and delete its file there."""
        self.shell("pkill", "-INT", "screenrecord", check=False)
        base.stop(rec.get("proc"))
        self.shell("rm", "-f", self.RECORD_REMOTE, check=False)

    def screenshot(self, device, path):
        """``adb exec-out screencap -p [-d <display>]`` written to ``path``: ``target.display``, or the display in
        use on a device with more than one (``resolve_display``). A warning screencap prints before the PNG (a
        device with several displays and none named) is dropped."""
        args = ["exec-out", "screencap", "-p"]
        display = self.capture_display(device)
        if display is not None:
            args += ["-d", str(display)]
        res = self.adb_run(*args, binary=True, timeout=60)
        if base.DRY_RUN:
            return
        data = res.out
        start = data.find(b"\x89PNG")
        if start < 0:
            raise base.DriverError("screencap didn't return a PNG: %r" % data[:120])
        if start:
            base.note("  (screencap printed before the picture: %s)" % data[:start].decode("utf-8", "replace")
                      .strip().splitlines()[0][:160])
        with open(path, "wb") as f:
            f.write(data[start:])


def _read(path):
    """A log file's text (empty when it isn't there)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


DRIVER = AdbDriver
