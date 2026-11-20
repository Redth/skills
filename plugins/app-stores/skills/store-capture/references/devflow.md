# DevFlow (.NET MAUI)

DevFlow is a testing, automation and debugging toolkit for .NET MAUI apps from the .NET team's MAUI Labs
(https://github.com/dotnet/maui-labs/tree/main/src/DevFlow). An agent inside the app's debug build serves its
visual tree, actions (tap, fill, scroll, navigate) and screenshots over HTTP on loopback; a CLI (`maui devflow`)
and an MCP server talk to it. It also covers plain .NET Android, iOS, Mac Catalyst and macOS apps through a native
agent. **It's marked experimental: commands and APIs can change between releases**; `maui devflow --help` on the
user's machine is the authority.

Use the `devflow` driver when a MAUI app already has the agent in its debug build (`AddMauiDevFlowAgent` in
`MauiProgram.cs`). It reaches controls by `AutomationId` (or text) without Appium or a test project, with the
limits [below](#what-it-cant-reach): on iOS, a screen behind an unnamed gesture or a native menu needs the
`appium` driver for that device.

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
  shows them (`--json`: `id`, `project`, `tfm`, `platform`, `appName`, `port`, `processId`, …). **While the broker
  runs it hands out the port**: a build's `-p:MauiDevFlowPort=…` isn't honoured, so a port fixed in the plan can
  point at another app's agent after a relaunch.
- On Android the CLI runs `adb reverse tcp:19223` and `adb forward tcp:<agent port>` itself, to whichever device
  adb picks unless it's told: the driver passes `--device <serial>` (and `ANDROID_SERIAL`) on every command, and
  refuses to start without a serial when more than one device is attached. Its own forward for direct HTTP uses
  `adb -s <serial> forward --no-rebind` (never taking a port another device's forward holds) and is removed after.

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
- One client at a time: a lease stops the Inspector, an IDE, MCP and the CLI driving the app at once, and it
  turns away the HTTP API's *changes* (`{"success": false, "reason": "lease", "error": "Another DevFlow session is
  driving this app. Take control before mutating it."}`) while the CLI holds it. So the driver changes the app only
  through the CLI, one command at a time, and uses HTTP only to read; a CLI command turned away by another client
  ("Another DevFlow session is driving this app") is tried again a second later, three times, then fails saying a
  client holds the lease. Close other DevFlow sessions (the Inspector, an IDE's, an MCP server) before a run.
- **The HTTP element query takes `type`, `automationId`, `text` or `selector` on preview.14**, not the `strategy`
  and `value` the spec shows ("At least one query parameter required"). An `xpath` step tries the HTTP query, then
  reads the whole tree (`ui tree --json`) and evaluates the XPath there (ElementTree's subset; elements are named
  by their `type`, their fields are attributes: `//Button[@automationId='menu']`, `//Label[@text='Summary']`).

## Which agent: pinned to the app on the device it owns

The developer may have their own simulators or phone running the same app's debug build, each with an agent. The
driver never lets the CLI pick one. After every launch it:

1. lists the agents (`maui devflow agent list --json`);
2. reads each one's status (`GET /api/v1/agent/status`, a read that needs no lease): `device.id` (the
   simulator's UDID on iOS), `app.packageId` (the bundle id or package) and `app.processId`;
3. keeps the one that is **this plan's app on this device**: the package matches, and the device id is the
   dedicated simulator's UDID, or the process runs from that simulator's folder (`ps -o command= -p <pid>` shows
   `CoreSimulator/Devices/<UDID>/`), or on Android the process id is the one `adb -s <serial> shell pidof
   <package>` reports;
4. passes its `--agent-port` on every later command.

Waiting for it (`agentTimeout`, 90 s) replaces `agent wait`, which returns as soon as *any* agent connects. None
found is an error naming what is running; more than one of ours (two copies of the app) is an error too: never a
guess. `target.agentPort` names a port by hand (after checking `maui devflow list`) for an agent that can't be told
apart; its status is still checked, and a port that's another device's or app's agent is refused.

## What it can't reach

Seen with preview.14 on iOS simulators; check `maui devflow --help` and the release notes for later versions.

- **Taps are semantic actions, not touches.** `ui tap` invokes the element's own tap; a `Label` (or image) whose
  `TapGestureRecognizer` sits on an unnamed parent `Grid` answers `success: false`, and the driver fails the step
  saying so (a reply of `success: false` is never taken as done). Give the element that has the gesture an
  `AutomationId` (a change to the app, with the user), or tap its parent by id.
- **Point taps** (`ui tap --x --y`, or `tap: {x, y}`) need `AgentOptions.EnableSyntheticTouch` in the app; the
  status's `capabilities.syntheticTouch` says whether it's on.
- **Native menus** (`UIMenu` on a button, context menus) aren't in the tree.
- **Native views registered with the agent** show their `automationId` in `ui tree`, but `ui query`/`ui tap
  --automationId` don't find them: the driver falls back to the tree and taps them by the agent's own element id
  (`native:registered:<guid>`).
- **`ui scroll --element`** can answer `success: false` for an element below the fold: the driver then scrolls down
  step by step until it's found.
- **`ui tap` doesn't wait**: right after a launch an element may not be there yet. The driver waits for it (as a
  `wait` step would) before tapping when the first tap finds nothing.

When a screen needs any of these and the app can't change, switch that **device** to the `appium` driver (XCUITest
taps for real and reads native menus), keeping its `id`; other devices can stay on `devflow`.

- **The keyboard isn't in the tree** on iOS: the driver can't see or close it there. End a typing screen's steps
  with `{ "hideKeyboard": { "tap": <a label or title outside the field> } }`, and look at the picture (an asked-for
  keyboard check is `unchecked` on iOS). On Android the host (`adb`) sees and closes it.
- **Text** is the agent's own query (exact); when it finds nothing the driver looks in the tree, ignoring case and
  surrounding space, then for the words inside a longer text, as every driver does. An `xpath` the agent's HTTP
  query refuses is evaluated over the tree, with `contains()`, `not()`, `and`/`or`
  ([config.md](config.md#steps)).

## Foldables: DevFlow's fold control

The same CLI folds a foldable emulator or simulator **without an agent** (`maui devflow device fold get|set
folded|unfolded|partially-folded`, `--udid` for an iOS simulator with `--experimental`, `--device` for an Android
serial). The `simctl` host uses it for the iPhone Duo's `posture`, whichever driver captures the device (this one,
Ailoha, Appium); the `adb` host folds an Android emulator through its own console. Details and what was seen:
[simctl.md](simctl.md#the-iphone-duo).

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
| `agentPort` | the agent's port by hand, when it can't be told apart (checked against its status) |
| `agentPlatform` | the CLI's `--platform` (default from the plan's platform: `ios`, `android`, `maccatalyst`, `windows`) |
| `appName` | the app's display name, for an agent that reports no package |
| `agentTimeout` | seconds to wait for the agent after a launch (default 90) |
| `cli` | the CLI as a command list, when it isn't on `PATH` |
| `host` | `simctl`, `adb` or `none` |
| `screenshot` | `host` (default when there's a host) or `agent` |

After each `launch` the driver finds the app's agent again (the pinning above), waits for `ui status`, and runs the
screen's steps through it: `tap`, `type`, `wait`, `scroll`, `back` (`ui navigate ..` in a Shell app; else the host's
back key on Android; else the HTTP back action, which a held lease turns away), `swipe`, `settle`, `script`, and
`appFile` through the host.
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

## Building for capture

- **iOS simulator:** `dotnet build -f net10.0-ios -c Debug -p:RuntimeIdentifier=iossimulator-arm64`; the plan's
  `app.ios.app` is the `.app` under `bin/Debug/<tfm>/iossimulator-arm64/`.
- **Android:** a Debug build is made for Fast Deployment by default: its assemblies aren't in the APK, so after
  `adb install` it crashes on start. Build with `-p:EmbedAssembliesIntoApk=true` (the `adb` host warns when it sees
  an APK without them); the plan's `app.android.apk` is the `*-Signed.apk`.
- **After updating the app, build clean.** The first iOS build after pulling a newer app failed to link
  (`_OBJC_CLASS_$_…` undefined) from stale intermediate output; a clean build fixed it. Before the first capture
  after an update, delete the target framework's `obj/` and `bin/` folders (or `dotnet clean` with the same `-f`
  and `-c`, then build), for every platform the plan captures ([staging.md](staging.md#7-updating-when-the-app-changed)).
- Launch values reach a MAUI app as `NSUserDefaults` (iOS launch arguments), environment variables
  (`SIMCTL_CHILD_` on iOS only) and intent extras (Android): give the plan both `args` and `env` with the same keys
  (best in `staging.launch`) and each platform reads its own.

## Debug builds look different

A debug build can be slower and show what a release doesn't. Hide debug-only UI in the screenshot mode; check
every capture for it.
