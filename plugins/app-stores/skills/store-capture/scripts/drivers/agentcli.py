"""What the in-app agent drivers share (``devflow``, ``ailoha``): an agent inside the app's debug build that
serves its UI tree, actions and screenshots on a loopback HTTP port, and a CLI that speaks to it.

Both agents speak the same protocol (``/api/v1/ui/tree``, ``/api/v1/ui/elements?strategy=…&value=…``,
``/api/v1/ui/actions/tap|fill|scroll|back|gesture``, ``/api/v1/ui/screenshot``), and both CLIs share a command
shape (``ui tap --automationId X``, ``ui fill --automationId X "text"``, ``ui query … --wait-until exists``,
``ui scroll``, ``ui screenshot --output … --scale native``, ``agent wait``, ``agent list``). The CLI is used for
everything it does; the HTTP API only to read (an agent's status, an xpath lookup), never to change the app while
the CLI holds DevFlow's one-client lease.

**Which agent.** Several apps' agents may be running (the developer's own simulators and phone). The driver never
lets the CLI pick: it lists the agents (``agent list --json``), asks each for its status (``GET
/api/v1/agent/status``: the device's id, the app's package and process), and pins the one that is this plan's app
on this device (the simulator's UDID, matched in the status or through the process's path; on Android the
process id ``pidof`` reports on the device's serial). Every later command carries ``--agent-port``; after each
launch it's found again. None or more than one is a clear error, never a guess. ``target.agentPort`` names one
(checked against the status when it answers). On Android the CLI also gets ``--device <serial>`` (DevFlow) and
``ANDROID_SERIAL`` so the forwards it makes go to this device only.

The device itself (boot, install, locale, appearance, the clean status bar, launch, deep links and the
screenshot) is the host's (``hosted.py``). Without a host (a Mac Catalyst or Windows app), screenshots are the
agent's (``ui screenshot --scale native``, the app's window).

Target settings: ``agentPort``, ``agentPlatform`` (the CLI's ``--platform``), ``cli`` (the command as a list,
for a CLI that isn't on PATH), ``agentTimeout`` (seconds to wait for the agent after a launch, default 90),
``appName`` (the app's display name, when the agent reports no package), ``host``, ``screenshot`` (``host`` |
``agent``).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

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


def first_json(text):
    """The first JSON value in a CLI's output, as it is (no envelope unwrapped); ``None`` when there's none."""
    text = (text or "").strip()
    for start in range(len(text)):
        if text[start] in "[{":
            try:
                return json.JSONDecoder().raw_decode(text[start:])[0]
            except ValueError:
                continue
    return None


def _get(d, *path):
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def tree_to_xml(items):
    """An agent's tree (a list of ``{"type", "automationId", "text", "id", "children": […]}``) as an ElementTree
    root for XPath (``//Button[@automationId='search']``), and a map from each node to its item."""
    root = ET.Element("tree")
    nodes = {}

    def add(parent, item):
        if not isinstance(item, dict):
            return
        tag = re.sub(r"[^A-Za-z0-9_.-]", "", str(item.get("type") or "Element")) or "Element"
        if not re.match(r"[A-Za-z_]", tag):
            tag = "E" + tag
        attrs = dict((k, str(v)) for k, v in item.items() if isinstance(v, (str, int, float, bool)) and v is not None)
        node = ET.SubElement(parent, tag, attrs)
        nodes[node] = item
        for child in item.get("children") or []:
            add(node, child)

    for item in items if isinstance(items, list) else [items]:
        add(root, item)
    return root, nodes


def walk(items):
    """Every item of an agent's tree, depth first."""
    stack = list(reversed(items if isinstance(items, list) else [items]))
    while stack:
        item = stack.pop()
        if not isinstance(item, dict):
            continue
        yield item
        stack.extend(reversed(item.get("children") or []))


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
    STEPS = ("launch", "deepLink", "url", "appFile", "tap", "type", "wait", "scroll", "back", "swipe", "settle",
             "script", "posture", "hideKeyboard")
    FINDERS = ("id", "text", "css", "xpath")
    LOCATORS = {"id": "accessibility-id", "text": "text", "css": "css-selector", "xpath": "xpath"}
    INSTALL = ""
    STATUS_PATH = "/api/v1/agent/status"
    DEVICE_FLAG = None      # the CLI's option naming an Android device by serial (DevFlow: --device)
    RETRIES = 3             # a command another client's lease turned away is tried again this often
    LEASE = ("another devflow session", "another session is driving", "take control before mutating",
             '"reason":"lease"', '"reason": "lease"')
    NOT_FOUND = ("no elements found", "no element", "not found", "element not found")
    TAP_ADVICE = ""

    def __init__(self, options=None):
        """Set up; nothing runs until ``prepare``."""
        HostedDriver.__init__(self, options)
        self.port = None
        self.pinned = False
        self.forwarded = []
        self.agent = {}

    # -- the CLI and the HTTP API -----------------------------------------------------------------------------

    def cli_cmd(self, device):
        """The CLI as a command list (``target.cli`` overrides)."""
        t = device.get("target") or {}
        cli = t.get("cli")
        if isinstance(cli, str):
            cli = cli.split()
        return list(cli or self.CLI)

    def serial(self, device):
        """The Android device's adb serial (``None`` elsewhere, or without one)."""
        if device.get("platform") != "android":
            return None
        return self.device_ref(device)

    def globals(self, device, platform=True):
        """Options every CLI command gets: the pinned agent's port, the platform (not for ``agent wait`` and
        ``agent list``, where DevFlow's ``--platform`` filters on the broker's own platform names) and, on Android,
        the device's serial (``DEVICE_FLAG``) so the CLI's adb forwards go to it."""
        t = device.get("target") or {}
        out = []
        port = t.get("agentPort") or self.port
        if port:
            out += ["--agent-port", str(port)]
        plat = t.get("agentPlatform") or self.PLATFORM_ARGS.get(device.get("platform"))
        if plat and platform:
            out += ["--platform", plat]
        serial = self.serial(device)
        if serial and self.DEVICE_FLAG:
            out += [self.DEVICE_FLAG, serial]
        return out

    def cli_env(self, device):
        """``ANDROID_SERIAL`` for the CLI on Android, so an ``adb`` it runs reaches this device only."""
        serial = self.serial(device)
        return {"ANDROID_SERIAL": serial} if serial else None

    def leased(self, res):
        """True when the agent turned a command away because another client holds its lease."""
        text = ((res.out or "") + " " + (res.err or "")).lower()
        return any(m in text for m in self.LEASE)

    def cli(self, device, args, timeout=120, check=True, dry_output="", json_out=False, pin=True):
        """Run ``<cli> <args> <globals> [--json]``, one command at a time, on the pinned agent (``pin``: find it
        first; ``agent …`` commands never pin). A command another client's lease turned away is tried again a
        second later (``RETRIES``); still turned away, it's a ``DriverError`` saying so."""
        agent = list(args[:1]) == ["agent"]
        if pin and not agent:
            self.ensure_pinned(device)
        cmd = self.cli_cmd(device) + list(args) + self.globals(device, platform=not agent) + (
            ["--json"] if json_out else [])
        res = None
        for attempt in range(self.RETRIES):
            try:
                res = base.run(cmd, timeout=timeout, check=False, dry_output=dry_output, env=self.cli_env(device))
            except base.ToolMissing as e:
                raise base.ToolMissing("%s (%s)" % (e, self.INSTALL)) from None
            if res.ok or not self.leased(res) or attempt == self.RETRIES - 1:
                break
            base.note("  the agent is busy with another client's command: trying again in a second")
            base.sleep(1.0)
        if self.leased(res) and not res.ok:
            raise base.DriverError("%s: another %s client holds this app's lease (the Inspector, an IDE, an MCP "
                                   "server or another CLI): close it and run again" % (base.quote(cmd), self.NAME))
        if check and not res.ok:
            raise base.CommandError(cmd, res.code, res.out, res.err)
        return res

    def outcome(self, res):
        """``(ok, message)`` for an action: a non-zero exit, or a reply saying ``"success": false``, isn't ok."""
        if not res.ok:
            return False, (res.err or res.out or "exit %s" % res.code).strip()
        raw = first_json(res.out)
        if isinstance(raw, dict) and raw.get("success") is False:
            return False, str(raw.get("error") or raw.get("message") or raw.get("reason") or "success: false")
        return True, ""

    def not_found(self, message):
        return any(m in (message or "").lower() for m in self.NOT_FOUND)

    def act(self, ctx, args, what):
        """Run an action (``ui tap …``, ``ui fill …``) and raise ``StepFailed`` with advice when it didn't work."""
        ok, message = self.outcome(self.cli(ctx.device, args, check=False))
        if not ok:
            raise base.StepFailed("step %d: %s: %s%s" % (ctx.index, what, message[:300],
                                                         self.TAP_ADVICE if what.startswith("tap") else ""))

    # -- which agent ------------------------------------------------------------------------------------------

    def list_args(self):
        """The CLI's arguments that list connected agents."""
        return ["agent", "list"]

    def app_id(self, device):
        app = device.get("app") or {}
        return app.get("bundleId") or app.get("package")

    def agents(self, device):
        """The agents the CLI lists (dicts), each with a ``port``."""
        res = self.cli(device, self.list_args(), check=False, dry_output="[]", json_out=True, pin=False)
        items = parse_json(res.out) if res.ok else None
        items = items if isinstance(items, list) else []
        out = []
        for a in items:
            if isinstance(a, dict) and (a.get("port") or a.get("agentPort")):
                a = dict(a)
                a["port"] = int(a.get("port") or a.get("agentPort"))
                out.append(a)
        return out

    def agent_status(self, device, port):
        """``GET /api/v1/agent/status`` on ``port`` (a read: no lease needed), or ``None`` when it doesn't answer.
        On Android the port is forwarded from this device only (``--no-rebind``: never taking a forward another
        device has)."""
        if device.get("platform") == "android" and self.device_ref(device) and \
                not self.forward(device, port, quiet_fail=True):
            return None
        try:
            data = base.http_json("GET", "http://127.0.0.1:%d%s" % (port, self.STATUS_PATH), timeout=5)
        except base.DriverError:
            return None
        return data if isinstance(data, dict) else None

    def identify(self, device, agent):
        """Whether ``agent`` is this plan's app on this device: ``True``, ``False``, or ``None`` (can't tell)."""
        family = {"ios": "ios", "ipados": "ios", "tvos": "ios", "android": "android"}.get(device.get("platform"))
        plat = str(agent.get("platform") or "").lower()
        if family == "ios" and plat and "ios" not in plat:
            return False
        if family == "android" and plat and "android" not in plat:
            return False
        status = self.agent_status(device, agent["port"]) or {}
        want = self.app_id(device)
        have = _get(status, "app", "packageId") or agent.get("packageId") or agent.get("bundleId")
        if want and have and have != want:
            return False
        name = (device.get("target") or {}).get("appName")
        shown = _get(status, "app", "name") or agent.get("appName")
        if not have and name and shown and name != shown:
            return False
        pid = _get(status, "app", "processId") or agent.get("processId")
        ref = self.device_ref(device)
        if not ref:
            # No host (a Mac Catalyst or Windows app on this machine): the app's id is all there is.
            return True if (want and have == want) or (name and shown == name) else None
        dev = _get(status, "device", "id")
        if family == "ios":
            if dev and dev.upper() == ref.upper():
                return True
            if pid:
                path = base.run(["ps", "-o", "command=", "-p", str(pid)], check=False, quiet=True).out or ""
                if ("/Devices/%s/" % ref).upper() in path.upper():
                    return True
                if "CoreSimulator/Devices/" in path:
                    return False
            return False if dev else None
        if family == "android":
            if dev and dev == ref:
                return True
            if pid and want:
                adb = list(getattr(self.host(device), "adb", None) or ["adb"])
                out = base.run(adb + ["-s", ref, "shell", "pidof", want], check=False, quiet=True).out or ""
                if str(pid) in out.split():
                    return True
                return False
            # The status answered through a forward from this device only: it's this device's agent.
            return True if status and have == want else None
        return None

    def describe_agent(self, agent):
        return "port %s (%s)" % (agent.get("port"), ", ".join(str(agent.get(k)) for k in ("appName", "platform", "tfm")
                                                              if agent.get(k)))

    def find_agent(self, device):
        """The port of this plan's app's agent on this device, from ``agents`` and ``identify``: ``None`` while
        there's none yet; ``DriverError`` when more than one is."""
        mine, unsure, others = [], [], []
        for a in self.agents(device):
            verdict = self.identify(device, a)
            (mine if verdict else unsure if verdict is None else others).append(a)
        ports = sorted(set(a["port"] for a in mine))
        if len(ports) > 1:
            raise base.DriverError("more than one %s agent is %s on %s (%s): stop the extra copies, or name one "
                                   "with target.agentPort" % (self.NAME, self.app_id(device) or "this app",
                                                               self.device_ref(device) or "this machine",
                                                               "; ".join(self.describe_agent(a) for a in mine)))
        if ports:
            self.agent = mine[0]
            return ports[0]
        self._last = (unsure, others)
        return None

    def ensure_pinned(self, device, timeout=None):
        """Pin the agent every command goes to (once, and again after each launch): ``target.agentPort``
        (checked against the agent's status when it answers), else ``find_agent`` until it's there."""
        if self.pinned:
            return
        t = device.get("target") or {}
        if base.DRY_RUN:
            base.note("  (dry run: the agent of %s on %s would be found in `%s` and pinned with --agent-port)" % (
                self.app_id(device) or "the app", self.device_ref(device) or "this machine",
                " ".join(self.cli_cmd(device) + self.list_args())))
            self.pinned = True
            return
        if t.get("agentPort"):
            self.port = int(t["agentPort"])
            verdict = self.identify(device, {"port": self.port})
            if verdict is False:
                raise base.DriverError("target.agentPort %d is another app's or another device's agent, not %s on "
                                       "%s: check `%s`" % (self.port, self.app_id(device), self.device_ref(device),
                                                           " ".join(self.cli_cmd(device) + self.list_args())))
            self.pinned = True
            self.forward(device, self.port)
            return
        timeout = float(t.get("agentTimeout") or 90) if timeout is None else timeout
        self._last = ([], [])
        try:
            self.port = base.poll(lambda: self.find_agent(device), timeout, interval=1.0, what="the agent")
        except base.StepFailed:
            unsure, others = self._last
            running = unsure + others
            raise base.DriverError(
                "no %s agent of %s on %s appeared within %g s. %s Is the debug build (with the agent) installed and "
                "launched? Only an agent known to be this app on this device is used%s" % (
                    self.NAME, self.app_id(device) or "the app", self.device_ref(device) or "this machine", timeout,
                    ("Running: %s." % "; ".join(self.describe_agent(a) for a in running)) if running
                    else "No agent is running.",
                    ": these couldn't be told apart, so name the right one with target.agentPort after checking "
                    "`%s`" % " ".join(self.cli_cmd(device) + self.list_args()) if unsure else "")) from None
        self.pinned = True
        base.note("  pinned the %s agent on port %d%s" % (self.NAME, self.port, (" (%s)" % self.describe_agent(
            self.agent)) if self.agent else ""))
        self.forward(device, self.port)

    def agent_port(self, device):
        """The pinned agent's HTTP port (``ensure_pinned``)."""
        self.ensure_pinned(device)
        return self.port or self.DEFAULT_PORT

    def forward(self, device, port, quiet_fail=False):
        """On Android, ``adb -s <serial> forward --no-rebind tcp:<port> tcp:<port>`` so the HTTP API reaches the
        agent on this device (never taking a host port another device's forward holds). Removed in ``reset``.
        Returns True when the port reaches this device."""
        if device.get("platform") != "android":
            return True
        serial = self.device_ref(device)
        if not serial:
            return False
        adb = list(getattr(self.host(device), "adb", None) or ["adb"]) + ["-s", serial]
        listed = base.run(adb + ["forward", "--list"], check=False, quiet=True, dry_output="").out or ""
        for line in listed.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "tcp:%d" % port:
                return parts[0] == serial
        res = base.run(adb + ["forward", "--no-rebind", "tcp:%d" % port, "tcp:%d" % port], check=False, timeout=30,
                       quiet=quiet_fail)
        if not res.ok:
            if quiet_fail:
                return False
            raise base.DriverError("couldn't forward tcp:%d to %s: %s" % (port, serial, (res.err or res.out).strip()))
        self.forwarded.append((adb, port))
        return True

    def api(self, device, method, path, body=None, timeout=30, dry_body=b"{}"):
        """One request to the pinned agent's HTTP API (``http://127.0.0.1:<port><path>``), its JSON returned."""
        port = self.agent_port(device)
        if not base.DRY_RUN and not self.forward(device, port):
            raise base.DriverError("tcp:%d on this machine is forwarded to another Android device: the %s agent on "
                                   "%s can't be reached over HTTP without taking it" % (port, self.NAME,
                                                                                         self.device_ref(device)))
        url = "http://127.0.0.1:%d%s" % (port, path)
        return base.http_json(method, url, body=body, timeout=timeout, dry_body=dry_body)

    # -- the four calls ---------------------------------------------------------------------------------------

    def prepare_app(self, device, plan):
        """Check the CLI is there (``maui --version``, ``ailoha --version``): a missing one is ``ToolMissing`` with
        the install line. On Android without a host serial and several devices attached, refuse: the CLI's adb
        forwards would go to whichever adb picks."""
        try:
            base.run(self.cli_cmd(device)[:1] + ["--version"], timeout=60, check=False, dry_output="0.0.0", quiet=True)
        except base.ToolMissing as e:
            raise base.ToolMissing("%s (%s)" % (e, self.INSTALL)) from None
        if device.get("platform") == "android" and not self.device_ref(device) and not base.DRY_RUN:
            out = base.run(["adb", "devices"], check=False, quiet=True).out or ""
            attached = [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("device")]
            if len(attached) > 1:
                raise base.DriverError("%d Android devices are attached (%s) and %s names none: give it a host "
                                       "(adb) or target.serial so the agent's forwards go to the right one"
                                       % (len(attached), ", ".join(attached), device["id"]))

    def reset_app(self, device):
        """Remove the adb forwards this driver added."""
        warnings = []
        for adb, port in self.forwarded:
            res = base.run(adb + ["forward", "--remove", "tcp:%d" % port], check=False, timeout=30)
            if not res.ok:
                warnings.append("couldn't remove adb forward tcp:%d" % port)
        self.forwarded = []
        return warnings

    def after_launch(self, ctx):
        """After a launch the app is a new process: find its agent again (``ensure_pinned``), then wait until it
        answers (``ui status``)."""
        t = ctx.device.get("target") or {}
        timeout = float(t.get("agentTimeout") or 90)
        if not t.get("agentPort"):
            self.pinned = False
            self.port = None
        self.ensure_pinned(ctx.device, timeout)
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

    def tree(self, device):
        """The agent's whole UI tree (``ui tree --json``) as a list of items."""
        res = self.cli(device, ["ui", "tree"], check=False, json_out=True, timeout=60, dry_output="[]")
        items = parse_json(res.out) if res.ok else None
        if isinstance(items, dict):
            items = [items]
        return items if isinstance(items, list) else []

    def find_in_tree(self, device, query):
        """``query`` looked up in the whole tree: an ``id`` the agent's query missed (a native view registered
        with the agent shows its automationId in the tree only), ``text`` as every driver matches it (exactly, then
        ignoring case and surrounding space, then contained: the agent's own query is exact), or an ``xpath``
        (XPath 1.0's everyday part, ``base.xpath_all``, over elements named by their type with their fields as
        attributes)."""
        items = self.tree(device)
        finder, wanted = query
        if finder == "xpath":
            root, nodes = tree_to_xml(items)
            node = base.xpath_first(root, wanted)
            return element_from(nodes[node]) if node is not None and node in nodes else None
        if finder == "text":
            return base.find_element([element_from(item) for item in walk(items)], "text", wanted)
        for item in walk(items):
            aid = item.get("automationId")
            if finder == "id" and aid and (aid == wanted or str(aid).endswith("/" + str(wanted))):
                return element_from(item)
        return None

    def find(self, ctx, query):
        """The first element ``query`` finds now, or ``None``: the CLI's ``ui query`` (an ``id`` it misses is looked
        for in the tree too); an xpath through the HTTP API, else the tree."""
        args = self.finder_args(query)
        if args is not None:
            res = self.cli(ctx.device, ["ui", "query"] + args, check=False, dry_output='[{"id": "dry-run"}]',
                           json_out=True, timeout=60)
            items = parse_json(res.out) if res.ok else None
            if isinstance(items, dict):
                items = [items]
            if items:
                return element_from(items[0])
            if query[0] in ("id", "text") and not base.DRY_RUN:
                return self.find_in_tree(ctx.device, query)
            return None
        path = "/api/v1/ui/elements?strategy=%s&value=%s&limit=1" % (self.LOCATORS[query[0]], _quote(query[1]))
        try:
            items = self.api(ctx.device, "GET", path, dry_body=b'[{"id": "dry-run"}]')
        except base.DriverError:
            # Some versions' element query takes only type, automationId, text or selector: read the tree.
            return self.find_in_tree(ctx.device, query)
        if isinstance(items, dict):
            items = items.get("elements") if isinstance(items.get("elements"), list) else [items]
        if not items:
            return None
        return element_from(items[0])

    def element_id(self, ctx, query, timeout=None):
        """The agent's id for the element ``query`` names, waiting for it to appear."""
        el = self.wait_for(ctx, query, timeout if timeout is not None else 10)
        return el.attrs.get("elementId")

    def inspect_tree(self, ctx):
        """The agent's UI tree as JSON (``capture.py --inspect``)."""
        return json.dumps(self.tree(ctx.device), indent=1, ensure_ascii=False)

    # -- steps -------------------------------------------------------------------------------------------------

    def step_tap(self, ctx, value):
        """``ui tap --automationId|--text``; when that finds nothing yet, wait for the element (a native view's
        id is looked for in the tree) and tap it by the agent's own id. css and xpath: found first, then tapped
        by id. A tap the agent reports as ``success: false`` fails the step, with advice."""
        if isinstance(value, dict) and "x" in value and "y" in value:
            if self.host_has(ctx.device, "tap"):
                self.host(ctx.device).step_tap(ctx, value)
                return
            raise base.StepFailed("step %d: %s taps elements, not points: give the device a host that taps "
                                  "points (adb), or name the element%s" % (ctx.index, self.NAME, self.TAP_ADVICE))
        query = base.element_query(value)
        if query is None:
            raise base.StepFailed("step %d: tap needs an element (id, text, css or xpath)" % ctx.index)
        timeout = (value or {}).get("timeout")
        args = self.finder_args(query) if query[0] in ("id", "text") else None
        if args is not None:
            ok, message = self.outcome(self.cli(ctx.device, ["ui", "tap"] + args, check=False))
            if ok:
                return
            if not self.not_found(message):
                raise base.StepFailed("step %d: tap %s %r: %s%s" % (ctx.index, query[0], query[1], message[:300],
                                                                     self.TAP_ADVICE))
        self.act(ctx, ["ui", "tap", self.element_id(ctx, query, timeout)], "tap %s %r" % query)

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
        if args is not None:
            ok, message = self.outcome(self.cli(ctx.device, ["ui", "fill"] + args + [str(text)], check=False))
            if ok:
                return
            if not self.not_found(message):
                raise base.StepFailed("step %d: fill %s %r: %s" % (ctx.index, query[0], query[1], message[:300]))
        self.act(ctx, ["ui", "fill", self.element_id(ctx, query, value.get("timeout"))] + [str(text)],
                 "fill %s %r" % query)

    def step_wait(self, ctx, value):
        """``ms`` sleeps; an element waits with ``ui query … --wait-until exists --timeout`` (xpath: polled; an id
        the query never finds is looked for in the tree before giving up)."""
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
        if res.ok:
            return
        if query[0] in ("id", "text") and self.find_in_tree(ctx.device, query) is not None:
            return
        raise base.StepFailed("%s %r didn't appear within %g s" % (query[0], query[1], timeout))

    def step_scroll(self, ctx, value):
        """``to`` an element: ``ui scroll --element <id>`` (into view; when the agent can't, scrolled down until
        it's found, at most ``times``, 8); a ``direction`` (``times`` times, each ``distance``, default 400):
        ``ui scroll --dx/--dy``."""
        value = value or {}
        if isinstance(value, str):
            value = {"direction": value}
        to = value.get("to")
        if to:
            query = base.element_query(to)
            if query is None:
                raise base.StepFailed("step %d: scroll to needs an element" % ctx.index)
            ok, message = self.outcome(self.cli(ctx.device, ["ui", "scroll", "--element",
                                                             self.element_id(ctx, query)], check=False))
            if ok:
                return
            base.note("  the agent couldn't scroll to it (%s): scrolling down instead" % message[:120])
            for _ in range(int(value.get("times") or 8)):
                self.cli(ctx.device, ["ui", "scroll", "--dy", "-400"])
                el = self.find(ctx, query)
                if el is not None and el.bounds:
                    return
            raise base.StepFailed("step %d: couldn't scroll %s %r into view" % (ctx.index, query[0], query[1]))
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
