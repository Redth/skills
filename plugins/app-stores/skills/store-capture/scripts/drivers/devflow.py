"""The ``devflow`` driver: .NET MAUI (and plain .NET Android/iOS/Mac) apps with Microsoft's DevFlow agent
(dotnet/maui-labs, ``src/DevFlow``), driven by the ``maui devflow`` CLI.

The app references ``Microsoft.Maui.DevFlow.Agent`` and calls ``builder.AddMauiDevFlowAgent()`` inside
``#if DEBUG`` (plain .NET apps: ``Microsoft.Maui.DevFlow.Agent.Native``, ``StartDevFlowAgent()`` /
``DevFlowAgent.Start()``). The CLI is the ``Microsoft.Maui.Cli`` .NET tool (``dotnet tool install -g
Microsoft.Maui.Cli --prerelease``), command ``maui devflow …``. The agent listens on loopback; its port comes from
the broker (``localhost:19223``, ports 10223–10899), a ``.mauidevflow`` file, or 9223 as a last resort; the CLI
discovers it, and on Android sets up the ``adb reverse``/``adb forward`` itself.

What this driver runs (``agentcli.py`` for the shared shape):

- ``maui devflow ui tap --automationId X`` / ``--text X`` / ``<elementId>``
- ``maui devflow ui fill --automationId X "text"``
- ``maui devflow ui query --automationId X --wait-until exists --timeout N`` (``--selector`` for CSS)
- ``maui devflow ui scroll --element <id>`` / ``--dy -400``
- ``maui devflow ui gesture swipe --direction up [--element <id>] [--distance d]``
- ``maui devflow ui screenshot --output f.png --scale native --overwrite`` (without a host)
- ``maui devflow theme set dark --scope app`` (appearance without a host; ``system`` again after)
- ``maui devflow agent wait`` / ``agent list --json`` / ``ui status``
- HTTP: ``POST /api/v1/ui/actions/back``, ``GET /api/v1/ui/elements?strategy=xpath&value=…``
"""

from __future__ import annotations

from . import base
from .agentcli import AgentCliDriver


class DevFlowDriver(AgentCliDriver):
    """.NET MAUI apps through the DevFlow agent and ``maui devflow``."""

    NAME = "devflow"
    CLI = ("maui", "devflow")
    DEFAULT_PORT = 9223
    PLATFORM_ARGS = {"ios": "ios", "ipados": "ios", "android": "android", "macos": "maccatalyst",
                     "windows": "windows"}
    INSTALL = "install the CLI: dotnet tool install -g Microsoft.Maui.Cli --prerelease"

    def __init__(self, options=None):
        """Set up."""
        AgentCliDriver.__init__(self, options)
        self.themed = False

    def apply_appearance(self, device, appearance, shot):
        """The host's system appearance; with no host, the app's theme (``theme set <light|dark> --scope app``)."""
        if self.host(device) is not None:
            AgentCliDriver.apply_appearance(self, device, appearance, shot)
            return
        res = self.cli(device, ["theme", "set", appearance, "--scope", "app"], check=False)
        if res.ok:
            self.themed = True
        else:
            shot.warnings.append("devflow couldn't set the app's theme to %s: %s" % (
                appearance, (res.err or res.out).strip()[:200]))

    def reset_app(self, device):
        """Put the app's theme back to the system's, then the shared clean-up."""
        warnings = []
        if self.themed:
            res = self.cli(device, ["theme", "set", "system", "--scope", "app"], check=False)
            if not res.ok:
                warnings.append("devflow couldn't put the app's theme back to the system's")
            self.themed = False
        return warnings + AgentCliDriver.reset_app(self, device)

    def step_swipe(self, ctx, value):
        """``ui gesture swipe --direction <d>`` on an element (``id``/``text`` …) or the current page."""
        if isinstance(value, str):
            value = {"direction": value}
        value = value or {}
        if value.get("from") or value.get("to"):
            raise base.StepFailed("step %d: devflow swipes by direction (its gesture API), not from/to points"
                                  % ctx.index)
        direction = value.get("direction")
        if direction not in ("up", "down", "left", "right"):
            raise base.StepFailed("step %d: swipe needs a direction (up, down, left, right)" % ctx.index)
        args = ["ui", "gesture", "swipe", "--direction", direction]
        query = base.element_query(value)
        if query is not None:
            args += ["--element", self.element_id(ctx, query)]
        if value.get("distance"):
            args += ["--distance", "%g" % float(value["distance"])]
        self.cli(ctx.device, args)


DRIVER = DevFlowDriver
