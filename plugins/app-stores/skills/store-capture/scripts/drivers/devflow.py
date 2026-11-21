"""The ``devflow`` driver: .NET MAUI (and plain .NET Android/iOS/Mac) apps with Microsoft's DevFlow agent
(dotnet/maui-labs, ``src/DevFlow``), driven by the ``maui devflow`` CLI.

The app references ``Microsoft.Maui.DevFlow.Agent`` and calls ``builder.AddMauiDevFlowAgent()`` inside
``#if DEBUG`` (plain .NET apps: ``Microsoft.Maui.DevFlow.Agent.Native``, ``StartDevFlowAgent()`` /
``DevFlowAgent.Start()``). The CLI is the ``Microsoft.Maui.Cli`` .NET tool (``dotnet tool install -g
Microsoft.Maui.Cli --prerelease``), command ``maui devflow …``. The agent listens on loopback; its port comes from
the broker (``localhost:19223``, ports 10223–10899), a ``.mauidevflow`` file, or 9223 as a last resort; the CLI
discovers it, and on Android sets up the ``adb reverse``/``adb forward`` itself.

What this driver runs (``agentcli.py`` for the shared shape, and for how it pins the agent of the app it launched
on the device it owns, never another simulator's or phone's):

- ``maui devflow agent list --json``, then ``GET /api/v1/agent/status`` on each agent's port (``device.id``,
  ``app.packageId``, ``app.processId``) to find ours; every later command gets ``--agent-port <port>`` (and on
  Android ``--device <serial>``)
- ``maui devflow ui tap --automationId X`` / ``--text X`` / ``<elementId>``
- ``maui devflow ui fill --automationId X "text"``
- ``maui devflow ui query --automationId X --wait-until exists --timeout N`` (``--selector`` for CSS)
- ``maui devflow ui tree --json`` (an xpath, and a native view's automationId the query misses)
- ``maui devflow ui scroll --element <id>`` / ``--dy -400``
- ``maui devflow ui gesture swipe --direction up [--element <id>] [--distance d]``
- ``maui devflow ui navigate ..`` (back, in a Shell app), else the host's back (Android), else the HTTP back
- ``maui devflow ui screenshot --output f.png --scale native --overwrite`` (without a host)
- ``maui devflow theme set dark --scope app`` (appearance without a host; ``system`` again after)
- ``maui devflow ui status``

DevFlow's limits on iOS (seen with preview.14): a tap is a semantic action, not a touch, so a tap gesture on an
unnamed parent (a ``Label`` inside a ``Grid`` that has the ``TapGestureRecognizer``) answers ``success: false``; a
point tap needs ``AgentOptions.EnableSyntheticTouch`` in the app; native menus (``UIMenu``) aren't in the tree.
The step then fails saying so: give the element with the gesture an ``AutomationId``, or capture that device with
the ``appium`` driver (XCUITest taps for real).
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
    DEVICE_FLAG = "--device"
    TAP_ADVICE = (" (DevFlow taps are semantic actions, not touches: a gesture on an unnamed parent isn't reached, "
                  "point taps need AgentOptions.EnableSyntheticTouch, native menus aren't in the tree. Give the "
                  "element with the gesture an AutomationId, or capture this device with the appium driver)")

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

    def step_back(self, ctx, value):
        """Back: ``ui navigate ..`` (Shell's back) through the CLI; else the host's back (Android's key); else the
        agent's HTTP back action, which another client's lease can turn away (then a clear error)."""
        ok, message = self.outcome(self.cli(ctx.device, ["ui", "navigate", ".."], check=False))
        if ok:
            return
        if self.host_has(ctx.device, "back"):
            self.host(ctx.device).step_back(ctx, value)
            return
        try:
            reply = self.api(ctx.device, "POST", "/api/v1/ui/actions/back", body={})
        except base.DriverError as e:
            text = str(e).lower()
            if any(m in text for m in self.LEASE):
                raise base.StepFailed("step %d: back: DevFlow's lease turned the HTTP back away (another client "
                                      "drives the app); a Shell app goes back with `ui navigate ..`, which said: %s"
                                      % (ctx.index, message[:200])) from None
            raise
        if isinstance(reply, dict) and reply.get("success") is False:
            raise base.StepFailed("step %d: back: %s" % (ctx.index, reply.get("error") or reply.get("reason")))

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
        self.swipe_hold(ctx, value, can=False)
        args = ["ui", "gesture", "swipe", "--direction", direction]
        query = base.element_query(value)
        if query is not None:
            args += ["--element", self.element_id(ctx, query)]
        if value.get("distance"):
            args += ["--distance", "%g" % float(value["distance"])]
        self.cli(ctx.device, args)


DRIVER = DevFlowDriver
