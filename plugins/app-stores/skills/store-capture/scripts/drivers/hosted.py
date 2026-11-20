"""Drivers that reach screens inside the app (an in-app agent, Appium, a UI test, a Maestro flow) but leave the
device itself to the platform's own driver: its **host**.

The host (``simctl`` for iOS-family simulators, ``adb`` for Android, none for a Mac or Windows app; a device's
``target.host`` overrides it, ``"none"`` turns it off) finds or creates and boots the dedicated device, installs
the app, sets the locale, appearance and clean status bar, launches the app and opens deep links, and puts it all
back in ``reset``. The hosted driver adds what only it can do: finding elements, tapping, typing, scrolling,
running a flow. Screenshots come from the host too (the device's whole framebuffer, status bar included, at its
native size) unless ``target.screenshot`` is ``"agent"`` or there's no host.

So one ``target`` serves both: the host's settings (``deviceType``, ``runtime``, ``udid``, ``avd``, ``serial``,
``wmSize``, ``density``…) and the hosted driver's (``agentPort``, ``server``, ``capabilities``, ``scheme``…).
"""

from __future__ import annotations

from . import base

# The host a plan platform gets when its device's target doesn't say.
DEFAULT_HOSTS = {"ios": "simctl", "ipados": "simctl", "tvos": "simctl", "watchos": "simctl", "visionos": "simctl",
                 "android": "adb"}
# Steps the host does for a hosted driver (when the host has them): a foldable's posture is the device's, so the
# host's too (simctl through DevFlow's fold control, adb through the emulator's console or device_state).
HOST_STEPS = ("launch", "deepLink", "url", "appFile", "posture")


def type_target(value):
    """A ``type`` step's target as an element object: its ``id``/``label``/``xpath``/``css`` (not ``text``, which is
    what to type), or ``into`` (a field found by its text); ``{}`` for whatever has focus."""
    if not isinstance(value, dict):
        return {}
    if value.get("into"):
        return {"text": value["into"]}
    return dict((k, v) for k, v in value.items() if k in base.FINDER_KEYS and k != "text")


class HostedDriver(base.Driver):
    """A driver with an optional host driver for the device (see the module's docstring). Subclasses keep the
    base class's contract; this one forwards ``prepare``/``reset``, the locale, appearance and status bar, the
    launch/deep-link steps and the screenshot to the host when there is one."""

    HOST_STEPS = HOST_STEPS

    def __init__(self, options=None):
        """Set up; the host is made on first use."""
        base.Driver.__init__(self, options)
        self._host = None
        self._host_name = False   # False: not decided yet

    def capabilities(self):
        """The base's, plus ``throughHost``: the steps done only by the device's host (``simctl``/``adb``), so
        not on a device without one, and ``hosts``: the default host by platform."""
        caps = base.Driver.capabilities(self)
        caps["throughHost"] = [k for k in self.HOST_STEPS if k in self.STEPS and not self.has_own_step(k)]
        caps["hosts"] = dict((p, DEFAULT_HOSTS[p]) for p in self.PLATFORMS if p in DEFAULT_HOSTS)
        return caps

    # -- the host -------------------------------------------------------------------------------------------

    def host_name(self, device):
        """The host driver's name for ``device`` (``None``: no host)."""
        t = device.get("target") or {}
        name = t.get("host")
        if name in ("none", False):
            return None
        if name:
            return name
        return DEFAULT_HOSTS.get(device.get("platform"))

    def host(self, device):
        """The host driver for ``device`` (made once), or ``None``."""
        if self._host_name is False:
            self._host_name = self.host_name(device)
            if self._host_name:
                from . import get
                cls = get(self._host_name)
                self._host = cls(self.options)
        return self._host

    def host_has(self, device, kind):
        """True when the host can do step ``kind``."""
        h = self.host(device)
        return bool(h is not None and kind in h.STEPS and hasattr(h, "step_" + kind))

    def device_ref(self, device):
        """The host's handle for the device: the simulator's UDID or the adb serial (``None`` without one)."""
        h = self.host(device)
        if h is None:
            t = device.get("target") or {}
            return t.get("udid") or t.get("serial")
        for attr in ("udid", "serial"):
            value = getattr(h, attr, None)
            if value:
                return value
        env = h.script_env(device) or {}
        for key in ("APPSTORES_UDID", "APPSTORES_SERIAL", "ANDROID_SERIAL"):
            if env.get(key):
                return env[key]
        return None

    # -- forwarded calls ------------------------------------------------------------------------------------

    def prepare(self, device, plan):
        """The host's ``prepare`` (boot, install), then ``prepare_app``."""
        h = self.host(device)
        if h is not None:
            h.prepare(device, plan)
        self.prepare_app(device, plan)

    def prepare_app(self, device, plan):
        """What the hosted driver does once the device is up (connect to the agent, start a session)."""

    def reset(self, device):
        """``reset_app`` first, then the host's ``reset``; every warning from both."""
        warnings = []
        try:
            warnings += list(self.reset_app(device) or [])
        except Exception as e:  # noqa: BLE001 - always go on to the host
            warnings.append("%s: putting the app back failed: %s" % (self.NAME, e))
        h = self._host
        if h is not None:
            try:
                warnings += list(h.reset(device) or [])
            except Exception as e:  # noqa: BLE001
                warnings.append("%s: resetting the device failed: %s" % (self._host_name, e))
            self.warnings.extend(getattr(h, "warnings", []) or [])
        return warnings

    def reset_app(self, device):
        """Undo what the hosted driver changed itself (a theme, a session); return warnings."""
        return []

    def source(self, device):
        """The host's description of the device, plus this driver's name."""
        h = self._host
        out = dict(h.source(device)) if h is not None else {}
        out["via"] = self.NAME
        return out

    def apply_locale(self, device, locale, shot):
        """The host sets the device's locale (and passes it at launch)."""
        h = self.host(device)
        if h is not None:
            h.apply_locale(device, locale, shot)
            if "statusBar" not in h.state:
                self.state.pop("statusBar", None)
            h.state["locale"] = locale

    def apply_appearance(self, device, appearance, shot):
        """The host sets the device's appearance."""
        h = self.host(device)
        if h is not None:
            h.apply_appearance(device, appearance, shot)
            h.state["appearance"] = appearance

    def apply_posture(self, device, posture, shot):
        """The host folds the device (and lays it out again, finds the display in use, cleans the status bar
        again); a driver without a host that folds can't."""
        if not self.host_has(device, "posture"):
            raise base.StepSkipped("%s can't put %s in a posture: %s" % (
                self.NAME, device["id"], "it has no host" if self.host(device) is None else
                "its host (%s) can't" % self._host_name))
        h = self.host(device)
        if h.state.get("posture") == posture:
            return   # the host put the device in it already (adb does, preparing a device with a posture)
        h.apply_posture(device, posture, shot)
        h.state["posture"] = posture
        if "statusBar" not in h.state:
            self.state.pop("statusBar", None)

    def folds(self, device):
        """A hosted driver folds through its host."""
        return self.host_has(device, "posture")

    def step_posture(self, ctx, value):
        """``posture`` by the host."""
        base.Driver.step_posture(self, ctx, value)

    def keyboard_shown(self, ctx):
        """The host's view of the keyboard (adb can tell; a simulator can't), unless the driver sees it itself."""
        h = self.host(ctx.device)
        return h.keyboard_shown(ctx) if h is not None else None

    def hide_keyboard(self, ctx, value):
        """The host closes the keyboard when it can (adb: the back key, only while the keyboard is up)."""
        h = self.host(ctx.device)
        if h is not None and "hideKeyboard" in h.STEPS:
            h.hide_keyboard(ctx, value)
            return
        base.Driver.hide_keyboard(self, ctx, value)

    def apply_status_bar(self, device, mode, clock, shot):
        """The host cleans the status bar; ``none`` without a host."""
        h = self.host(device)
        if h is None:
            return "none"
        result = h.apply_status_bar(device, mode, clock, shot)
        h.state["statusBar"] = (mode, clock)
        return result

    def script_env(self, device):
        """The host's variables for a ``script`` step."""
        h = self.host(device)
        return dict(h.script_env(device) or {}) if h is not None else {}

    def unsupported(self, screen, device=None):
        """The base checks, with the host's steps counted only when the host has them."""
        if device is not None:
            posture = screen.get("posture") or device.get("posture")
            if posture and not self.host_has(device, "posture"):
                return "%s puts a device in a posture through its host, and %s has %s" % (
                    self.NAME, device["id"], "no host" if self.host(device) is None else "a host that can't")
            for i, step in enumerate(screen.get("steps") or [], 1):
                kind, _ = base.step_of(step)
                if kind in self.HOST_STEPS and not self.has_own_step(kind) and not self.host_has(device, kind):
                    return "step %d (%s): %s does %s steps through its host, and %s has %s" % (
                        i, base.describe_step(step), self.NAME, kind, device["id"],
                        "no host" if self.host(device) is None else "a host that can't")
        return base.Driver.unsupported(self, screen, device)

    def has_own_step(self, kind):
        """True when this driver does step ``kind`` itself (not through the host)."""
        return False

    def host_step(self, ctx, kind, value):
        """Run step ``kind`` on the host; ``StepSkipped`` when it can't."""
        if not self.host_has(ctx.device, kind):
            raise base.StepSkipped("step %d: %s has no host that does %s steps" % (ctx.index, ctx.device["id"], kind))
        getattr(self.host(ctx.device), "step_" + kind)(ctx, value)

    def step_launch(self, ctx, value):
        """``launch`` by the host (simctl launch / am start with the seed, the args and the locale)."""
        self.host_step(ctx, "launch", value)
        self.after_launch(ctx)

    def after_launch(self, ctx):
        """Called after the host launched the app (wait for an agent to come up, …)."""

    def step_deepLink(self, ctx, value):
        """``deepLink`` by the host."""
        self.host_step(ctx, "deepLink", value)

    def step_url(self, ctx, value):
        """``url`` by the host."""
        self.host_step(ctx, "url", value)

    def step_appFile(self, ctx, value):
        """``appFile`` (a file copied into the app's own data) by the host."""
        self.host_step(ctx, "appFile", value)

    def use_host_screenshot(self, device):
        """True when the host takes the screenshots (the default when there is one)."""
        t = device.get("target") or {}
        return self.host(device) is not None and t.get("screenshot", "host") != "agent"

    def screenshot(self, device, path):
        """The host's screenshot, or ``agent_screenshot``."""
        if self.use_host_screenshot(device):
            self.host(device).screenshot(device, path)
        else:
            self.agent_screenshot(device, path)

    def agent_screenshot(self, device, path):
        """The hosted driver's own screenshot (an agent's, a WebDriver's)."""
        raise base.DriverError("%s can't take screenshots itself: give %s a host" % (self.NAME, device["id"]))
