# DevFlow (.NET MAUI)

DevFlow is a testing, automation and debugging toolkit for .NET MAUI apps from the .NET team's MAUI Labs
(https://github.com/dotnet/maui-labs/tree/main/src/DevFlow). An agent inside the app's debug build serves its
visual tree, actions (tap, fill, scroll, navigate) and screenshots over HTTP on loopback; a CLI (`maui devflow`)
and an MCP server talk to it. It also covers plain .NET Android, iOS, Mac Catalyst and macOS apps through a native
agent. **It's marked experimental: commands and APIs can change between releases**; `maui devflow --help` on the
user's machine is the authority.

Use the `devflow` driver when a MAUI app already has the agent in its debug build (`AddMauiDevFlowAgent` in
`MauiProgram.cs`). It reaches screens by `AutomationId` without Appium or a test project.

## In the app

```xml
<PackageReference Include="Microsoft.Maui.DevFlow.Agent" />
```

```csharp
using Microsoft.Maui.DevFlow.Agent;

public static MauiApp CreateMauiApp()
{
    var builder = MauiApp.CreateBuilder();
    builder.UseMauiApp<App>();
#if DEBUG
    builder.AddMauiDevFlowAgent();
#endif
    return builder.Build();
}
```

- **Debug builds only.** The guard keeps the agent out of store builds; flag one that isn't guarded. DevFlow's
  XAML source maps embed developer file paths and XAML: its README says to turn them off for release and store
  builds (`DevFlowXamlSourceMapsEnabled=false`).
- Blazor Hybrid adds `Microsoft.Maui.DevFlow.Blazor`. Plain .NET apps (no MAUI):
  `Microsoft.Maui.DevFlow.Agent.Native`, started explicitly (`this.StartDevFlowAgent()` in `MainActivity.OnCreate`
  on Android, `DevFlowAgent.Start()` in `FinishedLaunching` on iOS, Mac Catalyst and macOS). GTK on Linux:
  `Microsoft.Maui.DevFlow.Agent.Gtk`.
- Give the controls the screens need an `AutomationId`: the agent, Appium and Maestro all find them by it.

## The CLI

```sh
dotnet tool install -g Microsoft.Maui.Cli --prerelease     # `maui devflow …`; `maui --version` (not `maui devflow --version`)
maui devflow list                                          # running apps with an agent (`agent list --json` too)
maui devflow agent wait                                    # until the app's agent answers
maui devflow ui tree                                       # the visual tree
maui devflow ui tap --automationId "search"                # or --text "Search", or an element id
maui devflow ui fill --automationId "search-field" "pasta"   # the text is the second positional
maui devflow ui query --automationId "plan-title" --wait-until exists --timeout 10   # or gone; --text, --selector (CSS)
maui devflow ui scroll --element <element id>              # into view; or --dy -400 (negative is down), --item-index
maui devflow ui gesture swipe --direction up               # [--element <id>] [--distance d]
maui devflow ui screenshot --output shot.png --scale native --overwrite
maui devflow theme set dark --scope app                    # light|dark|system, --scope app|system|auto
maui devflow ui --help                                     # everything else
```

- **Always `--scale native` on `ui screenshot`:** by default it scales down to 1× logical pixels. Without
  `--overwrite` it refuses to replace a file.
- `ui tap` has no `--selector`: query first, then tap the element's id (the driver does).
- Also there: `ui navigate <route>` (Shell routes), `ui tree --depth`, `ui alert detect|dismiss`, `ui permission
  grant`, `recording start|stop`.
- Global options: `--agent-port` (`-ap`), `--agent-host` (`-ah`), `--platform` (`-p`: `maccatalyst`, `android`,
  `ios`, `windows`; **default `maccatalyst`**, so name it for a phone), `--json`, `--no-json`.

## Where the agent listens

- On loopback. Its port comes from DevFlow's broker (`localhost:19223`, started on demand and gone after five
  idle minutes; it hands out agent ports in 10223–10899 and serves an Inspector at
  `http://localhost:19223/inspector/`), a `.mauidevflow` file, or 9223 as a last resort. `maui devflow list`
  shows them (`--json`: `id`, `project`, `tfm`, `platform`, `appName`, `port`, …). On Android the CLI runs `adb
  reverse tcp:19223` and `adb forward tcp:<agent port>` itself; the driver adds a forward of its own for direct
  HTTP, and removes it after. Don't guess ports; name one in the plan (`target.agentPort`) only when discovery
  can't.
- A versioned REST API under `/api/v1/` (JSON): `GET agent/status`, `GET ui/tree?depth=&window=`, `GET
  ui/elements?strategy=accessibility-id|css-selector|type|text|xpath&value=&limit=`, `GET
  ui/screenshot?elementId=&scale=native` (PNG), `POST ui/actions/tap` (`elementId`, or `x`, `y`), `fill`
  (`elementId`, `text`), `scroll` (`elementId`, `deltaX`, `deltaY`, `itemIndex`, `scrollToPosition`), `navigate`
  (`route`), `back`, `key`, `gesture`, `batch`. Elements carry `id`, `automationId`, `text`, `type`, `bounds` (in
  device-independent units) and `state`; errors are RFC 7807 problem details (501 for something a platform's
  backend doesn't support). WebSocket channels are under `/ws/v1/`; the OpenAPI spec is in the repository's
  `docs/DevFlow/spec/`.
- **Element ids belong to one capture of the tree:** query again after the screen changes (the driver finds each
  element afresh for every step).
- One client at a time: a global lease stops the Inspector, an IDE, MCP and the CLI driving the app at once. Close
  other DevFlow sessions before a capture run.

## The plan

```json
{ "id": "maui-iphone", "platform": "ios", "kind": "phone", "driver": "devflow", "width": 1320, "height": 2868,
  "target": { "deviceType": "iPhone 17 Pro Max" } }
```

```json
{ "id": "search", "steps": [
    { "launch": { "args": { "ScreenshotScreen": "plan" } } },
    { "tap": { "id": "search" } },
    { "type": { "id": "search-field", "text": "pasta" } },
    { "settle": true } ] }
```

**The device has a host.** `simctl` for Apple simulators, `adb` for Android (`target.host` overrides it; `"none"`
for a Mac Catalyst or Windows app). The host finds or creates and boots the dedicated device, installs the debug
build, sets the locale, appearance and clean status bar, launches the app (launch arguments, `ScreenshotSeed`) and
opens deep links, and puts it all back after. So one `target` carries both the host's settings (`deviceType`,
`runtime`, `udid`, `avd`, `serial`, `wmSize`, `density`, …: see [simctl.md](simctl.md), [adb.md](adb.md)) and the
agent's:

| `target` field | Meaning |
|---|---|
| `agentPort` | the agent's port, when the CLI can't discover it |
| `agentPlatform` | the CLI's `--platform` (default from the plan's platform: `ios`, `android`, `maccatalyst`, `windows`) |
| `appName` | which app's agent, when several are running |
| `agentTimeout` | seconds to wait for the agent after a launch (default 90) |
| `cli` | the CLI as a command list, when it isn't on `PATH` |
| `host` | `simctl`, `adb` or `none` |
| `screenshot` | `host` (default when there's a host) or `agent` |

After each `launch` the driver waits for the agent (`agent wait`, then `ui status`) and runs the screen's steps
through it: `tap`, `type`, `wait`, `scroll`, `back` (the agent's back action), `swipe`, `settle`, `script`.
Without a host, `launch`, `deepLink` and `url` are `skipped` (the report says so up front): start the app
yourself, or give it a host.
Elements by `id` (the `AutomationId`), `text`, `css` (Blazor Hybrid's web content) or `xpath`; not `label`. A
screenshot mode and the agent combine: the mode seeds the data, the agent taps to what the mode doesn't name.

## The picture

A store shot is the whole screen, status bar included. With a host, the picture is the host's (`simctl io …
screenshot --mask=ignored`, `adb exec-out screencap -p`): the device's whole framebuffer at its native size.
Without one (a Mac Catalyst or Windows app), or with `target.screenshot: "agent"`, it's the agent's
`ui screenshot --scale native`: the app's window at native pixels (on a Mac, with its window chrome), without the
system's bars. (The CLI's own screenshot on an iOS simulator goes through `simctl` and is the full screen.) Appearance
without a host is the app's theme (`theme set … --scope app`). Check the size and the top edge either way.

## Debug builds look different

A debug build can be slower and show what a release doesn't. Hide debug-only UI in the screenshot mode; check
every capture for it.
