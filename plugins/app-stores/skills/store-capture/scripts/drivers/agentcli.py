"""What the in-app agent drivers share (``devflow``, ``ailoha``): an agent inside the app's debug build that
serves its UI tree, actions and screenshots on a loopback HTTP port, and a CLI that speaks to it.

Both agents speak the same protocol (``/api/v1/ui/tree``, ``/api/v1/ui/elements?strategy=…&value=…``,
``/api/v1/ui/actions/tap|fill|scroll|back|gesture``, ``/api/v1/ui/screenshot``), and both CLIs share a command
shape (``ui tap --automationId X``, ``ui fill --automationId X "text"``, ``ui query … --wait-until exists``,
``ui scroll``, ``ui screenshot --output … --scale native``, ``agent wait``, ``agent list``). The CLI is used for
everything it does (it finds the agent's port through its broker and sets up adb forwarding); the HTTP API only
for what it lacks (an xpath lookup, DevFlow's back), on the port ``target.agentPort`` names or the CLI's agent
list reports.

The device itself (boot, install, locale, appearance, the clean status bar, launch, deep links and the
screenshot) is the host's (``hosted.py``). Without a host (a Mac Catalyst or Windows app), screenshots are the
agent's (``ui screenshot --scale native``, the app's window).

Target settings: ``agentPort``, ``agentPlatform`` (the CLI's ``--platform``), ``cli`` (the command as a list,
for a CLI that isn't on PATH), ``agentTimeout`` (seconds to wait for the agent after a launch, default 90),
``appName`` (which agent, when the CLI lists several), ``host``, ``screenshot`` (``host`` | ``agent``).
"""

from __future__ import annotations

import json

from . import base
from .hosted import HostedDriver, type_target

DIRECTIONS = ("up", "down", "left", "right")


def parse_json(text):
    """The first JSON value in a CLI's output (it may print a line before it), unwrapped from a
    ``{"result"|"data"|"elements"|"agents": …}`` envelope. ``None`` when there's none."""
    text = (text or "").strip()
    if not text:
        return None
    value = None
    for start in range(len(text)):
        if text[start] in "[{":
            try:
                value = json.JSONDecoder().raw_decode(text[start:])[0]
                break
            except ValueError:
                continue
    if isinstance(value, dict):
        for key in ("result", "data", "elements", "agents"):
            if key in value and isinstance(value[key], (list, dict)):
                return value[key]
    return value


def element_from(item):
    """A protocol element (``{"id", "automationId", "text", "bounds": {x, y, width, height}, …}``) as a
    ``base.Element``; ``attrs["elementId"]`` is the agent's own id for it."""
    b = item.get("bounds") or {}
    bounds = None
    try:
        if b:
            x, y, w, h = float(b.get("x", 0)), float(b.get("y", 0)), float(b.get("width", 0)), float(b.get("height", 0))
            bounds = (int(x), int(y), int(x + w), int(y + h))
    except (TypeError, ValueError):
        bounds = None
    attrs = dict(item)
    attrs["elementId"] = item.get("id")
    return base.Element(id=item.get("automationId"), text=item.get("text") or item.get("value"),
                        label=item.get("role"), cls=item.get("type"), bounds=bounds, attrs=attrs)


class AgentCliDriver(HostedDriver):
    """An in-app agent driven by its CLI (see the module's docstring). Subclasses set ``NAME``, ``CLI``,
    ``DEFAULT_PORT``, ``PLATFORM_ARGS`` and what differs."""

    CLI = ()
    DEFAULT_PORT = 0
    PLATFORMS = ("ios", "ipados", "android", "macos", "windows")
    PLATFORM_ARGS = {"ios": "ios", "ipados": "ios", "android": "android", "macos": "maccatalyst",
                     "windows": "windows"}
    STEPS = ("launch", "deepLink", "url", "tap", "type", "wait", "scroll", "back", "swipe", "settle", "script")
    FINDERS = ("id", "text", "css", "xpath")
    LOCATORS = {"id": "accessibility-id", "text": "text", "css": "css-selector", "xpath": "xpath"}
    INSTALL = ""

    def __init__(self, options=None):
        """Set up; nothing runs until ``prepare``."""
        HostedDriver.__init__(self, options)
        self.port = None
        self.forwarded = None

    # -- the CLI and the HTTP API -----------------------------------------------------------------------------

    def cli_cmd(self, device):
        """The CLI as a command list (``target.cli`` overrides)."""
        t = device.get("target") or {}
        cli = t.get("cli")
        if isinstance(cli, str):
            cli = cli.split()
        return list(cli or self.CLI)

    def globals(self, device, platform=True):
        """Options every CLI command gets: the agent's port when known, the platform (not for ``agent wait``
        and ``agent list``, where DevFlow's ``--platform`` is a filter on the broker's own platform names)."""
        t = device.get("target") or {}
        out = []
        port = t.get("agentPort") or self.port
        if port:
            out += ["--agent-port", str(port)]
        plat = t.get("agentPlatform") or self.PLATFORM_ARGS.get(device.get("platform"))
        if plat and platform:
            out += ["--platform", plat]
        return out

    def cli(self, device, args, timeout=120, check=True, dry_output="", json_out=False):
        """Run ``<cli> <args> <globals> [--json]``."""
        agent = list(args[:1]) == ["agent"]
        cmd = self.cli_cmd(device) + list(args) + self.globals(device, platform=not agent) + (
            ["--json"] if json_out else [])
        try:
            return base.run(cmd, timeout=timeout, check=check, dry_output=dry_output)
        except base.ToolMissing as e:
            raise base.ToolMissing("%s (%s)" % (e, self.INSTALL)) from None

    def agent_port(self, device):
        """The agent's HTTP port: ``target.agentPort``, else the one the CLI's agent list reports for this app
        (the only agent, or the one whose name or package matches), else the agent's default."""
        t = device.get("target") or {}
        if t.get("agentPort"):
            return int(t["agentPort"])
        if self.port:
            return self.port
        agents = parse_json(self.cli(device, self.list_args(), check=False, dry_output="[]", json_out=True).out)
        agents = agents if isinstance(agents, list) else []
        wanted = [w for w in (t.get("appName"), (device.get("app") or {}).get("bundleId"),
                              (device.get("app") or {}).get("package")) if w]
        pick = None
        if len(agents) == 1:
            pick = agents[0]
        else:
            for a in agents:
                names = [str(a.get(k) or "") for k in ("appName", "packageId", "project", "id")]
                if any(w and any(w in n for n in names) for w in wanted):
                    pick = a
                    break
        port = None
        if isinstance(pick, dict):
            port = pick.get("port") or pick.get("agentPort")
        self.port = int(port) if port else self.DEFAULT_PORT
        self.forward(device, self.port)
        return self.port

    def list_args(self):
        """The CLI's arguments that list connected agents."""
        return ["agent", "list"]

    def forward(self, device, port):
        """On Android, ``adb forward tcp:<port> tcp:<port>`` so the HTTP API reaches the agent on the device
        (the CLIs do this themselves; direct HTTP needs it too). Removed in ``reset``."""
        if device.get("platform") != "android":
            return
        serial = self.device_ref(device)
        adb = ["adb"] + (["-s", serial] if serial else [])
        listed = base.run(adb + ["forward", "--list"], check=False, quiet=True, dry_output="").out or ""
        if ("tcp:%d tcp:%d" % (port, port)) in listed:
            return
        base.run(adb + ["forward", "tcp:%d" % port, "tcp:%d" % port], timeout=30)
        self.forwarded = (adb, port)

    def api(self, device, method, path, body=None, timeout=30, dry_body=b"{}"):
        """One request to the agent's HTTP API (``http://127.0.0.1:<port><path>``), its JSON returned."""
        url = "http://127.0.0.1:%d%s" % (self.agent_port(device), path)
        return base.http_json(method, url, body=body, timeout=timeout, dry_body=dry_body)

    # -- the four calls ---------------------------------------------------------------------------------------

    def prepare_app(self, device, plan):
        """Check the CLI is there (``maui --version``, ``ailoha --version``): a missing one is ``ToolMissing`` with the install line."""
        try:
            base.run(self.cli_cmd(device)[:1] + ["--version"], timeout=60, check=False, dry_output="0.0.0", quiet=True)
        except base.ToolMissing as e:
            raise base.ToolMissing("%s (%s)" % (e, self.INSTALL)) from None

    def reset_app(self, device):
        """Remove the adb forward this driver added."""
        warnings = []
        if self.forwarded:
            adb, port = self.forwarded
            res = base.run(adb + ["forward", "--remove", "tcp:%d" % port], check=False, timeout=30)
            if not res.ok:
                warnings.append("couldn't remove adb forward tcp:%d" % port)
            self.forwarded = None
        return warnings

    def after_launch(self, ctx):
        """Wait for the agent to answer after a launch: the broker's ``agent wait``, then ``ui status``."""
        t = ctx.device.get("target") or {}
        timeout = float(t.get("agentTimeout") or 90)
        if not t.get("agentPort"):
            self.cli(ctx.device, ["agent", "wait", "--timeout", str(int(timeout))], timeout=timeout + 30,
                     check=False)
        base.poll(lambda: self.cli(ctx.device, ["ui", "status"], check=False, timeout=30).ok, timeout,
                  interval=1.0, what="the %s agent to answer" % self.NAME)

    def has_own_step(self, kind):
        return kind not in self.HOST_STEPS

    # -- finding --------------------------------------------------------------------------------------------

    def finder_args(self, query):
        """The CLI's options for a finder (``--automationId``, ``--text``, ``--selector``); ``None`` for one the
        CLI can't take (xpath)."""
        finder, wanted = query
        if finder == "id":
            return ["--automationId", str(wanted)]
        if finder == "text":
            return ["--text", str(wanted)]
        if finder == "css":
            return ["--selector", str(wanted)]
        return None

    def find(self, ctx, query):
        """The first element ``query`` finds now (CLI ``ui query``; xpath through the HTTP API), or ``None``."""
        args = self.finder_args(query)
        if args is not None:
            res = self.cli(ctx.device, ["ui", "query"] + args, check=False, dry_output='[{"id": "dry-run"}]',
                           json_out=True, timeout=60)
            items = parse_json(res.out) if res.ok else None
        else:
            path = "/api/v1/ui/elements?strategy=%s&value=%s&limit=1" % (
                self.LOCATORS[query[0]], _quote(query[1]))
            try:
                items = self.api(ctx.device, "GET", path, dry_body=b'[{"id": "dry-run"}]')
            except base.DriverError:
                items = None
        if isinstance(items, dict):
            items = [items]
        if not items:
            return None
        return element_from(items[0])

    def element_id(self, ctx, query, timeout=None):
        """The agent's id for the element ``query`` names, waiting for it to appear."""
        el = self.wait_for(ctx, query, timeout if timeout is not None else 10)
        return el.attrs.get("elementId")

    # -- steps -------------------------------------------------------------------------------------------------

    def step_tap(self, ctx, value):
        """``ui tap --automationId|--text`` (css and xpath: found first, then tapped by the agent's id)."""
        if isinstance(value, dict) and "x" in value and "y" in value:
            if self.host_has(ctx.device, "tap"):
                self.host(ctx.device).step_tap(ctx, value)
                return
            raise base.StepFailed("step %d: %s taps elements, not points: give the device a host that taps "
                                  "points (adb), or name the element" % (ctx.index, self.NAME))
        query = base.element_query(value)
        if query is None:
            raise base.StepFailed("step %d: tap needs an element (id, text, css or xpath)" % ctx.index)
        args = self.finder_args(query) if query[0] in ("id", "text") else None
        if args is None:
            args = [self.element_id(ctx, query)]
        self.cli(ctx.device, ["ui", "tap"] + args)

    def step_type(self, ctx, value):
        """``ui fill <target> <text>`` (the target: ``id``, ``css`` or ``xpath`` beside the ``text`` to type, or
        ``into``: the field showing that text); without a target, the host types into whatever has focus."""
        if isinstance(value, str):
            value = {"text": value}
        value = value or {}
        text = value.get("text")
        if text is None:
            raise base.StepFailed("step %d: type needs text" % ctx.index)
        query = base.element_query(type_target(value))
        if query is None:
            if self.host_has(ctx.device, "type"):
                self.host(ctx.device).step_type(ctx, {"text": text})
                return
            raise base.StepFailed("step %d: %s fills an element: give type an id (or css/xpath) beside its text"
                                  % (ctx.index, self.NAME))
        args = self.finder_args(query) if query[0] in ("id", "text") else None
        if args is None:
            args = [self.element_id(ctx, query)]
        self.cli(ctx.device, ["ui", "fill"] + args + [str(text)])

    def step_wait(self, ctx, value):
        """``ms`` sleeps; an element waits with ``ui query … --wait-until exists --timeout`` (xpath: polled)."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = {"ms": value}
        value = value or {}
        if value.get("ms") is not None:
            base.sleep(float(value["ms"]) / 1000.0)
        query = base.element_query(value)
        if query is None:
            return
        timeout = float(value.get("timeout") or self.WAIT_TIMEOUT)
        args = self.finder_args(query)
        if args is None:
            self.wait_for(ctx, query, timeout)
            return
        res = self.cli(ctx.device, ["ui", "query"] + args + ["--wait-until", "exists", "--timeout",
                                                              str(int(max(1, round(timeout))))],
                       timeout=timeout + 30, check=False)
        if not res.ok:
            raise base.StepFailed("%s %r didn't appear within %g s" % (query[0], query[1], timeout))

    def step_scroll(self, ctx, value):
        """``to`` an element: ``ui scroll --element <id>`` (into view); a ``direction`` (``times`` times, each
        ``distance``, default 400): ``ui scroll --dx/--dy``."""
        value = value or {}
        if isinstance(value, str):
            value = {"direction": value}
        to = value.get("to")
        if to:
            query = base.element_query(to)
            if query is None:
                raise base.StepFailed("step %d: scroll to needs an element" % ctx.index)
            self.cli(ctx.device, ["ui", "scroll", "--element", self.element_id(ctx, query)])
            return
        direction = value.get("direction", "down")
        if direction not in DIRECTIONS:
            raise base.StepFailed("step %d: scroll direction is up, down, left or right" % ctx.index)
        d = float(value.get("distance") or 400)
        # The CLIs' sign: a negative --dy scrolls down (content moves up).
        delta = {"down": ("--dy", -d), "up": ("--dy", d), "right": ("--dx", -d), "left": ("--dx", d)}[direction]
        for _ in range(int(value.get("times") or 1)):
            self.cli(ctx.device, ["ui", "scroll", delta[0], "%g" % delta[1]])

    def step_back(self, ctx, value):
        """The agent's back action (``POST /api/v1/ui/actions/back``)."""
        self.api(ctx.device, "POST", "/api/v1/ui/actions/back", body={})

    def step_swipe(self, ctx, value):
        """A swipe (``direction``; optional element to swipe on, ``distance``)."""
        raise base.StepSkipped("step %d: %s can't swipe" % (ctx.index, self.NAME))

    def agent_screenshot(self, device, path):
        """``ui screenshot --output <path> --scale native --overwrite`` (native pixels, never scaled down)."""
        self.cli(device, ["ui", "screenshot", "--output", path, "--scale", "native", "--overwrite"], timeout=120)


def _quote(value):
    import urllib.parse
    return urllib.parse.quote(str(value), safe="")
