"""The ``ailoha`` driver: apps with the Ailoha agent (.NET MAUI, native Android, Flutter, React Native, Expo,
WinUI 3, WPF; https://ailoha.dev), driven by the ``ailoha`` CLI (npm ``@ailoha/cli``, or ailoha.dev's installer).

The app adds the agent to its debug build only (MAUI ``Ailoha.Agent.Maui`` + ``builder.AddMauiDevFlowAgent()``
in ``#if DEBUG``; Android ``debugImplementation("com.ailoha:ailoha-android-agent:…")`` and
``AilohaAndroidAgent.start(…)``; Flutter ``ailoha_agent`` + ``initAgent()`` behind ``kDebugMode``; React Native
``@ailoha/react-native`` + ``initAgent()`` behind ``__DEV__``). The agent listens on loopback port 9233 (falling
back through 9238) and registers with the Ailoha broker on 19323; on Android, ``adb forward tcp:9233 tcp:9233``
(the CLI's discovery does it).

What this driver runs (``agentcli.py`` for the shared shape):

- ``ailoha ui tap --automationId X`` / ``--text X`` / ``<elementId>``; ``ailoha ui fill --automationId X "text"``
- ``ailoha ui query --automationId X --wait-until exists --timeout N`` (``--selector`` for CSS)
- ``ailoha ui scroll --element <id>`` / ``--dy -400``; ``ailoha ui swipe x1 y1 x2 y2 --duration ms``
- ``ailoha ui navigate --back``; ``ailoha ui wait-for-idle --timeout-ms 2000`` (before ``settle``'s frames)
- ``ailoha ui screenshot --output f.png --scale native --overwrite`` (without a host)
- ``ailoha agent wait`` / ``agent list --json`` / ``ui status``; ``ailoha ui tree --depth 1 --json`` (the
  window's size, for a swipe)

``--platform`` is the framework or platform (``maui``, ``flutter``, ``react-native``, ``expo``, ``android``,
``ios``, ``maccatalyst``, ``winui``, ``wpf``): ``target.agentPlatform`` says which, else the plan platform's.
"""

from __future__ import annotations

from . import base
from .agentcli import AgentCliDriver, element_from, parse_json


class AilohaDriver(AgentCliDriver):
    """Apps with the Ailoha agent, through ``ailoha``."""

    NAME = "ailoha"
    CLI = ("ailoha",)
    DEFAULT_PORT = 9233
    PLATFORM_ARGS = {"ios": "ios", "ipados": "ios", "android": "android", "macos": "maccatalyst",
                     "windows": "winui"}
    INSTALL = "install the CLI: curl -fsSL https://ailoha.dev/install.sh | bash, or npm install -g @ailoha/cli"

    def step_back(self, ctx, value):
        """``ui navigate --back``."""
        self.cli(ctx.device, ["ui", "navigate", "--back"])

    def step_settle(self, ctx, value):
        """``ui wait-for-idle`` (pending frames and animations), then two identical frames."""
        timeout = float((value or {}).get("timeout") or self.SETTLE_TIMEOUT) if isinstance(value, dict) \
            else self.SETTLE_TIMEOUT
        res = self.cli(ctx.device, ["ui", "wait-for-idle", "--timeout-ms", str(int(timeout * 1000))],
                       timeout=timeout + 30, check=False)
        if not res.ok:
            ctx.warn("ailoha's wait-for-idle didn't finish: %s" % (res.err or res.out).strip()[:200])
        AgentCliDriver.step_settle(self, ctx, value)

    def window_bounds(self, ctx):
        """The first window's bounds from ``ui tree --depth 1`` (agent units)."""
        tree = parse_json(self.cli(ctx.device, ["ui", "tree", "--depth", "1"], json_out=True,
                                   dry_output='[{"id": "w", "bounds": {"x": 0, "y": 0, "width": 400, '
                                              '"height": 800}}]').out)
        if isinstance(tree, dict):
            tree = tree.get("elements") or [tree]
        for item in tree or []:
            el = element_from(item)
            if el.bounds:
                return el.bounds
        raise base.StepFailed("step %d: the UI tree gave no window size to swipe in" % ctx.index)

    def step_swipe(self, ctx, value):
        """``ui swipe x1 y1 x2 y2``: ``from``/``to`` as given (the agent's units), or across the window's middle
        (half its size) the way ``direction`` says (``up`` moves the finger up), over ``ms``."""
        if isinstance(value, str):
            value = {"direction": value}
        value = value or {}
        if value.get("from") and value.get("to"):
            args = ["ui", "swipe"] + ["%d" % round(v) for v in list(value["from"]) + list(value["to"])]
            if value.get("ms"):
                args += ["--duration", str(int(value["ms"]))]
            self.cli(ctx.device, args)
            return
        direction = value.get("direction")
        if direction not in ("up", "down", "left", "right"):
            raise base.StepFailed("step %d: swipe needs a direction (up, down, left, right) or from and to" % ctx.index)
        query = base.element_query(value)
        bounds = self.wait_for(ctx, query, 10).bounds if query else self.window_bounds(ctx)
        if not bounds:
            raise base.StepFailed("step %d: no bounds to swipe in" % ctx.index)
        left, top, right, bottom = bounds
        cx, cy = (left + right) / 2.0, (top + bottom) / 2.0
        horizontal = direction in ("left", "right")
        d = float(value.get("distance") or ((right - left) if horizontal else (bottom - top)) / 2.0)
        dx, dy = {"up": (0, -d), "down": (0, d), "left": (-d, 0), "right": (d, 0)}[direction]
        x1, y1, x2, y2 = cx - dx / 2, cy - dy / 2, cx + dx / 2, cy + dy / 2
        args = ["ui", "swipe"] + ["%d" % round(v) for v in (x1, y1, x2, y2)]
        if value.get("ms"):
            args += ["--duration", str(int(value["ms"]))]
        self.cli(ctx.device, args)


DRIVER = AilohaDriver
